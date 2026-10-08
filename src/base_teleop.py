"""
base_teleop.py — 🛞 베이스(옴니휠) 모터만 따로 텔레옵하는 도구.

    python src/base_teleop.py              # 키보드로 베이스만 운전
    python src/base_teleop.py --scan        # 버스에 붙은 모터 ID 확인 (배선 점검)
    python src/base_teleop.py --test-wheels # 바퀴 하나씩 돌려서 ID·방향 확인

■ 왜 이 파일이 따로 있나
---------------------------------------------------------------------------
XLeRobot 기본 배선에서 **베이스 바퀴 모터 3개는 오른팔과 같은 시리얼 버스**에
데이지체인으로 붙어 있습니다 (오른팔 ID 1~6, 바퀴 ID 7·8·9).
그래서 "베이스만 움직이기"는 포트를 하나 열어서 **ID 7·8·9 에만** 명령을 보내는
일입니다. 팔 모터(1~6)는 버스에 올라와 있어도 이 프로세스가 아예 주소를 지정하지
않으므로 토크·목표값이 전혀 바뀌지 않습니다. 팔은 있던 자세 그대로 있습니다.

■ ⚠️ 같은 포트를 두 프로세스가 열면 안 됩니다
---------------------------------------------------------------------------
`arm_node.py` 가 오른팔 포트를 잡고 있는 상태에서 이걸 같이 띄우면, 리눅스는
시리얼 포트를 **막아주지 않습니다.** 두 프로세스의 패킷이 섞여서 양쪽 다 오동작합니다
(에러도 안 납니다). 그래서 시작할 때 포트를 쓰는 다른 프로세스가 있으면 거부합니다.
먼저 `arm_node.py` 를 내리고 이걸 쓰세요.

■ 바퀴 모터는 위치가 아니라 **속도**로 제어합니다
---------------------------------------------------------------------------
바퀴는 Operating_Mode=VELOCITY(1) 로 두고 `Goal_Velocity` 를 씁니다. 캘리브레이션이
필요 없습니다(정규화되는 레지스터는 Goal/Present_Position 뿐). 그래서 팔 캘리브레이션
파일 없이도 베이스만 바로 돌릴 수 있습니다.

■ 키 (robot.yaml 의 base.keys 에서 바꿀 수 있음)
---------------------------------------------------------------------------
    w/s  앞/뒤        a/d  좌/우 평행이동      q/e  좌/우 제자리 회전
    r/f  속도 단계 ↑/↓  space  즉시 정지        x · ESC · Ctrl-C  종료

기본은 **누르고 있는 동안 간다**(hold) 방식입니다. 터미널은 키를 뗀 걸 알려주지 않아서,
마지막 키 입력 후 `base.hold_s`(기본 0.6초) 가 지나면 자동으로 멈춥니다. 터미널 키
자동반복이 그 사이를 메워주기 때문에 누르고 있으면 계속 갑니다. 손을 떼면 0.6초 안에
섭니다. `--latch` 를 주면 한 번 누른 속도가 space/반대키까지 유지됩니다.
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import select
import sys
import termios
import time
import tty
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger("base_teleop")

# 바퀴 장착 각도. lerobot 의 LeKiwi 와 동일한 규약입니다 (240°, 0°, 120° - 90° 오프셋).
# 순서를 바꾸면 운동학이 깨집니다. 바퀴가 엉뚱하게 돌면 각도가 아니라
# robot.yaml 의 base.wheel_ids 를 고치세요.
WHEEL_ORDER = ("left", "back", "right")
WHEEL_ANGLES_DEG = {"left": 240.0 - 90.0, "back": 0.0 - 90.0, "right": 120.0 - 90.0}

STEPS_PER_DEG = 4096.0 / 360.0

OPPOSITE = {
    "forward": "backward", "backward": "forward",
    "left": "right", "right": "left",
    "rotate_left": "rotate_right", "rotate_right": "rotate_left",
}

DEFAULT_BASE_CFG = {
    "port": None,                 # None 이면 arms.right_port 를 씁니다
    "model": "sts3215",
    "wheel_ids": {"left": 7, "back": 8, "right": 9},
    "wheel_radius": 0.05,         # m
    "base_radius": 0.125,         # m — 베이스 중심에서 바퀴까지
    "max_raw": 3000,              # 바퀴 하나당 최대 raw 속도(틱)
    "speed_levels": [
        {"xy": 0.1, "theta": 30},   # 느림
        {"xy": 0.2, "theta": 60},   # 보통
        {"xy": 0.3, "theta": 90},   # 빠름
    ],
    "hold_s": 0.6,
    "loop_hz": 30,
    "keys": {
        "forward": "w", "backward": "s",
        "left": "a", "right": "d",
        "rotate_left": "q", "rotate_right": "e",
        "speed_up": "r", "speed_down": "f",
        "stop": " ", "quit": "x",
    },
}


# =============================================================================
# 설정
# =============================================================================
def load_base_cfg(config_path: str | Path, port_override: str | None = None) -> dict:
    """robot.yaml -> base 설정. base 블록이 없으면 기본값으로 돕니다."""
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    user = cfg.get("base") or {}

    base = {**DEFAULT_BASE_CFG, **user}
    base["wheel_ids"] = {**DEFAULT_BASE_CFG["wheel_ids"], **(user.get("wheel_ids") or {})}
    base["keys"] = {**DEFAULT_BASE_CFG["keys"], **(user.get("keys") or {})}

    # 포트: 명령행 > base.port > arms.right_port (기본 배선에서 바퀴는 오른팔 버스)
    port = port_override or user.get("port") or (cfg.get("arms") or {}).get("right_port")
    if not port:
        raise SystemExit(
            "포트를 못 찾았습니다. robot.yaml 의 base.port 나 arms.right_port 를 채우거나 "
            "--port /dev/ttyACM1 로 직접 주세요."
        )
    base["port"] = port
    return base


# =============================================================================
# 운동학 — 몸체 속도(x, y, theta) -> 바퀴 raw 속도
# =============================================================================
def body_to_wheel_raw(x: float, y: float, theta_deg: float,
                      wheel_radius: float = 0.05, base_radius: float = 0.125,
                      max_raw: int = 3000) -> dict[str, int]:
    """몸체 기준 속도를 바퀴 3개의 raw 속도로 바꿉니다.

    lerobot LeKiwi._body_to_wheel_raw 와 같은 식입니다. numpy 를 쓰지 않아서
    하드웨어·numpy 없이도 tests_smoke.py 에서 검증할 수 있습니다.

    Args:
        x: 전진(+) / 후진(-) 속도 [m/s]
        y: 좌(+) / 우(-) 평행이동 속도 [m/s]
        theta_deg: 반시계(+) 회전 속도 [deg/s]

    Returns:
        {"left": raw, "back": raw, "right": raw} — 부호 포함 정수.
        하나라도 max_raw 를 넘으면 **셋을 같은 비율로** 줄입니다(방향 유지).
    """
    theta_rad = math.radians(theta_deg)

    degps: dict[str, float] = {}
    for wheel in WHEEL_ORDER:
        a = math.radians(WHEEL_ANGLES_DEG[wheel])
        # 바퀴 접지점의 선속도 [m/s]
        linear = math.cos(a) * x + math.sin(a) * y + base_radius * theta_rad
        # 선속도 -> 바퀴 각속도 [deg/s]
        degps[wheel] = math.degrees(linear / wheel_radius)

    peak = max(abs(v) * STEPS_PER_DEG for v in degps.values())
    scale = (max_raw / peak) if peak > max_raw else 1.0

    out: dict[str, int] = {}
    for wheel, v in degps.items():
        raw = int(round(v * scale * STEPS_PER_DEG))
        out[wheel] = max(-0x8000, min(0x7FFF, raw))
    return out


# =============================================================================
# 포트 점유 검사 — 같은 tty 를 두 프로세스가 열면 패킷이 섞입니다
# =============================================================================
def port_users(port: str) -> list[tuple[int, str]]:
    """해당 시리얼 포트를 열고 있는 **다른** 프로세스 목록. (리눅스 /proc 기반)

    권한이 없어 못 읽는 프로세스는 조용히 건너뜁니다. 그래서 "비어 있음"이
    100% 보장은 아닙니다 — 그래도 arm_node.py 를 켜둔 채 실수로 띄우는 사고는 잡힙니다.
    """
    try:
        target = os.path.realpath(port)
    except OSError:
        return []

    found: list[tuple[int, str]] = []
    me = os.getpid()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == me:
            continue
        try:
            for fd in (entry / "fd").iterdir():
                if os.path.realpath(fd) == target:
                    cmd = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
                    found.append((pid, cmd.strip() or "?"))
                    break
        except (PermissionError, FileNotFoundError, ProcessLookupError, OSError):
            continue
    return found


# =============================================================================
# 버스 — 바퀴 3개만 등록합니다 (팔 모터는 주소를 지정하지 않음)
# =============================================================================
def wheel_motor_name(wheel: str) -> str:
    return f"base_{wheel}_wheel"


def open_wheel_bus(base_cfg: dict, handshake: bool = True):
    """바퀴 ID 만 등록한 FeetechMotorsBus 를 열어서 돌려줍니다."""
    try:
        from lerobot.motors import Motor, MotorNormMode
        from lerobot.motors.feetech import FeetechMotorsBus
    except ImportError as e:   # PC 에서 실수로 띄웠을 때 바로 알 수 있게
        raise SystemExit(
            f"lerobot 모터 드라이버를 못 불러왔습니다 ({e}).\n"
            "  이 도구는 팔·바퀴가 USB 로 붙은 기기(🦾 Pi-A)에서 돌려야 합니다:\n"
            "    pip install -e \"lerobot[feetech]\""
        ) from e

    ids = base_cfg["wheel_ids"]
    model = base_cfg.get("model", "sts3215")
    motors = {
        wheel_motor_name(w): Motor(int(ids[w]), model, MotorNormMode.RANGE_M100_100)
        for w in WHEEL_ORDER
    }
    bus = FeetechMotorsBus(port=base_cfg["port"], motors=motors)
    bus.connect(handshake=handshake)
    return bus


def configure_wheels(bus) -> None:
    """바퀴를 속도 모드로. 팔 모터는 이 버스에 등록돼 있지 않으므로 영향 없음."""
    from lerobot.motors.feetech import OperatingMode

    bus.disable_torque()          # EEPROM 쓰려면 토크를 내려야 합니다
    bus.configure_motors()
    for name in bus.motors:
        bus.write("Operating_Mode", name, OperatingMode.VELOCITY.value)
    bus.enable_torque()


def write_wheel_raw(bus, raw_by_wheel: dict[str, int], num_retry: int = 0) -> None:
    bus.sync_write(
        "Goal_Velocity",
        {wheel_motor_name(w): int(v) for w, v in raw_by_wheel.items()},
        num_retry=num_retry,
    )


def stop_wheels(bus) -> None:
    write_wheel_raw(bus, dict.fromkeys(WHEEL_ORDER, 0), num_retry=5)


# =============================================================================
# 진단
# =============================================================================
def scan(base_cfg: dict) -> None:
    """버스에 응답하는 ID 전부 출력. 배선이 맞는지 이걸로 먼저 확인하세요."""
    bus = open_wheel_bus(base_cfg, handshake=False)   # ID 가 틀려도 일단 열립니다
    try:
        found = bus.broadcast_ping() or {}
    finally:
        bus.disconnect(disable_torque=False)          # 스캔은 토크를 건드리지 않습니다

    ids = sorted(found)
    want = {int(v): k for k, v in base_cfg["wheel_ids"].items()}
    print(f"{base_cfg['port']} 에서 응답한 모터 {len(ids)}개: {ids}")
    for i in ids:
        if i in want:
            role = f"바퀴({want[i]})"
        elif 1 <= i <= 6:
            role = "팔 관절(이 도구는 건드리지 않습니다)"
        else:
            role = "용도 미지정"
        print(f"  ID {i:>2} : {role}")

    missing = [f"{w}(ID {base_cfg['wheel_ids'][w]})" for w in WHEEL_ORDER
               if int(base_cfg["wheel_ids"][w]) not in found]
    if missing:
        print(f"\n⚠️ 설정에 적힌 바퀴가 안 보입니다: {', '.join(missing)}")
        print("   전원·체인 연결을 보고, ID 가 다르면 robot.yaml 의 base.wheel_ids 를 고치세요.")
    else:
        print("\n✅ 바퀴 3개 모두 응답. 이제 --test-wheels 로 방향을 확인하세요.")


def test_wheels(bus, raw: int, seconds: float) -> None:
    """바퀴를 하나씩 돌립니다. ID -> 실제 바퀴 매핑과 회전 방향 확인용."""
    print(f"바퀴를 하나씩 {seconds}초씩 돌립니다 (raw={raw}). 바퀴를 들거나 받쳐두세요.")
    for wheel in WHEEL_ORDER:
        print(f"  -> {wheel:>5} 바퀴 (ID {bus.motors[wheel_motor_name(wheel)].id})")
        write_wheel_raw(bus, {w: (raw if w == wheel else 0) for w in WHEEL_ORDER})
        time.sleep(seconds)
        stop_wheels(bus)
        time.sleep(0.4)
    print("끝. 도는 바퀴가 이름과 다르면 robot.yaml 의 base.wheel_ids 를 서로 바꾸세요.")


# =============================================================================
# 키 입력 -> 몸체 속도 (터미널 없이도 검증할 수 있게 분리)
# =============================================================================
class KeyState:
    """눌린 키를 모아서 몸체 속도(x, y, theta)를 만듭니다.

    터미널은 **키를 뗀 것을 알려주지 않습니다.** 그래서 hold 모드에서는 마지막 입력
    시각을 기억해두고 `hold_s` 가 지나면 그 방향을 끕니다. 키 자동반복이 그 사이를
    메워주므로 누르고 있는 동안은 계속 갑니다.

    latch 모드에서는 한 번 누른 방향이 정지키나 반대키까지 유지됩니다.
    """

    def __init__(self, keys: dict, speed_levels: list[dict],
                 hold_s: float = 0.6, latch: bool = False):
        self.keys = keys
        self.action_of = {v: k for k, v in keys.items()}
        self.levels = speed_levels
        self.hold_s = float(hold_s)
        self.latch = bool(latch)
        self.speed_index = 0
        self.quit = False
        self._pressed_at: dict[str, float] = {}

    def feed(self, chars: list[str], now: float) -> None:
        for ch in chars:
            if ch in ("\x03", "\x1b") or ch == self.keys["quit"]:
                self.quit = True
                return
            action = self.action_of.get(ch)
            if action == "speed_up":
                self.speed_index = min(self.speed_index + 1, len(self.levels) - 1)
            elif action == "speed_down":
                self.speed_index = max(self.speed_index - 1, 0)
            elif action == "stop":
                self._pressed_at.clear()
            elif action is not None:
                self._pressed_at[action] = now
                if self.latch:
                    self._pressed_at.pop(OPPOSITE.get(action, ""), None)

    def live(self, now: float) -> set[str]:
        if self.latch:
            return set(self._pressed_at)
        return {a for a, t in self._pressed_at.items() if now - t < self.hold_s}

    def velocity(self, now: float) -> tuple[float, float, float]:
        """(x [m/s], y [m/s], theta [deg/s]). 반대 방향을 같이 누르면 0 입니다."""
        live = self.live(now)
        level = self.levels[self.speed_index]
        xy, th = float(level["xy"]), float(level["theta"])
        x = xy * (("forward" in live) - ("backward" in live))
        y = xy * (("left" in live) - ("right" in live))
        theta = th * (("rotate_left" in live) - ("rotate_right" in live))
        return x, y, theta


# =============================================================================
# 키보드 텔레옵
# =============================================================================
def _pending_keys() -> list[str]:
    """지금 버퍼에 들어온 키를 전부 읽습니다 (블로킹 안 함)."""
    out = []
    while select.select([sys.stdin], [], [], 0)[0]:
        ch = sys.stdin.read(1)
        if not ch:
            break
        out.append(ch)
    return out


def teleop(bus, base_cfg: dict, latch: bool = False) -> None:
    if not sys.stdin.isatty():
        raise SystemExit("텔레옵은 터미널(tty)에서 실행해야 합니다. "
                         "스크립트로 돌리려면 --test-wheels 를 쓰세요.")

    keys = base_cfg["keys"]
    levels = base_cfg["speed_levels"]
    hold = float(base_cfg["hold_s"])
    dt = 1.0 / float(base_cfg.get("loop_hz", 30))
    state = KeyState(keys, levels, hold_s=hold, latch=latch)

    k = keys
    stop_label = "space" if k["stop"] == " " else k["stop"]
    print(f"\n베이스 텔레옵 — {base_cfg['port']} / 바퀴 ID {dict(base_cfg['wheel_ids'])}")
    print(f"  {k['forward']}/{k['backward']} 앞뒤   {k['left']}/{k['right']} 좌우   "
          f"{k['rotate_left']}/{k['rotate_right']} 회전   "
          f"{k['speed_up']}/{k['speed_down']} 속도   {stop_label} 정지   {k['quit']}/ESC 종료")
    print(f"  모드: {'latch (누른 속도 유지)' if latch else f'hold ({hold:g}초 입력 없으면 정지)'}\n")

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)                 # cbreak: Ctrl-C 가 그대로 동작합니다
    try:
        while True:
            tick = time.perf_counter()

            state.feed(_pending_keys(), tick)
            if state.quit:
                return

            x, y, theta = state.velocity(tick)

            raw = body_to_wheel_raw(
                x, y, theta,
                wheel_radius=float(base_cfg["wheel_radius"]),
                base_radius=float(base_cfg["base_radius"]),
                max_raw=int(base_cfg["max_raw"]),
            )
            write_wheel_raw(bus, raw)

            sys.stdout.write(
                f"\r속도단계 {state.speed_index + 1}/{len(levels)}  "
                f"x={x:+.2f} y={y:+.2f} θ={theta:+5.0f}  "
                f"raw L{raw['left']:+5d} B{raw['back']:+5d} R{raw['right']:+5d}   "
            )
            sys.stdout.flush()

            time.sleep(max(0.0, dt - (time.perf_counter() - tick)))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        print()


# =============================================================================
# main
# =============================================================================
def main() -> None:
    ap = argparse.ArgumentParser(description="베이스(옴니휠) 모터만 텔레옵")
    ap.add_argument("--config", default=str(PROJECT_ROOT / "config" / "robot.yaml"))
    ap.add_argument("--port", help="robot.yaml 대신 쓸 시리얼 포트 (예: /dev/ttyACM1)")
    ap.add_argument("--latch", action="store_true",
                    help="누른 속도를 space/반대키까지 유지 (기본은 손 떼면 정지)")
    ap.add_argument("--release", action="store_true",
                    help="종료할 때 바퀴 토크를 내립니다. 기본은 속도 0 으로 잡아둬서 "
                         "경사에서 안 밀립니다.")
    ap.add_argument("--scan", action="store_true", help="버스에 붙은 모터 ID 만 출력하고 종료")
    ap.add_argument("--test-wheels", action="store_true", help="바퀴를 하나씩 돌려서 ID·방향 확인")
    ap.add_argument("--test-raw", type=int, default=600, help="--test-wheels 의 raw 속도 (기본 600)")
    ap.add_argument("--test-seconds", type=float, default=1.5, help="--test-wheels 의 바퀴당 시간")
    ap.add_argument("--force", action="store_true",
                    help="다른 프로세스가 같은 포트를 열고 있어도 강행 (권장하지 않음)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-12s %(message)s",
        datefmt="%H:%M:%S",
    )

    base_cfg = load_base_cfg(args.config, args.port)

    busy = port_users(base_cfg["port"])
    if busy:
        who = "\n".join(f"    pid {pid}: {cmd}" for pid, cmd in busy)
        msg = (f"{base_cfg['port']} 를 다른 프로세스가 열고 있습니다:\n{who}\n"
               "  같은 시리얼 버스를 둘이 쓰면 패킷이 섞여서 양쪽 다 오동작합니다.\n"
               "  arm_node.py 를 먼저 내리세요.")
        if not args.force:
            raise SystemExit("✋ " + msg)
        logger.warning("%s\n  --force 로 강행합니다.", msg)

    if args.scan:
        scan(base_cfg)
        return

    bus = open_wheel_bus(base_cfg)
    try:
        configure_wheels(bus)
        if args.test_wheels:
            test_wheels(bus, args.test_raw, args.test_seconds)
        else:
            teleop(bus, base_cfg, latch=args.latch)
    finally:
        try:
            stop_wheels(bus)
        finally:
            bus.disconnect(disable_torque=args.release)


if __name__ == "__main__":
    main()
