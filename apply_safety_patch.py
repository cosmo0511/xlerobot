"""
arm_node.py 에 안전정지(safety_guard)를 자동으로 끼워 넣는 스크립트.
원본은 arm_node.py.bak 으로 백업합니다.

    cd ~/xlerobot
    python3 apply_safety_patch.py
"""

import shutil
import sys
from pathlib import Path

target = Path("src/arm_node.py")
src = target.read_text(encoding="utf-8")

if "safety_guard" in src:
    print("이미 패치되어 있습니다. 아무것도 안 바꿉니다.")
    sys.exit(0)

patches = [
    # 1) 초기화: 가드 생성
    (
        '        logger.info("팔 준비 완료")',
        '        from safety_guard import SafetyGuard\n'
        '        self.guard = SafetyGuard(threshold_deg=15.0)  # 양팔 동시 15 이상 튀면 정지\n'
        '        logger.info("팔 준비 완료")',
    ),
    # 2) run_task 시작: 기준 자세 잡고 send_action 가로채기 + 루프 안에서 확인
    (
        '        dt = 1.0 / self.fps\n'
        '        deadline = time.perf_counter() + max_seconds\n'
        '        steps = 0\n'
        '\n'
        '        try:\n'
        '            while time.perf_counter() < deadline:\n'
        '                tick = time.perf_counter()\n'
        '\n'
        '                if self.client.actions_available():\n'
        '                    self.client.control_loop_action()\n'
        '                    steps += 1\n',
        '        dt = 1.0 / self.fps\n'
        '        deadline = time.perf_counter() + max_seconds\n'
        '        steps = 0\n'
        '\n'
        '        # --- 안전정지: 양팔이 동시에 크게 튀는 명령은 보내지 않음 ---\n'
        '        from safety_guard import SafetyStop\n'
        '        self.guard.reset(self._observe(), task)\n'
        '        _robot = self.client.robot\n'
        '        _orig_send = _robot.send_action\n'
        '\n'
        '        def _guarded_send(action):\n'
        '            if not any(k.endswith(".pos") for k in action):\n'
        '                return _orig_send(action)  # 바퀴만 보내는 명령은 통과\n'
        '            try:\n'
        '                action = self.guard.check(action)\n'
        '            except SafetyStop:\n'
        '                return _orig_send(self.guard.hold_action())  # 고정 + 바퀴 정지\n'
        '            return _orig_send(action)\n'
        '\n'
        '        _robot.send_action = _guarded_send\n'
        '\n'
        '        try:\n'
        '            while time.perf_counter() < deadline:\n'
        '                tick = time.perf_counter()\n'
        '\n'
        '                if self.client.actions_available():\n'
        '                    self.client.control_loop_action()\n'
        '                    steps += 1\n'
        '                    if self.guard.tripped:\n'
        '                        raise SafetyStop(self.guard.message)\n',
    ),
    # 3) 안전정지면 큐 비우고 실패로 반환
    (
        '        except Exception as e:\n'
        '            logger.exception("에피소드 실행 중 예외")\n',
        '        except SafetyStop as e:\n'
        '            with self.client.action_queue_lock:\n'
        '                while not self.client.action_queue.empty():\n'
        '                    self.client.action_queue.get_nowait()\n'
        '            logger.warning("안전정지: %s", e)\n'
        '            return {"status": "failed", "message": f"안전정지(충돌 방지): {e}"}\n'
        '        except Exception as e:\n'
        '            logger.exception("에피소드 실행 중 예외")\n',
    ),
    # 4) 끝나면 send_action 원래대로
    (
        '        finally:\n'
        '            # 정책의 마지막 액션이 주행 중이었으면 바퀴가 계속 돕니다. 항상 세웁니다.\n',
        '        finally:\n'
        '            _robot.send_action = _orig_send  # 안전검사 해제 (park 등은 검사 안 함)\n'
        '            # 정책의 마지막 액션이 주행 중이었으면 바퀴가 계속 돕니다. 항상 세웁니다.\n',
    ),
]

for i, (old, new) in enumerate(patches, 1):
    n = src.count(old)
    if n != 1:
        print(f"✗ {i}번 위치를 찾지 못했습니다 (찾은 개수 {n}). 아무것도 안 바꿉니다.")
        sys.exit(1)
    src = src.replace(old, new)

shutil.copy(target, target.with_suffix(".py.bak"))
target.write_text(src, encoding="utf-8")
print("✓ 패치 완료. 원본은 src/arm_node.py.bak")
