#!/usr/bin/env python3
"""3옴니휠 베이스를 키보드로 직접 몬다. (라즈베리파이에서 실행)

팔도 네트워크도 쓰지 않는다. 오른팔 버스에 물린 바퀴 3개(ID 7/8/9)만 열어
VELOCITY 모드로 돌린다. 배선·회전 방향·속도 감각을 확인하는 용도.

    W / S      전진 / 후진
    A / D      좌 / 우 게걸음
    Q / E      좌 / 우 회전
    Z / X      속도 내림 / 올림
    SPACE      즉시 정지
    Q 가 회전이므로 종료는  Ctrl+C

터미널 입력(termios)만 쓰므로 SSH 에서 그대로 동작하고 추가 설치가 필요 없다.
터미널은 키를 누른 것만 알려주고 뗀 것은 알려주지 않으므로, 마지막 입력 후
일정 시간이 지나면 자동으로 멈춘다. 자동반복의 첫 공백(약 500ms)과 떼었을 때의
반응성을 둘 다 맞추려고 유지 시간을 두 단계로 둔다 (HOLD_FIRST / HOLD_REPEAT).

주의
    * host (bi_so_base_host) 와 ROS 바퀴 드라이버를 먼저 끌 것.
    * 로봇을 받침대에 올려 바퀴를 띄운 상태에서 실행할 것.

사용법
    source ~/venv/lerobot_0.6/bin/activate
    python ~/base_wasd.py
    python ~/base_wasd.py /dev/so101_follower_left
"""

import select
import sys
import termios
import time
import tty

import numpy as np

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus, OperatingMode

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/so101_follower_right"

# ── 로봇 상수 — bi_so_base_follower.py 와 같아야 한다 ────────────────────
WHEEL_RADIUS = 0.05
BASE_RADIUS = 0.125
WHEEL_ANGLES_DEG = (240.0, 0.0, 120.0)
MAX_RAW = 3000  # 서보에 넣을 수 있는 속도 상한

MOTORS = {
    "base_left_wheel": Motor(7, "sts3215", MotorNormMode.RANGE_M100_100),
    "base_back_wheel": Motor(8, "sts3215", MotorNormMode.RANGE_M100_100),
    "base_right_wheel": Motor(9, "sts3215", MotorNormMode.RANGE_M100_100),
}

# ── 속도 ────────────────────────────────────────────────────────────────
SPEED_MIN, SPEED_MAX, SPEED_STEP = 0.05, 0.50, 0.05  # m/s
SPEED_START = 0.15
TURN_PER_SPEED = 240.0  # 0.25 m/s -> 60 deg/s

# 터미널 자동반복은 첫 키와 두 번째 키 사이가 길다 (보통 500ms). 그 공백 동안
# 멈춰 버리면 꾹 누르고 있어도 한 번 끊긴다. 그래서 유지 시간을 두 단계로 둔다.
#   첫 입력 직후        -> HOLD_FIRST (반복이 시작되기를 기다린다)
#   반복이 들어오는 중   -> HOLD_REPEAT (떼면 바로 멈추도록 짧게)
HOLD_FIRST = 0.75
HOLD_REPEAT = 0.25
REPEAT_GAP = 0.2  # 이 간격보다 촘촘히 들어오면 '반복 중'으로 본다
TICK = 0.05

MOVE_KEYS = {  # 키 -> (x, y, theta) 부호와 표시 이름
    "w": ((1, 0, 0), "전진"),
    "s": ((-1, 0, 0), "후진"),
    "a": ((0, 1, 0), "좌 게걸음"),
    "d": ((0, -1, 0), "우 게걸음"),
    "q": ((0, 0, 1), "좌회전"),
    "e": ((0, 0, -1), "우회전"),
}

C = {"r": "\033[0m", "b": "\033[1m", "dim": "\033[2m",
     "g": "\033[32m", "y": "\033[33m", "c": "\033[36m", "red": "\033[31m"}
if not sys.stdout.isatty():
    C = dict.fromkeys(C, "")


def wheel_matrix() -> np.ndarray:
    angles = np.radians(np.array(WHEEL_ANGLES_DEG) - 90.0)
    return np.array([[np.cos(a), np.sin(a), BASE_RADIUS] for a in angles])


def body_to_wheel_raw(x: float, y: float, theta_deg: float) -> dict[str, int]:
    """몸통 속도(m/s, deg/s)를 바퀴 3개의 서보 속도값으로 바꾼다."""
    velocity = np.array([x, y, np.radians(theta_deg)])
    wheel_degps = (wheel_matrix().dot(velocity) / WHEEL_RADIUS) * (180.0 / np.pi)
    steps_per_deg = 4096.0 / 360.0
    peak = max(abs(d) * steps_per_deg for d in wheel_degps)
    if peak > MAX_RAW:  # 한 바퀴라도 상한을 넘으면 셋 다 같은 비율로 줄인다
        wheel_degps = wheel_degps * (MAX_RAW / peak)
    raw = [max(-0x8000, min(0x7FFF, int(round(d * steps_per_deg)))) for d in wheel_degps]
    return dict(zip(MOTORS, raw, strict=True))


def read_keys() -> list[str]:
    """버퍼에 쌓인 키를 전부 읽는다. 블로킹하지 않는다."""
    keys = []
    while select.select([sys.stdin], [], [], 0)[0]:
        ch = sys.stdin.read(1)
        if not ch:
            break
        keys.append(ch)
    return keys


def bar(value: float, lo: float, hi: float, width: int = 20) -> str:
    filled = int(round((value - lo) / (hi - lo) * width))
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def banner() -> None:
    print(f"\n{C['b']}  W/S{C['r']} 전후   {C['b']}A/D{C['r']} 게걸음   "
          f"{C['b']}Q/E{C['r']} 좌우회전   {C['b']}Z/X{C['r']} 속도   "
          f"{C['b']}SPACE{C['r']} 정지   {C['b']}Ctrl+C{C['r']} 종료")
    print(f"  {C['dim']}키를 꾹 누르면 계속 갑니다. 떼면 {HOLD_REPEAT}초 뒤 멈춥니다.{C['r']}\n")


def main() -> None:
    print(f"포트: {PORT}")
    bus = FeetechMotorsBus(port=PORT, motors=MOTORS)

    try:
        bus.connect(handshake=False)
    except Exception as exc:
        print(f"{C['red']}포트를 열 수 없습니다: {exc}{C['r']}")
        print(f"{C['dim']}  host 가 돌고 있으면 먼저 끄세요:  pkill -f \"[b]i_so_base_host\"{C['r']}")
        return

    found = bus.broadcast_ping() or {}
    missing = [m.id for m in MOTORS.values() if m.id not in found]
    if missing:
        # 응답이 없으면 disconnect() 가 토크 해제를 시도하다 또 터진다. 포트만 닫는다.
        print(f"{C['red']}>>> 바퀴 ID {missing} 가 응답하지 않습니다.{C['r']}")
        print(f"    응답한 ID: {sorted(found) if found else '없음'}")
        print(f"{C['dim']}  · 로봇 전원이 켜져 있는지 확인하세요.{C['r']}")
        print(f"{C['dim']}  · 다른 포트일 수 있습니다:  python {sys.argv[0]} /dev/so101_follower_left{C['r']}")
        try:
            bus.port_handler.closePort()
        except Exception:
            pass
        return

    print(f"응답한 ID: {sorted(found)}")
    print("VELOCITY 모드로 전환...")
    bus.disable_torque(list(MOTORS))
    for name in MOTORS:
        bus.write("Operating_Mode", name, OperatingMode.VELOCITY.value)
    bus.enable_torque(list(MOTORS))

    banner()

    speed = SPEED_START
    cmd = (0.0, 0.0, 0.0)
    label = "정지"
    last_key_t = 0.0
    repeating = False  # 자동반복이 흐르고 있는지
    lines = 0

    old_attrs = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())
        while True:
            for ch in read_keys():
                low = ch.lower()
                if ch == " ":
                    cmd, label, last_key_t, repeating = (0.0, 0.0, 0.0), "정지", 0.0, False
                elif low == "z":
                    speed = max(round(speed - SPEED_STEP, 2), SPEED_MIN)
                elif low == "x":
                    speed = min(round(speed + SPEED_STEP, 2), SPEED_MAX)
                elif low in MOVE_KEYS:
                    (sx, sy, st), label = MOVE_KEYS[low]
                    cmd = (sx * speed, sy * speed, st * speed * TURN_PER_SPEED)
                    now_t = time.time()
                    repeating = bool(last_key_t) and (now_t - last_key_t) < REPEAT_GAP
                    last_key_t = now_t

            hold = HOLD_REPEAT if repeating else HOLD_FIRST
            if last_key_t and time.time() - last_key_t > hold:
                cmd, label, last_key_t, repeating = (0.0, 0.0, 0.0), "정지", 0.0, False

            raw = body_to_wheel_raw(*cmd)
            bus.sync_write("Goal_Velocity", raw)

            try:
                now = bus.sync_read("Present_Velocity", list(MOTORS))
                meas = "  ".join(f"{v:>+6d}" for v in now.values())
            except Exception:
                meas = "   읽기 실패   "

            turn = speed * TURN_PER_SPEED
            moving = any(abs(v) > 1e-9 for v in cmd)
            col = C["g"] if moving else C["dim"]

            out = [
                f"  속도  {C['c']}[{bar(speed, SPEED_MIN, SPEED_MAX)}]{C['r']}  "
                f"{C['b']}{speed:4.2f} m/s{C['r']}  ·  {C['b']}{turn:5.1f} °/s{C['r']}"
                f"   {C['dim']}({int(round((speed - SPEED_MIN) / SPEED_STEP)) + 1}"
                f"/{int(round((SPEED_MAX - SPEED_MIN) / SPEED_STEP)) + 1}단){C['r']}",
                f"  동작  {col}{label:<10s}{C['r']}"
                f"  x {cmd[0]:+5.2f}   y {cmd[1]:+5.2f}   θ {cmd[2]:+6.1f}",
                f"  바퀴  목표 {'  '.join(f'{v:>+6d}' for v in raw.values())}",
                f"        실측 {meas}",
            ]
            if lines:
                sys.stdout.write(f"\033[{lines}A")
            for line in out:
                sys.stdout.write("\033[2K" + line + "\n")
            lines = len(out)
            sys.stdout.flush()
            time.sleep(TICK)

    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_attrs)
        print("\n정지 중...")
        try:
            bus.sync_write("Goal_Velocity", dict.fromkeys(MOTORS, 0), num_retry=5)
            bus.disable_torque(list(MOTORS))
            bus.disconnect()
        except Exception as exc:
            print(f"{C['y']}정지 처리 중 오류: {exc}{C['r']}")
            try:
                bus.port_handler.closePort()
            except Exception:
                pass
        print("종료")


if __name__ == "__main__":
    main()
