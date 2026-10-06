# =============================================================================
# config_bi_leader_base.py — 리더암 2개 + 키보드 베이스 = 텔레옵 장치 하나
# =============================================================================
# 왜 이런 게 필요한가:
#
# lerobot-teleoperate / lerobot-record 는 **텔레옵 장치를 하나만** 받습니다.
# 리더암과 키보드를 동시에 받는 경로(multi_teleop)가 record.py 에 있긴 한데
# `robot.name == "lekiwi_client"` 로 하드코딩돼 있어서 우리는 못 씁니다.
#
# 그래서 "리더암 2개 + 키보드"를 **하나의 장치처럼** 포장했습니다. 이러면
# lerobot 쪽 코드를 한 줄도 안 고치고 CLI 를 그대로 쓸 수 있습니다.
# =============================================================================

from dataclasses import dataclass, field

from lerobot.teleoperators.config import TeleoperatorConfig
from lerobot.teleoperators.so_leader import SOLeaderConfig

from .config_xlerobot import xlerobot_teleop_keys


@TeleoperatorConfig.register_subclass("bi_leader_base")
@dataclass
class BiLeaderBaseConfig(TeleoperatorConfig):
    """노트북에 꽂힌 리더암 2개 + 키보드."""

    # 리더암 포트. use_degrees 는 팔로워(XLerobotConfig.use_degrees)와 같아야 합니다.
    left_arm_config: SOLeaderConfig = field(default_factory=lambda: SOLeaderConfig(port="/dev/ttyACM0"))
    right_arm_config: SOLeaderConfig = field(default_factory=lambda: SOLeaderConfig(port="/dev/ttyACM1"))

    # 베이스 주행 키. 로봇(client)의 teleop_keys 와 같게 두는 게 덜 헷갈립니다.
    teleop_keys: dict[str, str] = field(default_factory=xlerobot_teleop_keys)

    # 머리 모터를 달았다면 True. 리더암이 머리를 조종하진 않으므로 0.0 을 채웁니다
    # (데이터셋 action 컬럼 수를 로봇과 맞추기 위해서).
    use_head: bool = False

    # 키보드를 안 쓰고 팔만 조종할 때. 베이스 명령은 항상 0 이 나갑니다.
    # pynput 이 없는 환경(SSH 등)에서 유용합니다.
    use_keyboard: bool = True
