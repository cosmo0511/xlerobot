# =============================================================================
# xlerobot_host.py — 🦾 라즈베리파이에서 상시 실행하는 host 프로세스
# =============================================================================
#
#   PYTHONPATH=src python -m xlerobot_devices.xlerobot_host \
#       --robot.id=home_xle \
#       --robot.port1=/dev/ttyACM0 \
#       --robot.port2=/dev/ttyACM1
#
# 하는 일은 딱 두 가지입니다.
#
#   1. 노트북(client)이 ZMQ(5555)로 보내는 action JSON 을 받아 모터에 씁니다.
#   2. 팔 관절 + 바퀴 속도 + 카메라 3장을 ZMQ(5556)로 계속 내보냅니다.
#
# 전송 형식은 멀티파트입니다: [JSON 헤더] + [카메라별 JPEG 원본].
# 업스트림 XLeRobot 은 JPEG 를 base64 로 JSON 안에 넣는데, 그러면 용량이 33%
# 늘어납니다. 카메라가 3대라 그 차이가 WiFi 에서 체감됩니다.
#
# ※ 왜 host 가 카메라를 가지고 있나: 카메라는 USB 로 Pi 에 꽂혀 있습니다.
#   노트북에서 열 수 없으니 Pi 가 읽어서 보내주는 수밖에 없습니다.
# =============================================================================

# ⚠️ 이 파일에는 `from __future__ import annotations` 를 넣지 마세요.
# draccus 가 main(cfg: XLerobotServerConfig) 의 타입 annotation 을 읽어서
# 그 dataclass 의 필드를 CLI 인자로 펼칩니다. future import 를 켜면 annotation 이
# 문자열("XLerobotServerConfig")이 되어버려서 draccus 가 dataclasses.fields() 를
# 문자열에 대고 호출합니다:
#   TypeError: must be called with a dataclass type or instance
# lerobot 의 lekiwi_host.py 도 같은 이유로 future import 를 쓰지 않습니다.

import json
import logging
import time
from dataclasses import dataclass, field

import cv2
import draccus
import zmq

from .config_xlerobot import XLerobotConfig, XLerobotHostConfig
from .xlerobot import XLerobot

logger = logging.getLogger(__name__)


@dataclass
class XLerobotServerConfig:
    """host 스크립트의 전체 설정. --robot.* / --host.* 로 넘깁니다."""

    robot: XLerobotConfig = field(default_factory=XLerobotConfig)
    host: XLerobotHostConfig = field(default_factory=XLerobotHostConfig)


class XLerobotHost:
    def __init__(self, config: XLerobotHostConfig):
        self.zmq_context = zmq.Context()

        # 명령 소켓: 최신 한 개만 들고 있으면 됩니다. 밀린 명령을 따라가면
        # 팔이 과거 자세를 쫓아가서 느려집니다.
        self.zmq_cmd_socket = self.zmq_context.socket(zmq.PULL)
        self.zmq_cmd_socket.setsockopt(zmq.CONFLATE, 1)
        self.zmq_cmd_socket.bind(f"tcp://*:{config.port_zmq_cmd}")

        # 관측 소켓: CONFLATE 는 멀티파트를 지원하지 않습니다. 대신 큐를 2로 줄여서
        # 네트워크가 막히면 오래된 프레임을 버립니다.
        self.zmq_observation_socket = self.zmq_context.socket(zmq.PUSH)
        self.zmq_observation_socket.setsockopt(zmq.SNDHWM, 2)
        self.zmq_observation_socket.bind(f"tcp://*:{config.port_zmq_observations}")

        self.connection_time_s = config.connection_time_s
        self.watchdog_timeout_ms = config.watchdog_timeout_ms
        self.max_loop_freq_hz = config.max_loop_freq_hz
        self.jpeg_quality = config.jpeg_quality

    def disconnect(self) -> None:
        self.zmq_observation_socket.close()
        self.zmq_cmd_socket.close()
        self.zmq_context.term()


@draccus.wrap()
def main(cfg: XLerobotServerConfig) -> None:
    logging.basicConfig(level=logging.INFO)

    logger.info("Configuring XLerobot")
    robot = XLerobot(cfg.robot)

    logger.info("Connecting XLerobot")
    robot.connect()

    logger.info("Starting host on cmd:%d obs:%d", cfg.host.port_zmq_cmd, cfg.host.port_zmq_observations)
    host = XLerobotHost(cfg.host)

    last_cmd_time = time.time()
    watchdog_active = False
    logger.info("Waiting for commands...")

    try:
        start = time.perf_counter()
        duration = 0.0
        while duration < host.connection_time_s:
            loop_start = time.time()

            try:
                msg = host.zmq_cmd_socket.recv_string(zmq.NOBLOCK)
                robot.send_action(dict(json.loads(msg)))
                last_cmd_time = time.time()
                watchdog_active = False
            except zmq.Again:
                pass
            except Exception as e:
                logger.error("Message fetching failed: %s", e)

            # 명령이 끊기면 **바퀴만** 세웁니다. 팔은 마지막 자세를 유지해야
            # 들고 있던 물건을 놓지 않습니다.
            if (time.time() - last_cmd_time > host.watchdog_timeout_ms / 1000) and not watchdog_active:
                logger.warning(
                    "No command for >%d ms. Stopping the base.", host.watchdog_timeout_ms
                )
                watchdog_active = True
                robot.stop_base()

            observation = robot.get_observation()

            cam_keys = list(robot.cameras.keys())
            jpeg_frames = []
            for cam_key in cam_keys:
                ret, jpeg = cv2.imencode(
                    ".jpg", observation.pop(cam_key), [int(cv2.IMWRITE_JPEG_QUALITY), host.jpeg_quality]
                )
                jpeg_frames.append(jpeg.tobytes() if ret else b"")

            header = {"_cams": cam_keys, **{k: float(v) for k, v in observation.items()}}

            try:
                host.zmq_observation_socket.send_multipart(
                    [json.dumps(header).encode()] + jpeg_frames, flags=zmq.NOBLOCK
                )
            except zmq.Again:
                logger.debug("Dropping observation, no client connected")

            # CPU 를 다 태우지 않도록 남은 시간만큼 잡니다.
            time.sleep(max(1 / host.max_loop_freq_hz - (time.time() - loop_start), 0))
            duration = time.perf_counter() - start

        logger.info("connection_time_s reached, shutting down.")

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Exiting...")
    finally:
        logger.info("Shutting down XLerobot host.")
        robot.disconnect()
        host.disconnect()


if __name__ == "__main__":
    main()
