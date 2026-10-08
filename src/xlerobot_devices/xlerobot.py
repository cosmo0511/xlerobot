# =============================================================================
# xlerobot.py — 🦾 라즈베리파이(host)에서 하드웨어를 직접 여는 로봇 클래스
# =============================================================================
# 업스트림 XLeRobot(Vector-Wangel/XLeRobot) 의 XLerobot 을 우리 배선에 맞게
# 다듬은 것입니다. 바뀐 점:
#
#   1. 머리 모터(port1 의 ID 7,8)를 선택사항으로 돌렸습니다 (use_head, 기본 False).
#      우리 왼팔 버스에는 1~6 밖에 없어서 원본 그대로면 sync_read 가 터집니다.
#   2. sync_read 에 num_retry 를 붙였습니다. 모터 9개가 한 버스에 있으면
#      Feetech 가 깨진 패킷을 돌려주는 일이 잦습니다.
#   3. connect() 에서 input() 으로 물어보지 않습니다. host 는 백그라운드로 띄우는
#      프로세스라 stdin 이 없을 수 있습니다. 캘리브레이션 파일이 있으면 그냥 씁니다.
#
# 이 클래스는 **라즈베리파이에서만** 인스턴스화됩니다. 노트북은 XLerobotClient 를 씁니다.
# =============================================================================

from __future__ import annotations

import logging
import sys
import time
from functools import cached_property
from itertools import chain
from typing import Any

import numpy as np

from lerobot.cameras.utils import make_cameras_from_configs
from lerobot.motors import Motor, MotorCalibration, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus, OperatingMode
from lerobot.robots.robot import Robot
from lerobot.robots.utils import ensure_safe_goal_position
from lerobot.utils.errors import DeviceAlreadyConnectedError, DeviceNotConnectedError

from .config_xlerobot import XLerobotConfig

logger = logging.getLogger(__name__)

# 베이스 기구학 상수. 르키위 기본값.
WHEEL_RADIUS = 0.05  # m
BASE_RADIUS = 0.125  # m 중심에서 바퀴까지
MAX_WHEEL_RAW = 3000


class XLerobot(Robot):
    """양팔 SO-101 + 르키위 3옴니휠 베이스. 버스 2개.

    bus1 = 왼팔 (+ 선택적으로 머리)
    bus2 = 오른팔 + 베이스 바퀴 3개
    """

    config_class = XLerobotConfig
    name = "xlerobot"

    def __init__(self, config: XLerobotConfig):
        super().__init__(config)
        self.config = config
        self.teleop_keys = config.teleop_keys

        self.speed_levels = [
            {"xy": 0.1, "theta": 30},  # 느리게
            {"xy": 0.2, "theta": 60},  # 보통
            {"xy": 0.3, "theta": 90},  # 빠르게
        ]
        self.speed_index = 0

        norm = MotorNormMode.DEGREES if config.use_degrees else MotorNormMode.RANGE_M100_100

        bus1_motors: dict[str, Motor] = {
            "left_arm_shoulder_pan": Motor(1, "sts3215", norm),
            "left_arm_shoulder_lift": Motor(2, "sts3215", norm),
            "left_arm_elbow_flex": Motor(3, "sts3215", norm),
            "left_arm_wrist_flex": Motor(4, "sts3215", norm),
            "left_arm_wrist_roll": Motor(5, "sts3215", norm),
            "left_arm_gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100),
        }
        if config.use_head:
            bus1_motors["head_motor_1"] = Motor(7, "sts3215", norm)
            bus1_motors["head_motor_2"] = Motor(8, "sts3215", norm)

        bus2_motors: dict[str, Motor] = {
            "right_arm_shoulder_pan": Motor(1, "sts3215", norm),
            "right_arm_shoulder_lift": Motor(2, "sts3215", norm),
            "right_arm_elbow_flex": Motor(3, "sts3215", norm),
            "right_arm_wrist_flex": Motor(4, "sts3215", norm),
            "right_arm_wrist_roll": Motor(5, "sts3215", norm),
            "right_arm_gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100),
            # 르키위. 속도 모드로 돌기 때문에 정규화가 다릅니다.
            "base_left_wheel": Motor(7, "sts3215", MotorNormMode.RANGE_M100_100),
            "base_back_wheel": Motor(8, "sts3215", MotorNormMode.RANGE_M100_100),
            "base_right_wheel": Motor(9, "sts3215", MotorNormMode.RANGE_M100_100),
        }

        self.bus1 = FeetechMotorsBus(
            port=config.port1,
            motors=bus1_motors,
            calibration={k: v for k, v in self.calibration.items() if k in bus1_motors},
        )
        self.bus2 = FeetechMotorsBus(
            port=config.port2,
            motors=bus2_motors,
            calibration={k: v for k, v in self.calibration.items() if k in bus2_motors},
        )

        self.left_arm_motors = [m for m in bus1_motors if m.startswith("left_arm")]
        self.head_motors = [m for m in bus1_motors if m.startswith("head")]
        self.right_arm_motors = [m for m in bus2_motors if m.startswith("right_arm")]
        self.base_motors = [m for m in bus2_motors if m.startswith("base")]

        self.cameras = make_cameras_from_configs(config.cameras)

    # -------------------------------------------------------------- features
    @cached_property
    def _state_ft(self) -> dict[str, type]:
        keys = [f"{m}.pos" for m in self.left_arm_motors]
        keys += [f"{m}.pos" for m in self.right_arm_motors]
        keys += [f"{m}.pos" for m in self.head_motors]
        keys += ["x.vel", "y.vel", "theta.vel"]
        return dict.fromkeys(keys, float)

    @cached_property
    def _cameras_ft(self) -> dict[str, tuple]:
        return {
            cam: (self.config.cameras[cam].height, self.config.cameras[cam].width, 3)
            for cam in self.cameras
        }

    @cached_property
    def observation_features(self) -> dict[str, type | tuple]:
        return {**self._state_ft, **self._cameras_ft}

    @cached_property
    def action_features(self) -> dict[str, type]:
        return self._state_ft

    # ------------------------------------------------------------- lifecycle
    @property
    def is_connected(self) -> bool:
        return (
            self.bus1.is_connected
            and self.bus2.is_connected
            and all(cam.is_connected for cam in self.cameras.values())
        )

    def connect(self, calibrate: bool = True) -> None:
        if self.is_connected:
            raise DeviceAlreadyConnectedError(f"{self} already connected")

        self.bus1.connect()
        self.bus2.connect()

        # 업스트림은 여기서 input() 으로 물어봅니다. host 는 nohup/systemd 로 띄우는
        # 프로세스라 stdin 이 없을 수 있어서, 파일이 있으면 묻지 않고 복원합니다.
        # 다시 캘리브레이션하려면 `lerobot-calibrate --robot.type=xlerobot ...` 를
        # 따로 돌리세요.
        if self.calibration:
            logger.info(f"Restoring calibration from {self.calibration_fpath}")
            self.bus1.write_calibration({k: v for k, v in self.calibration.items() if k in self.bus1.motors})
            self.bus2.write_calibration({k: v for k, v in self.calibration.items() if k in self.bus2.motors})
        elif calibrate:
            # 캘리브레이션은 사람이 팔을 손으로 돌려야 하는 작업입니다. stdin 이
            # 없으면(nohup/systemd) input() 이 EOFError 로 죽어서 원인을 찾기
            # 어려우므로, 먼저 사람이 읽을 수 있는 말로 막습니다.
            if not sys.stdin.isatty():
                raise DeviceNotConnectedError(
                    f"캘리브레이션 파일이 없습니다: {self.calibration_fpath}\n"
                    "Pi 에서 터미널을 붙이고 먼저 이걸 돌리세요:  ./scripts/host.sh --calibrate"
                )
            logger.info("No calibration file found, running manual calibration...")
            self.calibrate()

        for cam in self.cameras.values():
            cam.connect()

        self.configure()
        logger.info(f"{self} connected.")

    @property
    def is_calibrated(self) -> bool:
        return self.bus1.is_calibrated and self.bus2.is_calibrated

    def calibrate(self) -> None:
        """양쪽 버스를 차례로 캘리브레이션합니다.

        바퀴는 **범위 기록을 하지 않습니다.** 무한 회전하는 관절이라 min/max 가
        의미 없어서 0~4095 를 그대로 씁니다.
        """
        logger.info(f"\nRunning calibration of {self}")

        # --- bus1: 왼팔 (+ 머리) -------------------------------------------
        bus1_joints = self.left_arm_motors + self.head_motors
        self.bus1.disable_torque()
        for name in bus1_joints:
            self.bus1.write("Operating_Mode", name, OperatingMode.POSITION.value)

        input("왼팔(+머리)을 가동 범위의 **중간** 자세로 두고 ENTER....")
        homing1 = self.bus1.set_half_turn_homings(bus1_joints)

        print("왼팔(+머리) 관절을 하나씩 끝에서 끝까지 움직이세요. 끝나면 ENTER....")
        mins1, maxes1 = self.bus1.record_ranges_of_motion(bus1_joints)

        calib1 = {
            name: MotorCalibration(
                id=self.bus1.motors[name].id,
                drive_mode=0,
                homing_offset=homing1[name],
                range_min=mins1[name],
                range_max=maxes1[name],
            )
            for name in bus1_joints
        }
        self.bus1.write_calibration(calib1)

        # --- bus2: 오른팔 + 바퀴 -------------------------------------------
        # 바퀴는 토크를 건드리지 않습니다 (속도 모드로 둬야 함).
        self.bus2.disable_torque(self.right_arm_motors)
        for name in self.right_arm_motors:
            self.bus2.write("Operating_Mode", name, OperatingMode.POSITION.value)

        input("오른팔을 가동 범위의 **중간** 자세로 두고 ENTER....")
        homing2 = self.bus2.set_half_turn_homings(self.right_arm_motors)
        homing2.update(dict.fromkeys(self.base_motors, 0))

        print("오른팔 관절을 하나씩 끝에서 끝까지 움직이세요. 바퀴는 건드리지 마세요. 끝나면 ENTER....")
        mins2, maxes2 = self.bus2.record_ranges_of_motion(self.right_arm_motors)
        for name in self.base_motors:
            mins2[name] = 0
            maxes2[name] = 4095

        calib2 = {
            name: MotorCalibration(
                id=self.bus2.motors[name].id,
                drive_mode=0,
                homing_offset=homing2[name],
                range_min=mins2[name],
                range_max=maxes2[name],
            )
            for name in self.right_arm_motors + self.base_motors
        }
        self.bus2.write_calibration(calib2)

        self.calibration = {**calib1, **calib2}
        self._save_calibration()
        print("Calibration saved to", self.calibration_fpath)

    def configure(self) -> None:
        self.bus1.disable_torque()
        self.bus1.configure_motors()
        self.bus2.disable_torque()
        self.bus2.configure_motors()

        # 팔과 머리는 위치 모드. P 를 낮춰서 떨림을 줄입니다 (기본 32 -> 16).
        for name in self.left_arm_motors + self.head_motors:
            self.bus1.write("Operating_Mode", name, OperatingMode.POSITION.value)
            self.bus1.write("P_Coefficient", name, 16)
            self.bus1.write("I_Coefficient", name, 0)
            self.bus1.write("D_Coefficient", name, 43)

        for name in self.right_arm_motors:
            self.bus2.write("Operating_Mode", name, OperatingMode.POSITION.value)
            self.bus2.write("P_Coefficient", name, 16)
            self.bus2.write("I_Coefficient", name, 0)
            self.bus2.write("D_Coefficient", name, 43)

        # 바퀴만 속도 모드.
        for name in self.base_motors:
            self.bus2.write("Operating_Mode", name, OperatingMode.VELOCITY.value)

        self.bus1.enable_torque()
        self.bus2.enable_torque()

    def setup_motors(self) -> None:
        """모터 ID 를 하나씩 굽는 절차. 조립 때 한 번만 씁니다."""
        for motor in chain(reversed(self.left_arm_motors), reversed(self.head_motors)):
            input(f"'{motor}' 모터만 컨트롤러에 연결하고 ENTER.")
            self.bus1.setup_motor(motor)
            print(f"'{motor}' -> id {self.bus1.motors[motor].id}")

        for motor in chain(reversed(self.right_arm_motors), reversed(self.base_motors)):
            input(f"'{motor}' 모터만 컨트롤러에 연결하고 ENTER.")
            self.bus2.setup_motor(motor)
            print(f"'{motor}' -> id {self.bus2.motors[motor].id}")

    # --------------------------------------------------------- base 기구학
    @staticmethod
    def _degps_to_raw(degps: float) -> int:
        speed_int = int(round(degps * 4096.0 / 360.0))
        return max(-0x8000, min(0x7FFF, speed_int))

    @staticmethod
    def _raw_to_degps(raw_speed: int) -> float:
        return raw_speed / (4096.0 / 360.0)

    @staticmethod
    def _wheel_matrix() -> np.ndarray:
        """바퀴 3개의 장착 각도(240°, 0°, 120°)에 -90° 오프셋."""
        angles = np.radians(np.array([240.0, 0.0, 120.0]) - 90.0)
        return np.array([[np.cos(a), np.sin(a), BASE_RADIUS] for a in angles])

    @staticmethod
    def _body_to_wheel_raw(x: float, y: float, theta: float) -> dict[str, int]:
        """몸체 속도 (m/s, m/s, deg/s) -> 바퀴 raw 명령 3개."""
        velocity = np.array([x, y, theta * np.pi / 180.0])
        wheel_degps = (XLerobot._wheel_matrix().dot(velocity) / WHEEL_RADIUS) * (180.0 / np.pi)

        # 한 바퀴라도 한계를 넘으면 셋 다 같은 비율로 줄입니다 (방향 유지).
        raw_floats = [abs(d) * 4096.0 / 360.0 for d in wheel_degps]
        if max(raw_floats) > MAX_WHEEL_RAW:
            wheel_degps = wheel_degps * (MAX_WHEEL_RAW / max(raw_floats))

        raw = [XLerobot._degps_to_raw(d) for d in wheel_degps]
        return {
            "base_left_wheel": raw[0],
            "base_back_wheel": raw[1],
            "base_right_wheel": raw[2],
        }

    @staticmethod
    def _wheel_raw_to_body(left: float, back: float, right: float) -> dict[str, float]:
        """바퀴 raw 피드백 -> 몸체 속도 (m/s, m/s, deg/s)."""
        wheel_degps = np.array(
            [XLerobot._raw_to_degps(left), XLerobot._raw_to_degps(back), XLerobot._raw_to_degps(right)]
        )
        wheel_linear = wheel_degps * (np.pi / 180.0) * WHEEL_RADIUS
        x, y, theta_rad = np.linalg.inv(XLerobot._wheel_matrix()).dot(wheel_linear)
        return {"x.vel": float(x), "y.vel": float(y), "theta.vel": float(theta_rad * 180.0 / np.pi)}

    def _from_keyboard_to_base_action(self, pressed_keys) -> dict[str, float]:
        if self.teleop_keys["speed_up"] in pressed_keys:
            self.speed_index = min(self.speed_index + 1, 2)
        if self.teleop_keys["speed_down"] in pressed_keys:
            self.speed_index = max(self.speed_index - 1, 0)
        speed = self.speed_levels[self.speed_index]

        x_cmd = y_cmd = theta_cmd = 0.0
        if self.teleop_keys["forward"] in pressed_keys:
            x_cmd += speed["xy"]
        if self.teleop_keys["backward"] in pressed_keys:
            x_cmd -= speed["xy"]
        if self.teleop_keys["left"] in pressed_keys:
            y_cmd += speed["xy"]
        if self.teleop_keys["right"] in pressed_keys:
            y_cmd -= speed["xy"]
        if self.teleop_keys["rotate_left"] in pressed_keys:
            theta_cmd += speed["theta"]
        if self.teleop_keys["rotate_right"] in pressed_keys:
            theta_cmd -= speed["theta"]

        return {"x.vel": x_cmd, "y.vel": y_cmd, "theta.vel": theta_cmd}

    # ------------------------------------------------------------- 관측/명령
    def get_observation(self) -> dict[str, Any]:
        if not self.is_connected:
            raise DeviceNotConnectedError(f"{self} is not connected.")

        retry = self.config.num_read_retries
        start = time.perf_counter()

        bus1_joints = self.left_arm_motors + self.head_motors
        bus1_pos = self.bus1.sync_read("Present_Position", bus1_joints, num_retry=retry)
        right_pos = self.bus2.sync_read("Present_Position", self.right_arm_motors, num_retry=retry)
        wheel_vel = self.bus2.sync_read("Present_Velocity", self.base_motors, num_retry=retry)

        base_vel = self._wheel_raw_to_body(
            wheel_vel["base_left_wheel"],
            wheel_vel["base_back_wheel"],
            wheel_vel["base_right_wheel"],
        )

        state = {f"{k}.pos": v for k, v in bus1_pos.items()}
        state.update({f"{k}.pos": v for k, v in right_pos.items()})
        logger.debug(f"{self} read state: {(time.perf_counter() - start) * 1e3:.1f}ms")

        return {**state, **base_vel, **self.get_camera_observation()}

    def get_camera_observation(self) -> dict[str, Any]:
        obs = {}
        for cam_key, cam in self.cameras.items():
            start = time.perf_counter()
            obs[cam_key] = cam.async_read()
            logger.debug(f"{self} read {cam_key}: {(time.perf_counter() - start) * 1e3:.1f}ms")
        return obs

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """팔은 목표 위치, 베이스는 목표 속도로 보냅니다.

        부분 명령도 받습니다. 키가 없는 관절은 건드리지 않습니다.
        (주행만 하고 싶을 때 x.vel 만 보내는 식으로 쓸 수 있습니다.)
        """
        if not self.is_connected:
            raise DeviceNotConnectedError(f"{self} is not connected.")

        left_pos = {k: v for k, v in action.items() if k.startswith("left_arm_") and k.endswith(".pos")}
        right_pos = {k: v for k, v in action.items() if k.startswith("right_arm_") and k.endswith(".pos")}
        head_pos = {k: v for k, v in action.items() if k.startswith("head_") and k.endswith(".pos")}
        base_goal_vel = {k: v for k, v in action.items() if k.endswith(".vel")}

        if self.config.max_relative_target is not None:
            retry = self.config.num_read_retries
            present = self.bus1.sync_read(
                "Present_Position", self.left_arm_motors + self.head_motors, num_retry=retry
            )
            present.update(
                self.bus2.sync_read("Present_Position", self.right_arm_motors, num_retry=retry)
            )
            goal_present = {
                key: (goal, present[key.removesuffix(".pos")])
                for key, goal in chain(left_pos.items(), right_pos.items(), head_pos.items())
            }
            safe = ensure_safe_goal_position(goal_present, self.config.max_relative_target)
            left_pos = {k: v for k, v in safe.items() if k in left_pos}
            right_pos = {k: v for k, v in safe.items() if k in right_pos}
            head_pos = {k: v for k, v in safe.items() if k in head_pos}

        bus1_raw = {k.removesuffix(".pos"): v for k, v in {**left_pos, **head_pos}.items()}
        bus2_raw = {k.removesuffix(".pos"): v for k, v in right_pos.items()}

        if bus1_raw:
            self.bus1.sync_write("Goal_Position", bus1_raw)
        if bus2_raw:
            self.bus2.sync_write("Goal_Position", bus2_raw)
        if base_goal_vel:
            self.bus2.sync_write(
                "Goal_Velocity",
                self._body_to_wheel_raw(
                    base_goal_vel.get("x.vel", 0.0),
                    base_goal_vel.get("y.vel", 0.0),
                    base_goal_vel.get("theta.vel", 0.0),
                ),
            )

        return {**left_pos, **right_pos, **head_pos, **base_goal_vel}

    def stop_base(self) -> None:
        self.bus2.sync_write("Goal_Velocity", dict.fromkeys(self.base_motors, 0), num_retry=5)
        logger.info("Base motors stopped")

    def disconnect(self) -> None:
        if not self.is_connected:
            raise DeviceNotConnectedError(f"{self} is not connected.")

        self.stop_base()
        self.bus1.disconnect(self.config.disable_torque_on_disconnect)
        self.bus2.disconnect(self.config.disable_torque_on_disconnect)
        for cam in self.cameras.values():
            cam.disconnect()
        logger.info(f"{self} disconnected.")
