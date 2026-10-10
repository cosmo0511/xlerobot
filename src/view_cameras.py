"""
view_cameras.py — 카메라 화면 확인. 녹화 전에 이걸로 먼저 보세요.

    # 💻 PC 에서 (파이에서 ./scripts/host.sh 가 떠 있어야 함) — 기본
    python src/view_cameras.py                 # CAMERA_SET (기본 3cam)
    python src/view_cameras.py 4cam

    # 카메라가 꽂힌 기기에서 직접 장치를 열기 (파이에 모니터를 꽂았을 때 등)
    python src/view_cameras.py 3cam --local

    # 창 없이 (ssh 등) 한 장씩 저장하고 끝내기 -> outputs/camera_check/
    python src/view_cameras.py 3cam --local --save

화면은 rerun 뷰어 창에 뜹니다 (녹화 때 --display_data 로 뜨는 것과 같은 뷰어).
터미널에는 카메라별 fps 가 1초마다 찍힙니다.  Ctrl+C 로 종료.
※ lerobot venv 의 OpenCV 는 화면 없는(headless) 빌드라 cv2 창은 못 띄웁니다.

■ 두 모드의 차이
---------------------------------------------------------------------------
기본(원격)은 **녹화와 똑같은 경로**로 봅니다: 파이 호스트가 JPEG 로 보낸 프레임을
bi_so_base_client 가 받습니다. 여기서 보이는 그림이 그대로 데이터셋에 들어갑니다.
그래서 "top 칸에 손목캠이 나온다" 같은 이름-장치 엇갈림을 녹화 전에 잡을 수 있습니다.

--local 은 yaml 의 장치 경로를 OpenCV 로 직접 엽니다. 어떤 /dev/video* 가
어떤 카메라인지 찾을 때 씁니다. 호스트가 같은 장치를 열고 있으면 안 열립니다.

원격 모드는 로봇에 명령을 보내지 않습니다 (바퀴·팔 안 움직임).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from camera_config import (  # noqa: E402
    CameraConfigError,
    camera_kwargs,
    flat_cameras,
    load_camera_set,
)

SAVE_DIR = PROJECT_ROOT / "outputs" / "camera_check"


# =============================================================================
# 프레임 소스
# =============================================================================
class LocalSource:
    """yaml 의 장치를 OpenCV 로 직접 엽니다."""

    def __init__(self, cams: dict):
        self.caps = {}
        for name, spec in cams.items():
            dev = spec["index_or_path"]
            cap = cv2.VideoCapture(dev, cv2.CAP_V4L2) if isinstance(dev, str) else cv2.VideoCapture(dev)
            # MJPG 로 열어야 여러 대가 USB 대역폭에 들어갑니다 (YUYV 면 보통 못 버팀).
            # 설정의 fourcc 를 그대로 따릅니다 — lerobot 이 여는 방식과 같아야 합니다.
            cap.set(cv2.CAP_PROP_FOURCC,
                    cv2.VideoWriter_fourcc(*camera_kwargs(spec)["fourcc"]))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, spec.get("width", 640))
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, spec.get("height", 480))
            cap.set(cv2.CAP_PROP_FPS, spec.get("fps", 30))
            if not cap.isOpened():
                print(f"  ✗ {name:<12} {dev} 를 못 열었습니다", file=sys.stderr)
            self.caps[name] = cap

    def read(self) -> dict[str, np.ndarray | None]:
        frames = {}
        for name, cap in self.caps.items():
            ok, frame = cap.read() if cap.isOpened() else (False, None)
            # OpenCV 는 BGR 로 줍니다. 원격(lerobot)과 맞춰 RGB 로 돌려줍니다.
            frames[name] = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if ok else None
        return frames

    def close(self) -> None:
        for cap in self.caps.values():
            cap.release()


class RemoteSource:
    """녹화와 같은 경로: 파이 호스트 -> bi_so_base_client."""

    def __init__(self, cams: dict, remote_ip: str):
        from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
        from lerobot.robots.bi_so_follower import BiSOBaseClient, BiSOBaseClientConfig

        cfg = BiSOBaseClientConfig(
            remote_ip=remote_ip,
            cameras={
                name: OpenCVCameraConfig(**camera_kwargs(spec))
                for name, spec in cams.items()
            },
        )
        self.names = list(cams)
        self.robot = BiSOBaseClient(cfg)
        print(f"파이 호스트({remote_ip})에 접속 중 ...")
        self.robot.connect()

    def read(self) -> dict[str, np.ndarray | None]:
        self.robot.get_observation()  # 새 메시지가 있으면 last_frames 를 갱신
        # get_observation() 은 못 받은 카메라를 검은 화면으로 채우므로, 실제로 받은
        # 프레임(last_frames)을 직접 봅니다. 못 받았으면 None -> "NO FRAME".
        # 이미 RGB 입니다: lerobot 카메라가 RGB 로 읽고, 호스트 imencode 와 클라이언트
        # imdecode 가 채널 순서를 그대로 보존합니다 (데이터셋에 들어가는 그림과 같음).
        return {name: self.robot.last_frames.get(name) for name in self.names}

    def close(self) -> None:
        # disconnect() 는 바퀴 정지 명령을 보냅니다 — 보고만 있었으니 해가 없습니다.
        self.robot.disconnect()


# =============================================================================
# 화면
# =============================================================================
def save(frames: dict, camera_set: str) -> list[Path]:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    paths = []
    for name, frame in frames.items():
        if frame is None:
            continue
        p = SAVE_DIR / f"{stamp}_{camera_set}_{name}.jpg"
        cv2.imwrite(str(p), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))  # imwrite 는 BGR
        paths.append(p)
    return paths


# =============================================================================
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="카메라 화면 확인")
    ap.add_argument("camera_set", nargs="?", default=os.environ.get("CAMERA_SET", "3cam"))
    ap.add_argument("--local", action="store_true", help="장치를 이 기기에서 직접 엶")
    ap.add_argument("--remote-ip", help="파이 주소 (기본: robot.yaml arms.remote_ip)")
    ap.add_argument("--save", action="store_true", help="창 없이 한 장씩 저장하고 종료")
    args = ap.parse_args(argv)

    try:
        cams = flat_cameras(load_camera_set(args.camera_set))
    except CameraConfigError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1

    if args.local:
        print(f"카메라 구성 {args.camera_set} — 이 기기에서 직접 엽니다")
        src = LocalSource(cams)
    else:
        robot_yaml = yaml.safe_load((PROJECT_ROOT / "config" / "robot.yaml").read_text(encoding="utf-8"))
        remote_ip = args.remote_ip or robot_yaml["arms"]["remote_ip"]
        logging.basicConfig(level=logging.ERROR)  # "No frame yet" 경고가 매 프레임 찍히지 않게
        try:
            src = RemoteSource(cams, remote_ip)
        except Exception as e:
            print(f"오류: 파이 호스트에 못 붙었습니다 — {e}\n"
                  "파이에서 ./scripts/host.sh 를 같은 CAMERA_SET 으로 띄웠는지 확인하세요.\n"
                  "카메라가 이 기기에 꽂혀 있으면 --local 로 보세요.", file=sys.stderr)
            return 1

    try:
        if args.save:
            # 첫 프레임 몇 장은 노출이 덜 맞아서 버립니다.
            deadline = time.time() + 3.0
            frames = src.read()
            while time.time() < deadline:
                frames = src.read()
                time.sleep(0.05)
            for name, frame in frames.items():
                print(f"  {'✓' if frame is not None else '✗'} {name}")
            for p in save(frames, args.camera_set):
                print(f"저장: {p}")
            return 0 if all(f is not None for f in frames.values()) else 1

        import rerun as rr

        rr.init("xlerobot_cameras")
        rr.spawn(memory_limit="10%")
        print("rerun 창에 카메라가 뜹니다. Ctrl+C 로 종료.")

        counts = dict.fromkeys(cams, 0)
        last_ids = dict.fromkeys(cams, None)
        t0 = time.time()
        try:
            while True:
                frames = src.read()
                for name, f in frames.items():
                    # 원격은 새 프레임이 없으면 같은 배열을 돌려주므로 새 것만 그립니다.
                    if f is None or id(f) == last_ids[name]:
                        continue
                    last_ids[name] = id(f)
                    counts[name] += 1
                    rr.log(f"observation.images.{name}",
                           rr.Image(f).compress())  # 두 소스 모두 RGB
                if time.time() - t0 >= 1.0:
                    dt = time.time() - t0
                    print("  ".join(f"{n} {c / dt:4.1f}fps" if c else f"{n} ✗NO FRAME"
                                    for n, c in counts.items()))
                    counts = dict.fromkeys(cams, 0)
                    t0 = time.time()
                time.sleep(0.005)
        except KeyboardInterrupt:
            pass
        return 0
    finally:
        src.close()


if __name__ == "__main__":
    sys.exit(main())
