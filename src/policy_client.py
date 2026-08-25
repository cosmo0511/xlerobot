"""
policy_client.py — 💻 PC 쪽에서 🦾 Pi-A 의 팔 노드에 명령을 보내는 얇은 클라이언트.

INTERFACE 규격:
    run_policy(task_prompt, max_seconds, expect_holding)
                          -> {"status": "done"|"failed", "message": str}
    park(hold_gripper)    -> {"status": "done"|"failed", "message": str}

■ 왜 이렇게 얇은가
---------------------------------------------------------------------------
Pi 가 두 대라서 역할이 깔끔하게 나뉩니다.

    🦾 Pi-A   팔 + 카메라 소유. 30Hz 제어 루프. SmolVLA 행동 청크 수신.   (arm_node.py)
    💻 PC     SmolVLA 추론 서버 + 에이전트 + Nav2 목표 전송              (여기)
    🛞 Pi-B   바퀴 + 라이다 + Nav2 스택

팔 제어 루프는 Pi-A 안에서 로컬로 돌아야 합니다(네트워크 지터가 30Hz 루프에 섞이면
동작이 끊깁니다). 그래서 PC 는 "이 태스크 해라 / 다 되면 알려줘"만 보냅니다.
실제 제어 코드는 `arm_node.py` 에 있습니다.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class DryRunPolicy:
    """Pi-A 없이 흐름만 확인할 때 쓰는 가짜 팔."""

    def __init__(self, work_time_s: float = 1.0):
        self.work_time_s = work_time_s

    def run(self, task_prompt: str, max_seconds: float = 0.0,
            expect_holding: bool = False) -> dict[str, Any]:
        logger.info("[dry-run] 정책 실행하는 척: %r (%.1fs)%s", task_prompt, self.work_time_s,
                    " [잡았는지 확인]" if expect_holding else "")
        time.sleep(self.work_time_s)
        return {"status": "done", "message": f"{task_prompt} 완료(가짜)"}

    def park(self, hold_gripper: bool = False) -> dict[str, Any]:
        logger.info("[dry-run] 팔 접는 척%s", " (물건 든 채로)" if hold_gripper else "")
        return {"status": "done", "message": "파킹(가짜)"}

    def close(self) -> None:
        pass


class ArmNodeClient:
    """Pi-A 의 arm_node.py 에 ZMQ REQ 로 명령을 보냅니다."""

    def __init__(self, arms_cfg: dict):
        import zmq

        self._zmq = zmq
        self.address = arms_cfg["control_address"]
        self._ctx = zmq.Context()
        self._sock = self._connect()

        ping = self._request({"cmd": "ping"}, timeout_s=5.0)
        if ping.get("status") != "done":
            raise RuntimeError(
                f"Pi-A 의 팔 노드({self.address})가 응답하지 않습니다: {ping.get('message')}\n"
                "Pi-A 에서 `python src/arm_node.py` 가 떠 있는지 확인하세요."
            )
        logger.info("팔 노드 연결됨: %s", self.address)

    def _connect(self):
        sock = self._ctx.socket(self._zmq.REQ)
        sock.setsockopt(self._zmq.LINGER, 0)
        sock.connect(self.address)
        return sock

    def _request(self, payload: dict, timeout_s: float) -> dict[str, Any]:
        """REQ/REP 한 왕복. 타임아웃이 나면 소켓을 새로 만듭니다.

        ZMQ REQ 소켓은 응답을 못 받으면 상태가 망가져서 다음 요청도 전부 막힙니다.
        (이걸 모르면 '한 번 타임아웃 난 뒤로 계속 먹통'이 됩니다)
        """
        try:
            self._sock.send_string(json.dumps(payload, ensure_ascii=False))
            if self._sock.poll(int(timeout_s * 1000)) == 0:
                self._sock.close()
                self._sock = self._connect()
                return {"status": "failed",
                        "message": f"팔 노드 응답 없음 ({timeout_s:.0f}초 초과)"}
            return json.loads(self._sock.recv_string())
        except Exception as e:
            self._sock.close()
            self._sock = self._connect()
            return {"status": "failed", "message": f"팔 노드 통신 오류: {e}"}

    # --- 공개 API ---------------------------------------------------------
    def run(self, task_prompt: str, max_seconds: float,
            expect_holding: bool = False) -> dict[str, Any]:
        # 에피소드 자체가 max_seconds 만큼 걸리므로 여유를 두고 기다립니다.
        return self._request(
            {"cmd": "run", "task": task_prompt, "max_seconds": max_seconds,
             "expect_holding": expect_holding},
            timeout_s=max_seconds + 30.0,
        )

    def park(self, hold_gripper: bool = False) -> dict[str, Any]:
        """팔을 주행 자세로 접습니다.

        hold_gripper=True 면 그리퍼는 건드리지 않습니다. 여러 단계짜리 태스크에서
        물건을 든 채로 다음 위치로 이동할 때 반드시 True 로 부르세요.
        """
        return self._request(
            {"cmd": "park", "hold_gripper": hold_gripper}, timeout_s=30.0
        )

    def close(self) -> None:
        self._sock.close()
        self._ctx.term()


def make_policy_runner(arms_cfg: dict, dry_run: bool = False):
    if dry_run:
        return DryRunPolicy()
    return ArmNodeClient(arms_cfg)
