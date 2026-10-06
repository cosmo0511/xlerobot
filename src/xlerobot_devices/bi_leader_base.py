# =============================================================================
# bi_leader_base.py — 리더암 2개 + 키보드를 텔레옵 장치 하나로 묶습니다
# =============================================================================
# 내보내는 action 키가 XLerobotClient.action_features 와 **정확히** 같습니다.
#
#   left_arm_shoulder_pan.pos  ... left_arm_gripper.pos    (왼쪽 리더암)
#   right_arm_shoulder_pan.pos ... right_arm_gripper.pos   (오른쪽 리더암)
#   x.vel / y.vel / theta.vel                              (키보드)
#
# bi_so_leader 가 내보내는 키는 `left_shoulder_pan.pos` 입니다. 로봇이 기다리는
# 건 `left_arm_shoulder_pan.pos` 라서 중간에 이름을 바꿔줘야 합니다.
# 이 한 글자(arm_) 때문에 팔이 안 움직이는 게 제일 흔한 사고입니다.
# =============================================================================

from __future__ import annotations

import logging
from functools import cached_property
from typing import Any

from lerobot.teleoperators.bi_so_leader import BiSOLeader, BiSOLeaderConfig
from lerobot.teleoperators.keyboard import KeyboardTeleop, KeyboardTeleopConfig
from lerobot.teleoperators.teleoperator import Teleoperator

from .config_bi_leader_base import BiLeaderBaseConfig
from .config_xlerobot import ARM_JOINTS

logger = logging.getLogger(__name__)


class BiLeaderBase(Teleoperator):
    config_class = BiLeaderBaseConfig
    name = "bi_leader_base"

    def __init__(self, config: BiLeaderBaseConfig):
        super().__init__(config)
        self.config = config
        self.teleop_keys = config.teleop_keys

        # 리더암 두 개는 lerobot 의 bi_so_leader 를 그대로 씁니다.
        # id 가 같으면 캘리브레이션 파일도 그대로 재사용됩니다
        # (teleoperators/so_leader/<id>_left.json, <id>_right.json).
        self.arms = BiSOLeader(
            BiSOLeaderConfig(
                id=config.id,
                calibration_dir=config.calibration_dir,
                left_arm_config=config.left_arm_config,
                right_arm_config=config.right_arm_config,
            )
        )

        self.keyboard = KeyboardTeleop(KeyboardTeleopConfig()) if config.use_keyboard else None

        # 베이스 속도 단계. 눌리는 키가 노트북에 있으니 단계도 여기서 셉니다.
        self.speed_levels = [
            {"xy": 0.1, "theta": 30},  # 느리게
            {"xy": 0.2, "theta": 60},  # 보통
            {"xy": 0.3, "theta": 90},  # 빠르게
        ]
        self.speed_index = 0

    # -------------------------------------------------------------- features
    @cached_property
    def action_features(self) -> dict[str, type]:
        keys = [f"{side}_arm_{joint}.pos" for side in ("left", "right") for joint in ARM_JOINTS]
        if self.config.use_head:
            keys += ["head_motor_1.pos", "head_motor_2.pos"]
        keys += ["x.vel", "y.vel", "theta.vel"]
        return dict.fromkeys(keys, float)

    @cached_property
    def feedback_features(self) -> dict:
        # 힘 피드백은 쓰지 않습니다.
        return {}

    # ------------------------------------------------------------- lifecycle
    @property
    def is_connected(self) -> bool:
        if self.keyboard is not None and not self.keyboard.is_connected:
            return False
        return self.arms.is_connected

    @property
    def is_calibrated(self) -> bool:
        return self.arms.is_calibrated

    def connect(self, calibrate: bool = True) -> None:
        self.arms.connect(calibrate)
        if self.keyboard is not None:
            self.keyboard.connect()
            logger.info(
                "베이스 주행 키: 이동 %s/%s/%s/%s, 회전 %s/%s, 속도 %s/%s",
                self.teleop_keys["forward"],
                self.teleop_keys["backward"],
                self.teleop_keys["left"],
                self.teleop_keys["right"],
                self.teleop_keys["rotate_left"],
                self.teleop_keys["rotate_right"],
                self.teleop_keys["speed_up"],
                self.teleop_keys["speed_down"],
            )

    def calibrate(self) -> None:
        self.arms.calibrate()

    def configure(self) -> None:
        self.arms.configure()
        if self.keyboard is not None:
            self.keyboard.configure()

    def setup_motors(self) -> None:
        self.arms.setup_motors()

    # ------------------------------------------------------------------ 동작
    def _base_action(self) -> dict[str, float]:
        if self.keyboard is None:
            return {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}

        # KeyboardTeleop.get_action() 은 "지금 눌려 있는 키"가 키인 dict 를 줍니다.
        pressed = self.keyboard.get_action()

        if self.teleop_keys["speed_up"] in pressed:
            self.speed_index = min(self.speed_index + 1, 2)
        if self.teleop_keys["speed_down"] in pressed:
            self.speed_index = max(self.speed_index - 1, 0)
        speed = self.speed_levels[self.speed_index]

        x_cmd = y_cmd = theta_cmd = 0.0
        if self.teleop_keys["forward"] in pressed:
            x_cmd += speed["xy"]
        if self.teleop_keys["backward"] in pressed:
            x_cmd -= speed["xy"]
        if self.teleop_keys["left"] in pressed:
            y_cmd += speed["xy"]
        if self.teleop_keys["right"] in pressed:
            y_cmd -= speed["xy"]
        if self.teleop_keys["rotate_left"] in pressed:
            theta_cmd += speed["theta"]
        if self.teleop_keys["rotate_right"] in pressed:
            theta_cmd -= speed["theta"]

        return {"x.vel": x_cmd, "y.vel": y_cmd, "theta.vel": theta_cmd}

    def get_action(self) -> dict[str, Any]:
        raw = self.arms.get_action()

        # left_shoulder_pan.pos -> left_arm_shoulder_pan.pos
        action: dict[str, Any] = {}
        for key, value in raw.items():
            if key.startswith("left_"):
                action[f"left_arm_{key[len('left_'):]}"] = value
            elif key.startswith("right_"):
                action[f"right_arm_{key[len('right_'):]}"] = value
            else:
                action[key] = value

        if self.config.use_head:
            # 리더암은 머리를 조종하지 않습니다. 컬럼 수만 맞춰줍니다.
            action.setdefault("head_motor_1.pos", 0.0)
            action.setdefault("head_motor_2.pos", 0.0)

        action.update(self._base_action())
        return action

    def send_feedback(self, feedback: dict[str, Any]) -> None:
        pass

    def disconnect(self) -> None:
        self.arms.disconnect()
        if self.keyboard is not None:
            self.keyboard.disconnect()
