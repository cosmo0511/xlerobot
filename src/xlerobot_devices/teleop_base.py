"""
teleop_base.py — 베이스(르키위 3옴니휠)만 키보드로 몹니다. 팔은 안 건드립니다.

    # 🦾 Pi 에서 직접 (제일 간단. host 도 캘리브레이션도 카메라도 필요 없음)
    PYTHONPATH=src python -m xlerobot_devices.teleop_base

    # 💻 노트북에서 host 를 통해 (Pi 에서 host.sh 가 떠 있어야 함)
    PYTHONPATH=src python -m xlerobot_devices.teleop_base --remote-ip 192.168.200.114

조작:
    i k      전진 / 후진
    j l      좌 / 우 (옴니휠이라 제자리에서 옆으로 밀립니다)
    u o      제자리 회전
    n m      속도 단계 올리기 / 내리기 (3단)
    스페이스  즉시 정지
    q        종료

■ 왜 pynput 을 안 쓰나
---------------------------------------------------------------------------
lerobot 의 KeyboardTeleop 은 pynput 을 씁니다. pynput 은 X 디스플레이가 있어야
해서 **SSH 로 붙은 Pi 에서는 안 됩니다.** 여기서는 터미널을 raw 모드로 두고
직접 읽습니다. SSH 로 들어와서 바로 쓸 수 있습니다.

■ 키를 "누르고 있는" 것을 어떻게 아나
---------------------------------------------------------------------------
터미널은 "눌림/뗌"이 아니라 "눌렸다"만 알려줍니다. 대신 키를 누르고 있으면
자동 반복(auto-repeat)으로 계속 들어옵니다. 그래서 키가 올 때마다 명령을 갱신하고
HOLD_S 동안 새 키가 없으면 정지합니다. 손을 떼면 0.4초 안에 멈춥니다.

■ 바퀴는 캘리브레이션이 필요 없습니다
---------------------------------------------------------------------------
무한 회전 관절이라 가동범위가 0~4095 로 고정입니다. 그래서 로컬 모드는 팔
캘리브레이션이 끝나지 않았어도 바로 돌아갑니다.
"""

import argparse
import logging
import select
import sys
import termios
import time
import tty

logger = logging.getLogger("teleop_base")

# 속도 3단. xlerobot.py / xlerobot_client.py 와 같은 값입니다.
SPEED_LEVELS = [
    {"xy": 0.1, "theta": 30},  # 느리게
    {"xy": 0.2, "theta": 60},  # 보통
    {"xy": 0.3, "theta": 90},  # 빠르게
]

# 마지막 키 입력 후 이 시간이 지나면 멈춥니다.
# 터미널 자동 반복 간격(보통 30ms 쯤)보다 넉넉해야 주행 중에 끊기지 않습니다.
HOLD_S = 0.4

FPS = 30

HELP = """
==================================================================
  베이스 텔레옵 — 바퀴만. 팔은 건드리지 않습니다.
==================================================================
   i / k     전진 / 후진
   j / l     좌 / 우 (옆으로 밀림)
   u / o     제자리 회전
   n / m     속도 올리기 / 내리기
   스페이스   정지
   q         종료
==================================================================
"""


class RawTerminal:
    """터미널을 raw 모드로 두고, 빠져나갈 때 반드시 되돌립니다.

    되돌리지 않으면 스크립트가 죽은 뒤 셸에 입력이 안 보입니다 (`reset` 해야 함).
    """

    def __enter__(self):
        if not sys.stdin.isatty():
            # nohup/파이프로 돌리면 키를 읽을 수 없습니다. termios 역추적 대신
            # 사람이 읽을 수 있는 말로 막습니다.
            raise SystemExit(
                "이 스크립트는 터미널에서 직접 실행해야 합니다 (키 입력을 읽습니다).\n"
                "SSH 로 붙어 있다면 그냥 실행하면 되고, nohup/파이프로는 안 됩니다."
            )
        self.fd = sys.stdin.fileno()
        self.saved = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self

    def __exit__(self, *exc):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)

    @staticmethod
    def drain_keys() -> list[str]:
        """지금 버퍼에 들어온 키를 전부 꺼냅니다 (블로킹 없음)."""
        keys = []
        while select.select([sys.stdin], [], [], 0)[0]:
            ch = sys.stdin.read(1)
            if not ch:
                break
            keys.append(ch.lower())
        return keys


def _velocity_from_keys(keys: list[str], speed_index: int) -> tuple[dict[str, float], int, bool]:
    """눌린 키 -> (몸체 속도, 새 속도단계, 종료할지)."""
    if "n" in keys:
        speed_index = min(speed_index + 1, len(SPEED_LEVELS) - 1)
    if "m" in keys:
        speed_index = max(speed_index - 1, 0)
    speed = SPEED_LEVELS[speed_index]

    x = y = theta = 0.0
    if "i" in keys:
        x += speed["xy"]
    if "k" in keys:
        x -= speed["xy"]
    if "j" in keys:
        y += speed["xy"]
    if "l" in keys:
        y -= speed["xy"]
    if "u" in keys:
        theta += speed["theta"]
    if "o" in keys:
        theta -= speed["theta"]

    quit_now = "q" in keys
    if " " in keys:  # 스페이스는 즉시 정지
        x = y = theta = 0.0

    return {"x.vel": x, "y.vel": y, "theta.vel": theta}, speed_index, quit_now


# =============================================================================
# 두 가지 백엔드. 둘 다 send(vel) / stop() / close() 만 있으면 됩니다.
# =============================================================================
class LocalBase:
    """Pi 에서 port2 를 직접 열고 바퀴 3개만 돌립니다.

    팔 모터(ID 1~6)는 건드리지 않습니다. 같은 버스에 있지만 쓰지 않을 뿐입니다.
    """

    def __init__(self, port: str):
        from lerobot.motors import Motor, MotorNormMode
        from lerobot.motors.feetech import FeetechMotorsBus, OperatingMode

        from .xlerobot import XLerobot

        self._to_wheel = XLerobot._body_to_wheel_raw
        self.wheels = ["base_left_wheel", "base_back_wheel", "base_right_wheel"]

        # 바퀴는 ID 7,8,9. 캘리브레이션 없이 엽니다 (무한회전이라 범위가 고정).
        self.bus = FeetechMotorsBus(
            port=port,
            motors={
                "base_left_wheel": Motor(7, "sts3215", MotorNormMode.RANGE_M100_100),
                "base_back_wheel": Motor(8, "sts3215", MotorNormMode.RANGE_M100_100),
                "base_right_wheel": Motor(9, "sts3215", MotorNormMode.RANGE_M100_100),
            },
        )
        self.bus.connect()
        self.bus.disable_torque()
        for name in self.wheels:
            self.bus.write("Operating_Mode", name, OperatingMode.VELOCITY.value)
        self.bus.enable_torque()
        logger.info("바퀴 3개 연결됨: %s", port)

    def send(self, vel: dict[str, float]) -> None:
        self.bus.sync_write(
            "Goal_Velocity",
            self._to_wheel(vel["x.vel"], vel["y.vel"], vel["theta.vel"]),
        )

    def stop(self) -> None:
        self.bus.sync_write("Goal_Velocity", dict.fromkeys(self.wheels, 0), num_retry=5)

    def close(self) -> None:
        self.stop()
        self.bus.disconnect()


class RemoteBase:
    """노트북에서 host 로 속도만 보냅니다.

    팔 키가 없는 부분 명령이라 host 는 팔을 그대로 둡니다.
    카메라 프레임은 받긴 하지만 쓰지 않습니다.
    """

    def __init__(self, remote_ip: str, port_cmd: int, port_obs: int):
        from .config_xlerobot import XLerobotClientConfig
        from .xlerobot_client import XLerobotClient

        self.client = XLerobotClient(
            XLerobotClientConfig(
                id="base_teleop",
                remote_ip=remote_ip,
                port_zmq_cmd=port_cmd,
                port_zmq_observations=port_obs,
                cameras={},  # 영상은 필요 없습니다
            )
        )
        self.client.connect()
        logger.info("host 접속됨: %s", remote_ip)

    def send(self, vel: dict[str, float]) -> None:
        self.client.send_action(dict(vel))

    def stop(self) -> None:
        self.send({"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0})

    def close(self) -> None:
        self.stop()
        self.client.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(description="베이스(바퀴)만 키보드로 조종")
    parser.add_argument(
        "--remote-ip",
        default=None,
        help="Pi 의 IP. 주면 host 를 통해(노트북에서), 안 주면 이 기기에서 직접(Pi에서).",
    )
    parser.add_argument("--port2", default="/dev/ttyACM1", help="로컬 모드: 바퀴가 달린 버스")
    parser.add_argument("--port-cmd", type=int, default=5555)
    parser.add_argument("--port-obs", type=int, default=5556)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.remote_ip:
        base = RemoteBase(args.remote_ip, args.port_cmd, args.port_obs)
    else:
        base = LocalBase(args.port2)

    print(HELP)
    speed_index = 0
    last_vel = {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}
    last_key_t = 0.0
    last_shown = None

    try:
        with RawTerminal() as term:
            while True:
                loop_start = time.perf_counter()
                keys = term.drain_keys()

                if keys:
                    vel, speed_index, quit_now = _velocity_from_keys(keys, speed_index)
                    if quit_now:
                        break
                    last_vel = vel
                    last_key_t = time.perf_counter()
                elif time.perf_counter() - last_key_t > HOLD_S:
                    # 손을 뗀 것으로 봅니다.
                    last_vel = {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}

                base.send(last_vel)

                shown = (round(last_vel["x.vel"], 2), round(last_vel["y.vel"], 2),
                         round(last_vel["theta.vel"], 1), speed_index)
                if shown != last_shown:
                    sys.stdout.write(
                        f"\r속도단계 {speed_index + 1}/3   "
                        f"x={shown[0]:+.2f} m/s  y={shown[1]:+.2f} m/s  θ={shown[2]:+.1f} °/s    "
                    )
                    sys.stdout.flush()
                    last_shown = shown

                time.sleep(max(1 / FPS - (time.perf_counter() - loop_start), 0))

    except KeyboardInterrupt:
        pass
    finally:
        # 터미널을 되돌린 뒤에 찍어야 줄바꿈이 제대로 됩니다.
        base.close()
        print("\n정지하고 종료했습니다.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
