# =============================================================================
# config_xlerobot.py — XLeRobot (양팔 + 르키위 베이스) 설정
# =============================================================================
# 우리 배선:
#
#   port1 (왼팔 버스)        ID 1~6  왼팔 SO-101
#   port2 (오른팔+베이스 버스) ID 1~6  오른팔 SO-101
#                            ID 7,8,9 르키위 옴니휠 3개
#
# 업스트림 XLeRobot 은 port1 에 머리 모터(ID 7,8)가 더 붙어 있다고 가정합니다.
# 우리는 머리가 없으므로 기본값이 use_head=False 입니다. 나중에 머리를 달면
# --robot.use_head=true 만 켜면 됩니다.
# =============================================================================

from dataclasses import dataclass, field

from lerobot.cameras import CameraConfig
from lerobot.cameras.opencv import OpenCVCameraConfig
from lerobot.robots.config import RobotConfig

# SO-101 관절 순서. 데이터셋 컬럼 순서가 여기서 정해집니다.
ARM_JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)


def xlerobot_cameras_config() -> dict[str, CameraConfig]:
    """카메라 3개.

    이름이 그대로 데이터셋 키(observation.images.<이름>)가 됩니다.
    수집 때와 추론 때가 **글자까지 같아야** 하므로 함부로 바꾸지 마세요.
    """
    return {
        "top": OpenCVCameraConfig(index_or_path="/dev/video0", fps=30, width=640, height=480),
        "left_wrist": OpenCVCameraConfig(index_or_path="/dev/video2", fps=30, width=640, height=480),
        "right_wrist": OpenCVCameraConfig(index_or_path="/dev/video4", fps=30, width=640, height=480),
    }


def xlerobot_teleop_keys() -> dict[str, str]:
    """베이스 주행 키.

    WASD 를 안 쓰는 이유: lerobot-record 가 ←/→/ESC 를 쓰고, 손은 리더암 두 개를
    잡고 있습니다. 오른손잡이 기준으로 한 손만 떼서 누르기 쉬운 IJKL 로 뒀습니다.
    """
    return {
        # 이동
        "forward": "i",
        "backward": "k",
        "left": "j",
        "right": "l",
        "rotate_left": "u",
        "rotate_right": "o",
        # 속도 단계
        "speed_up": "n",
        "speed_down": "m",
        # 종료
        "quit": "b",
    }


@RobotConfig.register_subclass("xlerobot")
@dataclass
class XLerobotConfig(RobotConfig):
    """🦾 라즈베리파이(host)에서 실제 하드웨어를 여는 쪽 설정."""

    port1: str = "/dev/ttyACM0"  # 왼팔 버스
    port2: str = "/dev/ttyACM1"  # 오른팔 + 르키위 베이스 버스

    disable_torque_on_disconnect: bool = True

    # 머리 모터(port1 의 ID 7,8). 우리 구성엔 없습니다.
    use_head: bool = False

    # 한 스텝에 관절이 움직일 수 있는 최대량. None 이면 제한 없음.
    # 리더암을 확 휘두르면 팔로워가 그대로 따라가므로, 처음엔 숫자를 넣고 시작하세요.
    max_relative_target: float | dict[str, float] | None = None

    cameras: dict[str, CameraConfig] = field(default_factory=xlerobot_cameras_config)

    # ⚠️ 리더암(SOLeaderConfig)의 기본값이 use_degrees=True 입니다.
    # 팔로워와 리더의 정규화 방식이 다르면 텔레옵 매핑이 어긋납니다. 양쪽을 맞추세요.
    use_degrees: bool = True

    teleop_keys: dict[str, str] = field(default_factory=xlerobot_teleop_keys)

    # Feetech 버스가 간헐적으로 깨진 패킷을 돌려줄 때 재시도할 횟수.
    num_read_retries: int = 2


@dataclass
class XLerobotHostConfig:
    """host 프로세스(라즈베리파이)의 네트워크/루프 설정."""

    port_zmq_cmd: int = 5555
    port_zmq_observations: int = 5556

    # host 가 살아 있을 시간(초). 이 시간이 지나면 **스스로 종료합니다.**
    # 업스트림 lekiwi 는 기본이 30초라 "왜 자꾸 죽지?" 의 범인이 됩니다.
    # 하루치 수집이면 넉넉하게 주세요.
    connection_time_s: int = 36000

    # 이 시간 동안 명령이 안 오면 바퀴를 멈춥니다. 팔은 그대로 유지.
    watchdog_timeout_ms: int = 500

    # 팔이 떨리면 이 값을 낮추고 Pi 에서 top 으로 CPU 를 보세요.
    max_loop_freq_hz: int = 30

    # 전송할 JPEG 품질. 카메라 3개를 WiFi 로 보내므로 낮출 여지가 있습니다.
    jpeg_quality: int = 90


@RobotConfig.register_subclass("xlerobot_client")
@dataclass
class XLerobotClientConfig(RobotConfig):
    """💻 노트북(client)에서 host 에 붙는 쪽 설정.

    cameras / use_head 는 **host 와 똑같이** 맞춰야 합니다. client 는 이 값으로
    데이터셋의 feature 모양을 정하고, host 는 이 값으로 실제 카메라를 엽니다.
    어긋나면 녹화된 이미지 키가 틀어집니다.
    """

    remote_ip: str = "192.168.0.101"
    port_zmq_cmd: int = 5555
    port_zmq_observations: int = 5556

    use_head: bool = False

    teleop_keys: dict[str, str] = field(default_factory=xlerobot_teleop_keys)

    cameras: dict[str, CameraConfig] = field(default_factory=xlerobot_cameras_config)

    polling_timeout_ms: int = 15
    connect_timeout_s: int = 5
