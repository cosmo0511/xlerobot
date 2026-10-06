# =============================================================================
# xlerobot_devices — lerobot 플러그인 패키지
# =============================================================================
# lerobot 을 포크하지 않고 우리 로봇/텔레옵을 등록합니다. CLI 에 이렇게 넘깁니다.
#
#   --robot.discover_packages_path=xlerobot_devices
#   --teleop.discover_packages_path=xlerobot_devices
#
# lerobot 의 parser 가 이 인자를 보면 패키지를 import 하고, 그 과정에서 아래
# @RobotConfig.register_subclass / @TeleoperatorConfig.register_subclass 가
# 실행되어 --robot.type=xlerobot_client 같은 이름을 쓸 수 있게 됩니다.
#
# 그리고 lerobot 은 config 클래스 이름에서 "Config" 를 뗀 클래스를 이 패키지
# __init__ 에서 찾습니다 (XLerobotClientConfig -> XLerobotClient).
# 그래서 아래 export 가 **필수**입니다.
#
# PYTHONPATH 에 이 레포의 src/ 가 들어 있어야 합니다. scripts/*.sh 가 해줍니다.
# =============================================================================

from .bi_leader_base import BiLeaderBase
from .config_bi_leader_base import BiLeaderBaseConfig
from .config_xlerobot import (
    ARM_JOINTS,
    XLerobotClientConfig,
    XLerobotConfig,
    XLerobotHostConfig,
)
from .xlerobot_client import XLerobotClient

__all__ = [
    "ARM_JOINTS",
    "BiLeaderBase",
    "BiLeaderBaseConfig",
    "XLerobotClient",
    "XLerobotClientConfig",
    "XLerobotConfig",
    "XLerobotHostConfig",
]


def __getattr__(name: str):
    """XLerobot(host 쪽 실물 로봇)은 지연 import 합니다.

    노트북에는 feetech 드라이버가 없을 수 있습니다. 그런데 client 를 쓰려면
    이 패키지를 import 해야 하므로, 상단에서 XLerobot 을 당겨오면 노트북에서
    import 가 깨집니다.
    """
    if name == "XLerobot":
        from .xlerobot import XLerobot

        return XLerobot
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
