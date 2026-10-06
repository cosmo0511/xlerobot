# =============================================================================
# xlerobot_client.py — 💻 노트북에서 host 를 "로봇처럼" 보이게 하는 프록시
# =============================================================================
# lerobot-teleoperate / lerobot-record 입장에서는 이게 그냥 로봇입니다.
# 실제 모터와 카메라는 라즈베리파이에 있고, 이 클래스는 ZMQ 로 왕복만 합니다.
#
#   get_observation()  <- Pi 가 보내는 관절값 + JPEG 3장 (디코드해서 ndarray)
#   send_action()      -> Pi 로 action JSON
#
# ⚠️ cameras / use_head 설정이 host 와 어긋나면 안 됩니다.
#   client 의 cameras 는 "데이터셋 feature 모양 선언"이고,
#   host 의 cameras 는 "실제로 열 USB 장치"입니다. 이름과 해상도를 맞추세요.
# =============================================================================

from __future__ import annotations

import json
import logging
from functools import cached_property
from typing import Any

import cv2
import numpy as np
import zmq

from lerobot.robots.robot import Robot
from lerobot.utils.constants import ACTION, OBS_STATE
from lerobot.utils.errors import DeviceNotConnectedError

from .config_xlerobot import ARM_JOINTS, XLerobotClientConfig

logger = logging.getLogger(__name__)



class XLerobotClient(Robot):
    config_class = XLerobotClientConfig
    name = "xlerobot_client"

    def __init__(self, config: XLerobotClientConfig):
        super().__init__(config)
        self.config = config
        self.id = config.id
        self.robot_type = config.type

        self.remote_ip = config.remote_ip
        self.port_zmq_cmd = config.port_zmq_cmd
        self.port_zmq_observations = config.port_zmq_observations
        self.teleop_keys = config.teleop_keys
        self.polling_timeout_ms = config.polling_timeout_ms
        self.connect_timeout_s = config.connect_timeout_s

        self.zmq_context: zmq.Context | None = None
        self.zmq_cmd_socket: zmq.Socket | None = None
        self.zmq_observation_socket: zmq.Socket | None = None

        # 새 프레임이 안 오면 마지막 것을 다시 내줍니다. 30Hz 루프가 WiFi 한 번
        # 끊겼다고 멈추면 안 되니까요.
        self.last_frames: dict[str, np.ndarray] = {}
        self.last_remote_state: dict[str, Any] = {}

        self.speed_levels = [
            {"xy": 0.1, "theta": 30},
            {"xy": 0.2, "theta": 60},
            {"xy": 0.3, "theta": 90},
        ]
        self.speed_index = 0

        self._is_connected = False

    # -------------------------------------------------------------- features
    @cached_property
    def _state_ft(self) -> dict[str, type]:
        keys = [f"left_arm_{j}.pos" for j in ARM_JOINTS]
        keys += [f"right_arm_{j}.pos" for j in ARM_JOINTS]
        if self.config.use_head:
            keys += ["head_motor_1.pos", "head_motor_2.pos"]
        keys += ["x.vel", "y.vel", "theta.vel"]
        return dict.fromkeys(keys, float)

    @cached_property
    def _state_order(self) -> tuple[str, ...]:
        return tuple(self._state_ft.keys())

    @cached_property
    def _cameras_ft(self) -> dict[str, tuple[int, int, int]]:
        return {name: (cfg.height, cfg.width, 3) for name, cfg in self.config.cameras.items()}

    @cached_property
    def observation_features(self) -> dict[str, type | tuple]:
        return {**self._state_ft, **self._cameras_ft}

    @cached_property
    def action_features(self) -> dict[str, type]:
        return self._state_ft

    # ------------------------------------------------------------- lifecycle
    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def is_calibrated(self) -> bool:
        # 캘리브레이션은 Pi(host)에 있습니다. client 는 할 게 없습니다.
        return True

    def connect(self, calibrate: bool = True) -> None:
        if self._is_connected:
            raise DeviceNotConnectedError(f"{self} already connected")

        self.zmq_context = zmq.Context()

        self.zmq_cmd_socket = self.zmq_context.socket(zmq.PUSH)
        self.zmq_cmd_socket.connect(f"tcp://{self.remote_ip}:{self.port_zmq_cmd}")
        self.zmq_cmd_socket.setsockopt(zmq.CONFLATE, 1)

        self.zmq_observation_socket = self.zmq_context.socket(zmq.PULL)
        self.zmq_observation_socket.connect(f"tcp://{self.remote_ip}:{self.port_zmq_observations}")
        self.zmq_observation_socket.setsockopt(zmq.RCVHWM, 2)

        poller = zmq.Poller()
        poller.register(self.zmq_observation_socket, zmq.POLLIN)
        socks = dict(poller.poll(self.connect_timeout_s * 1000))
        if self.zmq_observation_socket not in socks:
            raise DeviceNotConnectedError(
                f"{self.connect_timeout_s}초 안에 host({self.remote_ip})에서 관측이 오지 않았습니다. "
                "Pi 에서 xlerobot_host 가 떠 있는지, IP/포트와 방화벽을 확인하세요."
            )

        self._is_connected = True
        logger.info(f"{self} connected to {self.remote_ip}")

    def calibrate(self) -> None:
        pass

    def configure(self) -> None:
        pass

    # ------------------------------------------------------------------ 수신
    def _poll_and_get_latest_message(self) -> list[bytes] | None:
        """소켓에 쌓인 걸 다 비우고 **가장 최신** 메시지만 돌려줍니다."""
        if self.zmq_observation_socket is None:
            raise DeviceNotConnectedError(f"{self} observation socket is not initialized")

        poller = zmq.Poller()
        poller.register(self.zmq_observation_socket, zmq.POLLIN)
        try:
            socks = dict(poller.poll(self.polling_timeout_ms))
        except zmq.ZMQError as e:
            logger.error(f"ZMQ polling error: {e}")
            return None

        if self.zmq_observation_socket not in socks:
            return None

        last_msg = None
        while True:
            try:
                last_msg = self.zmq_observation_socket.recv_multipart(zmq.NOBLOCK)
            except zmq.Again:
                break
        return last_msg

    def _parse_observation(self, frames: list[bytes]) -> dict[str, Any] | None:
        """[JSON 헤더] + [카메라별 JPEG] -> dict"""
        try:
            header = json.loads(frames[0])
            cam_names = header.pop("_cams")
            observation: dict[str, Any] = header
            for cam_name, jpeg in zip(cam_names, frames[1:], strict=True):
                observation[cam_name] = jpeg
            return observation
        except (json.JSONDecodeError, KeyError, ValueError, IndexError) as e:
            logger.error(f"Error decoding observation: {e}")
            return None

    @staticmethod
    def _decode_image(jpeg: bytes) -> np.ndarray | None:
        if not jpeg:
            return None
        frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            logger.warning("cv2.imdecode returned None")
        return frame

    def _remote_state_from_obs(
        self, observation: dict[str, Any]
    ) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        flat_state = {key: observation.get(key, 0.0) for key in self._state_order}
        state_vec = np.array([flat_state[key] for key in self._state_order], dtype=np.float32)
        obs_dict: dict[str, Any] = {**flat_state, OBS_STATE: state_vec}

        frames: dict[str, np.ndarray] = {}
        for cam_name in self._cameras_ft:
            jpeg = observation.get(cam_name)
            if jpeg is None:
                continue
            frame = self._decode_image(jpeg)
            if frame is not None:
                frames[cam_name] = frame

        return frames, obs_dict

    def _get_data(self) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        latest = self._poll_and_get_latest_message()
        if latest is None:
            return self.last_frames, self.last_remote_state

        observation = self._parse_observation(latest)
        if observation is None:
            return self.last_frames, self.last_remote_state

        try:
            new_frames, new_state = self._remote_state_from_obs(observation)
        except Exception as e:
            logger.error(f"Error processing observation, serving last one: {e}")
            return self.last_frames, self.last_remote_state

        self.last_frames = new_frames
        self.last_remote_state = new_state
        return new_frames, new_state

    def get_observation(self) -> dict[str, Any]:
        if not self._is_connected:
            raise DeviceNotConnectedError(f"{self} is not connected.")

        frames, obs_dict = self._get_data()
        for cam_name, (h, w, c) in self._cameras_ft.items():
            frame = frames.get(cam_name)
            if frame is None:
                # 첫 프레임이 아직 안 왔을 때. 검은 화면이라도 모양은 맞춰줘야
                # 데이터셋 writer 가 터지지 않습니다.
                logger.warning(f"No frame for camera '{cam_name}', serving black image")
                frame = np.zeros((h, w, c), dtype=np.uint8)
            obs_dict[cam_name] = frame
        return obs_dict

    # ------------------------------------------------------------------ 송신
    def _from_keyboard_to_base_action(self, pressed_keys) -> dict[str, float]:
        """키보드 눌린 키 -> 베이스 속도 명령.

        host 쪽 XLerobot 에도 같은 함수가 있지만, 속도 단계를 누르는 곳이
        노트북이므로 단계 상태(speed_index)도 노트북이 들고 있어야 합니다.
        """
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

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        if not self._is_connected:
            raise DeviceNotConnectedError(f"{self} is not connected.")
        if self.zmq_cmd_socket is None:
            raise DeviceNotConnectedError(f"{self} command socket is not initialized")

        # 데이터셋에서 리플레이하면 torch 텐서가 올 수 있습니다. json 은 못 먹습니다.
        action = {key: float(value) for key, value in action.items()}
        self.zmq_cmd_socket.send_string(json.dumps(action))

        actions = np.array([action.get(k, 0.0) for k in self._state_order], dtype=np.float32)
        action_sent: dict[str, Any] = {k: actions[i] for i, k in enumerate(self._state_order)}
        action_sent[ACTION] = actions
        return action_sent

    def disconnect(self) -> None:
        if not self._is_connected:
            raise DeviceNotConnectedError(f"{self} is not connected.")
        if self.zmq_observation_socket is not None:
            self.zmq_observation_socket.close()
        if self.zmq_cmd_socket is not None:
            self.zmq_cmd_socket.close()
        if self.zmq_context is not None:
            self.zmq_context.term()
        self._is_connected = False
