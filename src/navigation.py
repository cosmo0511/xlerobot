"""
navigation.py — 💻 PC 쪽에서 🛞 Pi-B 의 자율주행 노드에 목표를 보내는 얇은 클라이언트.

INTERFACE 규격:
    navigate_to(location_id) -> {"status": "arrived"|"failed"|"blocked",
                                 "location_id": str, "message": str}

■ ROS2 는 Pi-B 에만 있으면 됩니다
---------------------------------------------------------------------------
Nav2 액션 호출을 PC 에서 하면 PC 에도 ROS2 Jazzy 를 깔아야 합니다. Nav2 스택이
어차피 Pi-B 안에 다 있으므로, 액션 클라이언트도 거기(`src/nav_node.py`)로 옮겼습니다.
PC 는 팔 노드와 똑같이 ZMQ 로만 말합니다.

    💻 PC ──ZMQ──► 🦾 Pi-A  arm_node.py   (팔)
          ──ZMQ──► 🛞 Pi-B  nav_node.py   (주행)

이 파일에는 rclpy 임포트가 없습니다. PC 에 ROS2 를 설치할 필요가 없다는 뜻입니다.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from task_registry import TaskRegistry

logger = logging.getLogger(__name__)


class DryRunNavigator:
    """실제로 움직이지 않고 '도착했다'고만 답하는 가짜 자율주행."""

    def __init__(self, registry: TaskRegistry, travel_time_s: float = 1.0):
        self.registry = registry
        self.travel_time_s = travel_time_s

    def navigate_to(self, location_id: str) -> dict[str, Any]:
        if location_id not in self.registry.locations:
            return {"status": "failed", "location_id": location_id,
                    "message": f"알 수 없는 위치: {location_id}"}
        name = self.registry.locations[location_id].name
        logger.info("[dry-run] %s(%s) 로 이동하는 척 ... %.1fs", name, location_id, self.travel_time_s)
        time.sleep(self.travel_time_s)
        return {"status": "arrived", "location_id": location_id, "message": f"{name} 도착(가짜)"}

    def shutdown(self) -> None:
        pass


class NoNavigator:
    """자율주행을 안 쓸 때. 이동 단계를 건너뜁니다 (바퀴는 정책이 직접 냄)."""

    def __init__(self, registry: TaskRegistry):
        self.registry = registry

    def navigate_to(self, location_id: str) -> dict[str, Any]:
        if location_id not in self.registry.locations:
            return {"status": "failed", "location_id": location_id,
                    "message": f"알 수 없는 위치: {location_id}"}
        return {"status": "arrived", "location_id": location_id,
                "message": "자율주행 안 씀 — 이동 단계 건너뜀"}

    def shutdown(self) -> None:
        pass


class NavNodeClient:
    """Pi-B 의 nav_node.py 에 ZMQ REQ 로 목표를 보냅니다."""

    def __init__(self, nav_cfg: dict):
        import zmq

        self._zmq = zmq
        self.address = nav_cfg["control_address"]
        # 이동 자체가 오래 걸리므로, Pi-B 의 타임아웃보다 넉넉하게 기다립니다.
        self.timeout_s = float(nav_cfg.get("timeout_s", 60.0)) + 30.0
        self._ctx = zmq.Context()
        self._sock = self._connect()

        ping = self._request({"cmd": "ping"}, timeout_s=5.0)
        if ping.get("status") != "arrived":
            raise RuntimeError(
                f"Pi-B 의 자율주행 노드({self.address})가 응답하지 않습니다: {ping.get('message')}\n"
                "Pi-B 에서 `python src/nav_node.py` 가 떠 있는지 확인하세요."
            )
        logger.info("자율주행 노드 연결됨: %s", self.address)

    def _connect(self):
        sock = self._ctx.socket(self._zmq.REQ)
        sock.setsockopt(self._zmq.LINGER, 0)
        sock.connect(self.address)
        return sock

    def _request(self, payload: dict, timeout_s: float) -> dict[str, Any]:
        """REQ/REP 한 왕복. 타임아웃이 나면 소켓을 새로 만듭니다.

        ZMQ REQ 소켓은 응답을 못 받으면 상태가 망가져서 이후 요청이 전부 막힙니다.
        """
        try:
            self._sock.send_string(json.dumps(payload, ensure_ascii=False))
            if self._sock.poll(int(timeout_s * 1000)) == 0:
                self._sock.close()
                self._sock = self._connect()
                return {"status": "failed",
                        "message": f"자율주행 노드 응답 없음 ({timeout_s:.0f}초 초과)"}
            return json.loads(self._sock.recv_string())
        except Exception as e:
            self._sock.close()
            self._sock = self._connect()
            return {"status": "failed", "message": f"자율주행 노드 통신 오류: {e}"}

    def navigate_to(self, location_id: str) -> dict[str, Any]:
        reply = self._request(
            {"cmd": "goto", "location_id": location_id}, timeout_s=self.timeout_s
        )
        reply.setdefault("location_id", location_id)
        return reply

    def shutdown(self) -> None:
        self._sock.close()
        self._ctx.term()


def make_navigator(registry: TaskRegistry, nav_cfg: dict, dry_run: bool = False):
    if not nav_cfg.get("enabled", True):
        return NoNavigator(registry)
    if dry_run:
        return DryRunNavigator(registry)
    return NavNodeClient(nav_cfg)
