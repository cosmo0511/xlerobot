"""
nav_node.py — 🛞 Pi-B(르키위 라즈베리파이)에서 상시 실행하는 프로세스.

    실행:  source /opt/ros/jazzy/setup.bash
           source ~/ros2_ws/install/setup.bash
           python src/nav_node.py

■ 이 파일이 하는 일
---------------------------------------------------------------------------
Nav2 에 목표 pose 를 던지고 도착을 기다립니다. 그리고 그 결과를 ZMQ 로 PC 에 알려줍니다.

    PC 에서:  {"cmd": "goto", "location_id": "bedroom"}
      -> Nav2 NavigateToPose 액션 전송 -> 도착 대기
      -> {"status": "arrived"|"failed"|"blocked", "message": str}

■ 왜 PC 가 아니라 여기서 도나
---------------------------------------------------------------------------
처음엔 PC 에서 Nav2 액션을 호출하게 짰는데, 그러면 **PC 에도 ROS2 Jazzy 를 깔아야**
합니다. Nav2 스택이 어차피 Pi-B 안에 다 있는데 클라이언트 하나 때문에 PC 에 ROS2 를
설치하는 건 낭비입니다.

이렇게 옮기면 ROS2 는 Pi-B 한 대에만 있으면 되고, PC 는 팔 노드와 똑같이 ZMQ 로만
말합니다. 구조도 대칭이 됩니다.

    💻 PC ──ZMQ──► 🦾 Pi-A  arm_node.py   (팔)
          ──ZMQ──► 🛞 Pi-B  nav_node.py   (주행)

■ 이 파일이 안 하는 일
---------------------------------------------------------------------------
라이다 드라이버, 스캔 필터, IMU, EKF, AMCL, 코스트맵, 컨트롤러, 바퀴 구동 —
전부 별개 프로세스입니다. 이 파일은 그것들이 이미 돌고 있다고 전제하고,
`navigate_to_pose` 액션에 목표 하나를 던질 뿐입니다.
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

from task_registry import Pose, TaskRegistry, load_registry  # noqa: E402

logger = logging.getLogger("nav_node")

import rclpy  # noqa: E402
import rclpy.executors  # noqa: E402
from geometry_msgs.msg import PoseStamped  # noqa: E402
from nav2_msgs.action import NavigateToPose  # noqa: E402
from rclpy.action import ActionClient  # noqa: E402

# action_msgs/msg/GoalStatus
STATUS_SUCCEEDED = 4
STATUS_CANCELED = 5
STATUS_ABORTED = 6


class Nav2Bridge:
    """Nav2 NavigateToPose 액션 클라이언트."""

    def __init__(self, registry: TaskRegistry, nav_cfg: dict):
        self.registry = registry
        self.timeout_s = float(nav_cfg.get("timeout_s", 60.0))
        self.settle_s = float(nav_cfg.get("settle_s", 1.5))
        self.action_name = nav_cfg.get("action_name", "navigate_to_pose")

        if not rclpy.ok():
            rclpy.init()
        self._node = rclpy.create_node("xlerobot_nav_bridge")
        self._action_client = ActionClient(self._node, NavigateToPose, self.action_name)

        # goto 가 블로킹 호출이어야 하므로 스핀은 백그라운드에서 돕니다.
        self._executor = rclpy.executors.SingleThreadedExecutor()
        self._executor.add_node(self._node)
        threading.Thread(target=self._executor.spin, daemon=True).start()

        logger.info("Nav2 액션 서버 대기 중: %s", self.action_name)
        if self._action_client.wait_for_server(timeout_sec=10.0):
            logger.info("Nav2 연결됨")
        else:
            logger.warning(
                "Nav2 액션 서버(%s)가 아직 안 보입니다. "
                "nav2_bringup 을 띄우면 자동으로 붙습니다.", self.action_name
            )

    def goto(self, location_id: str) -> dict:
        """블로킹. 목표 위치에 도착할 때까지 기다렸다가 결과를 반환합니다."""
        if location_id not in self.registry.locations:
            return {"status": "failed",
                    "message": f"tasks.yaml 에 없는 위치: {location_id}"}

        loc = self.registry.locations[location_id]
        if loc.is_placeholder:
            return {"status": "failed",
                    "message": (f"{loc.name} 의 좌표가 아직 (0,0,0) 입니다. "
                                "tasks.yaml 에 실제 좌표를 채워 넣으세요.")}

        if not self._action_client.wait_for_server(timeout_sec=5.0):
            return {"status": "failed",
                    "message": (f"Nav2 액션 서버({self.action_name})가 응답하지 않습니다. "
                                "이 기기에서 nav2_bringup 이 떠 있는지 확인하세요.")}

        goal = NavigateToPose.Goal()
        goal.pose = self._to_pose_stamped(loc.pose)

        send_future = self._action_client.send_goal_async(goal)
        deadline = time.perf_counter() + self.timeout_s

        while not send_future.done():
            if time.perf_counter() > deadline:
                return {"status": "failed", "message": "Nav2 가 목표를 접수하지 않았습니다(타임아웃)."}
            time.sleep(0.05)

        goal_handle = send_future.result()
        if not goal_handle.accepted:
            return {"status": "blocked",
                    "message": "Nav2 가 목표를 거절했습니다(경로 없음 또는 목표가 장애물 위)."}

        result_future = goal_handle.get_result_async()
        while not result_future.done():
            if time.perf_counter() > deadline:
                goal_handle.cancel_goal_async()
                return {"status": "failed",
                        "message": f"{self.timeout_s:.0f}초 안에 도착하지 못했습니다."}
            time.sleep(0.05)

        status = result_future.result().status
        if status != STATUS_SUCCEEDED:
            kind = "blocked" if status == STATUS_ABORTED else "failed"
            return {"status": kind, "message": f"Nav2 종료 코드 {status} (4가 성공)."}

        # 도착 직후 트롤리 관성으로 흔들립니다. 팔을 쓰기 전에 가라앉을 때까지 대기.
        time.sleep(self.settle_s)
        return {"status": "arrived", "message": f"{loc.name} 도착"}

    def cancel(self) -> dict:
        """진행 중인 목표를 취소합니다(비상용)."""
        # 현재 목표 핸들을 따로 들고 있지 않으므로, Nav2 의 취소 API 를 쓰려면
        # goal_handle 을 보관하도록 확장하세요. 지금은 자리만 잡아둡니다.
        return {"status": "failed", "message": "cancel 은 아직 미구현입니다."}

    def shutdown(self) -> None:
        self._executor.shutdown()
        self._node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    def _to_pose_stamped(self, pose: Pose):
        msg = PoseStamped()
        msg.header.frame_id = "map"
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.pose.position.x = pose.x
        msg.pose.position.y = pose.y
        qx, qy, qz, qw = pose.as_quaternion()
        msg.pose.orientation.x = qx
        msg.pose.orientation.y = qy
        msg.pose.orientation.z = qz
        msg.pose.orientation.w = qw
        return msg


def serve(bridge: Nav2Bridge, bind_address: str) -> None:
    ctx = zmq.Context()
    sock = ctx.socket(zmq.REP)
    sock.bind(bind_address)
    logger.info("제어 소켓 대기 중: %s", bind_address)

    handlers = {
        "ping": lambda req: {"status": "arrived", "message": "nav node alive"},
        "goto": lambda req: bridge.goto(req["location_id"]),
        "cancel": lambda req: bridge.cancel(),
    }

    try:
        while True:
            req = json.loads(sock.recv_string())
            logger.info("명령 수신: %s", req)
            handler = handlers.get(req.get("cmd"))
            if handler is None:
                reply = {"status": "failed", "message": f"알 수 없는 명령: {req.get('cmd')}"}
            else:
                try:
                    reply = handler(req)
                except Exception as e:
                    logger.exception("명령 처리 실패")
                    reply = {"status": "failed", "message": str(e)}
            reply.setdefault("location_id", req.get("location_id", ""))
            sock.send_string(json.dumps(reply, ensure_ascii=False))
    except KeyboardInterrupt:
        logger.info("종료합니다.")
    finally:
        sock.close()
        ctx.term()


def main() -> None:
    ap = argparse.ArgumentParser(description="Pi-B 자율주행 노드")
    ap.add_argument("--config", default=str(PROJECT_ROOT / "config" / "robot.yaml"))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-12s %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    registry = load_registry()

    missing = registry.placeholder_locations()
    if missing:
        logger.warning("좌표가 아직 (0,0,0)인 위치: %s — tasks.yaml 을 채워주세요", missing)

    bridge = Nav2Bridge(registry, cfg["navigation"])
    try:
        serve(bridge, cfg["navigation"]["bind_address"])
    finally:
        bridge.shutdown()


if __name__ == "__main__":
    main()
