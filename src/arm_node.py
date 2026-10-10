"""
arm_node.py — 💻 PC 에서 실행하는 추론 노드 (양팔 + 바퀴).

    먼저 라즈베리파이에서:  ./scripts/host.sh
    PC 에서:               lerobot-policy-server --host=127.0.0.1 --port=8080
                           python src/arm_node.py

■ 이 파일이 하는 일
---------------------------------------------------------------------------
1. 파이의 bi_so_base_host 에 `bi_so_base_client` 로 붙습니다 (ZMQ 5555/5556).
   **녹화(scripts/record.sh)와 똑같은 로봇 클래스**입니다. 그래서 관측·액션 키와
   순서(15차원: 팔 12 + x.vel/y.vel/theta.vel), 카메라 이름, 이미지(파이에서 JPEG
   으로 한 번 압축된 것)까지 학습 데이터와 같습니다.
   카메라 이름은 robot.yaml 의 arms.camera_set -> config/cameras.<이름>.yaml.
2. 같은 PC 의 SmolVLA 추론 서버에 gRPC 로 붙습니다 (lerobot async inference).
3. 에이전트가 보내는 명령을 ZMQ 로 받아서 처리합니다.

       {"cmd": "run", "task": "Pick up the red dice", "max_seconds": 60,
        "expect_holding": true}
         -> 그 태스크로 한 에피소드 실행 -> {"status": "done"|"failed", ...}
         -> expect_holding=true 면 끝나고 그리퍼를 확인해서 못 잡았으면 failed
         -> 정책이 바퀴도 움직입니다. 에피소드가 끝나면 바퀴를 항상 세웁니다.

       {"cmd": "park", "hold_gripper": false}  -> 팔을 주행 자세로 접음 (바퀴 정지)
                                                 hold_gripper=true 면 그리퍼는 그대로
                                                 (물건을 든 채로 이동할 때)
       {"cmd": "grippers"} -> 양쪽 그리퍼 현재값 (grasp_check 임계값 정할 때)
       {"cmd": "ping"}   -> 살아 있는지 확인

■ 왜 파이가 아니라 PC 에서 도나
---------------------------------------------------------------------------
녹화가 이미 이 경로(파이 호스트 → 무선 → PC 클라이언트, 카메라 30fps)로 돌고
있습니다. 추론을 같은 경로로 돌리면 "녹화 때와 추론 때 로봇이 다르게 보이는"
문제가 구조적으로 안 생깁니다.

파이에서 `bi_so_base_follower` 를 직접 여는 방식은 **지금 패치로는 안 됩니다.**
바퀴 모터가 오른팔 버스에 추가되면서 오른팔 관절 목록에도 잡혀, 액션·관측이
18차원(right_base_*_wheel.pos 포함)이 됩니다. 녹화 데이터는 15차원이라 안 맞습니다.

무선이 끊기면 파이 호스트의 워치독(500ms)이 바퀴를 세웁니다.

■ 파킹 포즈에 대해
---------------------------------------------------------------------------
이동 중에 팔이 벌어져 있으면 문틀·가구에 부딪히므로, 에이전트가 주행 전에 항상
`park` 를 먼저 호출합니다. 이건 하드웨어 제약이 아니라 안전 규칙입니다.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from pathlib import Path

import yaml
import zmq

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from camera_config import (  # noqa: E402  (sys.path 조정 뒤라서)
    flat_cameras,
    observation_keys,
    resolve_cameras,
)

logger = logging.getLogger("arm_node")


# =============================================================================
# 로봇 + 정책 클라이언트
# =============================================================================
BASE_KEYS = ("x.vel", "y.vel", "theta.vel")
BASE_STOP = dict.fromkeys(BASE_KEYS, 0.0)


def build_robot_config(arms_cfg: dict):
    """robot.yaml 의 arms 블록 -> BiSOBaseClientConfig

    카메라는 arms.camera_set 이 가리키는 config/cameras.<이름>.yaml 에서 옵니다.
    **녹화(scripts/record.sh)와 같은 파일, 같은 로봇 클래스**라서 키가 어긋날 수 없습니다.
    장치는 파이에 있으므로 여기서는 열지 않습니다 (장치 확인은 host.sh 가 파이에서).
    """
    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
    from lerobot.robots.bi_so_follower import BiSOBaseClientConfig

    cam_cfg = resolve_cameras(arms_cfg)
    logger.info("카메라 구성 %s — 관측 키: %s",
                arms_cfg.get("camera_set", "(robot.yaml 인라인)"),
                ", ".join(observation_keys(cam_cfg)))

    # 클라이언트는 이 이름으로 파이가 보낸 프레임을 받습니다 (flat 레이아웃).
    # index_or_path 는 클라이언트에서 안 쓰지만 설정 형식상 필요합니다.
    cameras = {
        name: OpenCVCameraConfig(
            index_or_path=c["index_or_path"],
            width=c.get("width", 640),
            height=c.get("height", 480),
            fps=c.get("fps", 30),
        )
        for name, c in flat_cameras(cam_cfg).items()
    }

    return BiSOBaseClientConfig(
        remote_ip=arms_cfg["remote_ip"],
        cameras=cameras,
        id=arms_cfg.get("id"),
    )


class ArmController:
    """lerobot RobotClient 를 감싸서 '태스크 하나 = 에피소드 하나'로 쓰게 만듭니다.

    RobotClient 의 기본 control_loop 는 태스크 하나로 무한히 돕니다.
    우리는 태스크를 바꿔가며 유한한 에피소드를 돌려야 하므로, 루프를 직접 씁니다.
    """

    def __init__(self, arms_cfg: dict, policy_cfg: dict):
        from lerobot.async_inference.configs import RobotClientConfig
        from lerobot.async_inference.robot_client import RobotClient

        self.arms_cfg = arms_cfg
        self.fps = float(policy_cfg.get("fps", 30))

        client_cfg = RobotClientConfig(
            robot=build_robot_config(arms_cfg),
            policy_type=policy_cfg.get("type", "smolvla"),
            pretrained_name_or_path=policy_cfg["path"],
            actions_per_chunk=int(policy_cfg.get("actions_per_chunk", 50)),
            server_address=policy_cfg["server_address"],
            policy_device=policy_cfg.get("device", "cuda"),
            chunk_size_threshold=float(policy_cfg.get("chunk_size_threshold", 0.5)),
            fps=int(self.fps),
            task="",  # 태스크는 에피소드마다 바꿔 넣습니다
        )

        logger.info("로봇 연결 및 정책 서버 접속 중: %s", policy_cfg["server_address"])
        self.client = RobotClient(client_cfg)
        if not self.client.start():
            raise RuntimeError(
                f"정책 서버({policy_cfg['server_address']})에 붙지 못했습니다. "
                "PC 에서 lerobot-policy-server 가 떠 있는지 확인하세요."
            )

        # 행동 수신 스레드 시작 -> 배리어에서 만나야 둘 다 출발합니다.
        self._rx_thread = threading.Thread(target=self.client.receive_actions, daemon=True)
        self._rx_thread.start()
        self.client.start_barrier.wait()
        logger.info("팔 준비 완료")

    def _observe(self, timeout_s: float = 2.0) -> dict:
        """관절값이 들어 있는 관측. 클라이언트는 첫 메시지를 받기 전엔 비어 있습니다."""
        deadline = time.perf_counter() + timeout_s
        while True:
            obs = self.client.robot.get_observation()
            if any(k.endswith(".pos") for k in obs) or time.perf_counter() > deadline:
                return obs
            time.sleep(0.02)

    def stop_base(self) -> None:
        """바퀴만 세웁니다. 팔 키를 안 보내면 호스트는 팔을 그 자리에 둡니다."""
        self.client.robot.send_action(dict(BASE_STOP))

    # --- 파킹 ------------------------------------------------------------
    def park(self, hold_gripper: bool = False) -> dict:
        """주행 자세로 부드럽게 접습니다. 목표까지 선형 보간해서 이동.

        Args:
            hold_gripper: True 면 그리퍼 관절은 건드리지 않습니다.
                여러 단계짜리 태스크에서 **물건을 든 채로 이동할 때** 필수입니다.
                (1번 책상에서 집어서 2번 책상으로 옮기는 경우 등)
                False 로 두면 travel_pose 의 gripper 값으로 움직여서 물건을 떨어뜨립니다.
        """
        target = dict(self.arms_cfg.get("travel_pose") or {})
        if not target:
            return {"status": "failed", "message": "travel_pose 가 robot.yaml 에 없습니다."}

        if hold_gripper:
            dropped = [k for k in target if k.endswith("gripper.pos")]
            for k in dropped:
                target.pop(k)
            logger.info("그리퍼 유지한 채 파킹 (물건 운반 중): %s 제외", dropped)

        duration = float(self.arms_cfg.get("park_seconds", 2.5))
        robot = self.client.robot
        obs = self._observe()
        start = {k: float(obs[k]) for k in target if k in obs}
        missing = [k for k in target if k not in obs]
        if missing:
            return {"status": "failed",
                    "message": f"travel_pose 의 관절 이름이 로봇과 다릅니다: {missing[:3]}"}

        dt = 1.0 / self.fps
        steps = max(1, int(duration * self.fps))
        for i in range(1, steps + 1):
            a = i / steps
            # 바퀴는 0 으로 같이 보냅니다 — 파킹 중에 굴러가면 안 됩니다.
            robot.send_action({**BASE_STOP,
                               **{k: start[k] + (target[k] - start[k]) * a for k in target}})
            time.sleep(dt)
        return {"status": "done", "message": "팔 파킹 완료"}

    # --- 잡았는지 판정 ------------------------------------------------------
    def gripper_positions(self) -> dict:
        """양쪽 그리퍼의 현재 값. grasp_check 임계값을 정할 때 쓰세요."""
        obs = self._observe()
        return {k: round(float(v), 2) for k, v in obs.items() if k.endswith("gripper.pos")}

    def _is_holding(self) -> tuple[bool, str]:
        """그리퍼 값으로 물건을 쥐고 있는지 판정.

        그리퍼가 **끝까지 닫혔으면** 사이에 아무것도 없다는 뜻입니다(= 헛집음).
        거의 안 닫혔으면 접근만 하고 못 잡은 것입니다.
        임계값은 robot.yaml 의 arms.grasp_check 에서 옵니다.
        """
        cfg = self.arms_cfg.get("grasp_check") or {}
        joint = cfg.get("joint")
        if not joint:
            # 설정이 없으면 판정을 건너뜁니다(기존 동작 유지).
            return True, "grasp_check 미설정 — 판정 생략"

        obs = self._observe()
        if joint not in obs:
            return False, f"grasp_check.joint {joint!r} 가 로봇 관측에 없습니다"

        value = float(obs[joint])
        lo, hi = float(cfg.get("min", 3.0)), float(cfg.get("max", 55.0))
        if value < lo:
            return False, f"그리퍼가 끝까지 닫혔습니다({joint}={value:.1f} < {lo}) — 헛집음"
        if value > hi:
            return False, f"그리퍼가 안 닫혔습니다({joint}={value:.1f} > {hi}) — 못 잡음"
        return True, f"잡음 확인({joint}={value:.1f})"

    # --- 에피소드 실행 ------------------------------------------------------
    def run_task(self, task: str, max_seconds: float,
                 expect_holding: bool = False) -> dict:
        """한 태스크를 max_seconds 동안 수행합니다.

        expect_holding=True 면 끝나고 그리퍼를 확인해서, 아무것도 못 잡았으면
        failed 를 돌려줍니다. 이게 없으면 못 집고도 다음 위치까지 가서
        빈 손으로 놓는 시늉을 합니다.
        """
        # 이전 태스크의 행동이 큐에 남아 있으면 첫 1초 동안 엉뚱한 동작이 나갑니다.
        # 반드시 비우고 시작합니다.
        with self.client.action_queue_lock:
            while not self.client.action_queue.empty():
                self.client.action_queue.get_nowait()
        self.client.must_go.set()

        dt = 1.0 / self.fps
        deadline = time.perf_counter() + max_seconds
        steps = 0

        try:
            while time.perf_counter() < deadline:
                tick = time.perf_counter()

                if self.client.actions_available():
                    self.client.control_loop_action()
                    steps += 1

                if self.client._ready_to_send_observation():
                    # 태스크 문자열은 관측마다 같이 실려 갑니다.
                    # -> 태스크 전환에 서버 재시작이나 정책 재로딩이 필요 없습니다.
                    self.client.control_loop_observation(task)

                time.sleep(max(0.0, dt - (time.perf_counter() - tick)))

        except Exception as e:
            logger.exception("에피소드 실행 중 예외")
            return {"status": "failed", "message": f"실행 오류: {e}"}
        finally:
            # 정책의 마지막 액션이 주행 중이었으면 바퀴가 계속 돕니다. 항상 세웁니다.
            try:
                self.stop_base()
            except Exception:
                logger.exception("바퀴 정지 명령 실패 — 호스트 워치독(500ms)에 맡깁니다")

        if steps == 0:
            return {"status": "failed",
                    "message": "정책에서 행동을 하나도 못 받았습니다. "
                               "정책 서버 로그와 카메라 이름을 확인하세요."}

        if expect_holding:
            holding, why = self._is_holding()
            if not holding:
                return {"status": "failed", "message": f"{task} — {why}"}
            logger.info("%s", why)

        return {"status": "done",
                "message": f"{task} 실행 종료 ({max_seconds:.0f}초, {steps} 스텝)"}

    def close(self) -> None:
        try:
            self.park()
        finally:
            self.client.stop()


# =============================================================================
# ZMQ 제어 서버
# =============================================================================
def serve(controller: ArmController, bind_address: str) -> None:
    ctx = zmq.Context()
    sock = ctx.socket(zmq.REP)
    sock.bind(bind_address)
    logger.info("제어 소켓 대기 중: %s", bind_address)

    handlers = {
        "ping": lambda req: {"status": "done", "message": "arm node alive"},
        "park": lambda req: controller.park(hold_gripper=bool(req.get("hold_gripper", False))),
        "run": lambda req: controller.run_task(
            req["task"], float(req.get("max_seconds", 180)),
            expect_holding=bool(req.get("expect_holding", False)),
        ),
        "grippers": lambda req: {"status": "done",
                                 "message": str(controller.gripper_positions())},
    }

    try:
        while True:
            req = json.loads(sock.recv_string())
            cmd = req.get("cmd")
            logger.info("명령 수신: %s", req)
            handler = handlers.get(cmd)
            if handler is None:
                reply = {"status": "failed", "message": f"알 수 없는 명령: {cmd}"}
            else:
                try:
                    reply = handler(req)
                except Exception as e:
                    logger.exception("명령 처리 실패")
                    reply = {"status": "failed", "message": str(e)}
            sock.send_string(json.dumps(reply, ensure_ascii=False))
    except KeyboardInterrupt:
        logger.info("종료합니다.")
    finally:
        sock.close()
        ctx.term()


def main() -> None:
    ap = argparse.ArgumentParser(description="PC 추론 노드 (양팔 + 바퀴)")
    ap.add_argument("--config", default=str(PROJECT_ROOT / "config" / "robot.yaml"))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-12s %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    controller = ArmController(cfg["arms"], cfg["policy"])
    try:
        controller.park()  # 시작하자마자 안전 자세로
        serve(controller, cfg["arms"]["bind_address"])
    finally:
        controller.close()


if __name__ == "__main__":
    main()
