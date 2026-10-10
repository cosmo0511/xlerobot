"""
preflight_cameras.py — 카메라 구성을 **믿을 수 있는지** 녹화 전에 검증합니다.

    # 🍓 파이에서 — 어떤 /dev/video* 가 쓸 수 있는 카메라인지 + 동시에 열리는지
    python src/preflight_cameras.py --list
    python src/preflight_cameras.py 4cam --local
    python src/preflight_cameras.py --identify          # 장치마다 한 장씩 저장 (이름 배정용)

    # 💻 PC 에서 — 파이 host.sh 가 떠 있어야 함. 녹화와 같은 경로로 검증
    python src/preflight_cameras.py 4cam

종료 코드 0 = 녹화해도 됨, 1 = 고칠 게 있음. 그래서 스크립트에서 && 로 묶을 수 있습니다.

■ 왜 이 파일이 있나 — camera_config.py --check 로는 안 걸리는 것들
---------------------------------------------------------------------------
`--check` 는 **경로가 있는지**만 봅니다. 그런데 4캠에서 실제로 터지는 건 그게 아닙니다:

 1. **조용한 검은 화면.** `bi_so_base_client.get_observation()` 은 파이에서 안 온
    카메라를 `np.zeros` 로 채웁니다 (경고 한 줄만 찍고). 파이의 host.sh 를 3cam 으로,
    PC 의 record.sh 를 4cam 으로 띄우면 **base 칸이 전부 검정인 데이터셋**이 96개
    쌓입니다. 녹화는 되돌릴 수 없습니다. 이게 제일 위험합니다.
 2. **YUYV 로 열림.** 경로는 맞지만 MJPEG 협상이 안 되면 640x480 4대는 USB 대역폭을
    못 버팁니다. 프레임이 뚝뚝 끊긴 채로 녹화됩니다.
 3. **멈춘 화면.** 열렸고 프레임도 오는데 같은 그림이 계속 옵니다 (케이블 접촉 등).
 4. **메타데이터 노드.** UVC 카메라 하나가 /dev/video* 를 보통 **2개** 만듭니다.
    짝수만 쓰면 된다는 보장이 없습니다 (이 저장소의 0/2/4/6 도 추측값입니다).
 5. **장치 번호가 재부팅마다 바뀜.** /dev/video6 이 다음엔 /dev/video2 가 됩니다.
    그래서 `--list` 는 /dev/v4l/by-id 또는 by-path 의 **고정 경로**를 알려줍니다.

■ 두 모드
---------------------------------------------------------------------------
`--local` (파이에서) 장치를 직접, **4대 동시에** 엽니다. 협상된 FOURCC·실측 fps·
            추정 대역폭을 봅니다. CLAUDE.md 의 "4캠이 실제로 되는지"가 이걸로 답이 됩니다.

기본 (PC에서) 파이 호스트 → bi_so_base_client, 즉 **녹화와 똑같은 경로**로 봅니다.
            여기서 통과하면 그 그림이 그대로 데이터셋에 들어갑니다. 1번(조용한 검은
            화면)은 이 모드에서만 잡힙니다 — 파이와 PC 의 CAMERA_SET 이 어긋난 걸
            여기서 잡습니다. 로봇에 명령은 보내지 않습니다 (팔·바퀴 안 움직임).
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import struct
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from camera_config import (  # noqa: E402
    CameraConfigError,
    dataset_fps,
    flat_cameras,
    list_camera_sets,
    load_camera_set,
)

SAVE_DIR = PROJECT_ROOT / "outputs" / "camera_check"

# 파이 호스트가 관측을 보낼 때 쓰는 JPEG 품질 (bi_so_base_host.py 와 같은 기본값).
# 대역폭 추정을 호스트와 같은 조건으로 맞추기 위해 읽습니다.
JPEG_QUALITY = int(os.environ.get("LEROBOT_JPEG_QUALITY", "70"))

DEFAULT_SECONDS = 5.0

# 프레임이 "거의 검정"인 기준. 완전히 0 (max==0) 은 클라이언트가 채운 자리표시자라
# 따로 구분합니다 — 그건 "프레임이 아예 안 왔다"는 뜻입니다.
DARK_MEAN = 2.0

# 실측 fps 가 설정값의 이 비율보다 낮으면 실패로 봅니다.
FPS_FLOOR = 0.80


# =============================================================================
# v4l2 — /dev/video* 가 정말 "영상 캡처" 노드인지 커널에 직접 물어봅니다
# =============================================================================
# v4l2-ctl 이 파이에 깔려 있지 않을 수 있어서 ioctl 을 직접 씁니다 (표준 라이브러리만).
VIDIOC_QUERYCAP = 0x80685600       # _IOR('V', 0, struct v4l2_capability)   104 bytes
VIDIOC_ENUM_FMT = 0xC0405602       # _IOWR('V', 2, struct v4l2_fmtdesc)      64 bytes

CAP_VIDEO_CAPTURE = 0x00000001
CAP_META_CAPTURE = 0x00800000
CAP_DEVICE_CAPS = 0x80000000

BUF_TYPE_VIDEO_CAPTURE = 1
FOURCC_MJPG = 0x47504A4D           # v4l2_fourcc('M','J','P','G')


def fourcc_str(value: int) -> str:
    """정수 FOURCC -> 'MJPG' 같은 네 글자."""
    value = int(value) & 0xFFFFFFFF
    text = "".join(chr((value >> (8 * i)) & 0xFF) for i in range(4))
    return text if text.isprintable() else f"0x{value:08x}"


@dataclass
class VideoNode:
    path: str                      # /dev/videoN
    card: str = ""                 # 카메라 모델명 (커널이 알려주는 것)
    bus: str = ""                  # usb-0000:01:00.0-1.2  (꽂은 포트)
    is_capture: bool = False       # 영상 캡처 노드인가 (메타데이터 노드가 아닌가)
    is_meta: bool = False
    formats: tuple[int, ...] = ()
    by_id: str | None = None
    by_path: str | None = None
    error: str = ""

    @property
    def has_mjpg(self) -> bool:
        return FOURCC_MJPG in self.formats

    @property
    def is_usb(self) -> bool:
        """USB 에 꽂힌 장치인가.

        라즈베리파이는 `bcm2835-isp` 같은 **내장 영상처리 장치**를 /dev/video* 로
        여럿 내놓습니다. 이것들도 "영상 캡처" 능력이 있다고 신고하지만 카메라가
        아닙니다 (bus_info 가 `platform:...`). 세면 개수가 틀어지고 고정경로
        추천까지 망가져서, USB 인 것만 카메라로 칩니다.
        """
        return self.bus.startswith("usb")

    def stable_path(self, scheme: str) -> str:
        """고른 방식의 고정 경로. 없으면 /dev/videoN 으로 떨어집니다."""
        if scheme == "by-id":
            return self.by_id or self.by_path or self.path
        if scheme == "by-path":
            return self.by_path or self.by_id or self.path
        return self.path

    @property
    def stable(self) -> str:
        """방식을 안 정했을 때의 기본. by-id 가 겹칠 수 있으니 되도록
        stable_path(scheme) 을 쓰세요."""
        return self.by_id or self.by_path or self.path


def _querycap(path: str) -> tuple[str, str, str, int]:
    buf = bytearray(104)
    with open(path, "rb", buffering=0) as f:
        fcntl.ioctl(f, VIDIOC_QUERYCAP, buf, True)
    driver = bytes(buf[0:16]).split(b"\0")[0].decode("utf-8", "replace")
    card = bytes(buf[16:48]).split(b"\0")[0].decode("utf-8", "replace")
    bus = bytes(buf[48:80]).split(b"\0")[0].decode("utf-8", "replace")
    caps, device_caps = struct.unpack_from("<II", buf, 84)
    # device_caps 는 "이 노드 하나"의 능력, capabilities 는 "장치 전체"의 능력입니다.
    # 카메라 하나가 캡처 노드 + 메타데이터 노드를 만들면 capabilities 에는 둘 다
    # 켜져 있으므로, 노드를 구분하려면 반드시 device_caps 를 봐야 합니다.
    effective = device_caps if caps & CAP_DEVICE_CAPS else caps
    return driver, card, bus, effective


def _enum_formats(path: str) -> tuple[int, ...]:
    out: list[int] = []
    try:
        with open(path, "rb", buffering=0) as f:
            for index in range(64):
                buf = bytearray(64)
                struct.pack_into("<II", buf, 0, index, BUF_TYPE_VIDEO_CAPTURE)
                try:
                    fcntl.ioctl(f, VIDIOC_ENUM_FMT, buf, True)
                except OSError:
                    break
                out.append(struct.unpack_from("<I", buf, 44)[0])
    except OSError:
        pass
    return tuple(out)


def _symlink_map() -> tuple[dict[str, str], dict[str, str]]:
    """/dev/videoN -> by-id, by-path 링크 경로."""
    by_id: dict[str, str] = {}
    by_path: dict[str, str] = {}
    for folder, table in (("by-id", by_id), ("by-path", by_path)):
        root = Path("/dev/v4l") / folder
        if not root.is_dir():
            continue
        for link in sorted(root.iterdir()):
            try:
                target = str(link.resolve())
            except OSError:
                continue
            # 같은 장치에 링크가 여러 개면 (usb / usbv2) 짧은 쪽이 읽기 좋습니다.
            if target not in table or len(str(link)) < len(table[target]):
                table[target] = str(link)
    return by_id, by_path


def enumerate_video_nodes() -> list[VideoNode]:
    """/dev/video* 전부를 커널에 물어보고 분류합니다."""
    by_id, by_path = _symlink_map()
    nodes: list[VideoNode] = []
    paths = sorted(Path("/dev").glob("video*"),
                   key=lambda p: (len(p.name), p.name))
    for path in paths:
        node = VideoNode(path=str(path),
                         by_id=by_id.get(str(path)),
                         by_path=by_path.get(str(path)))
        try:
            _driver, card, bus, caps = _querycap(str(path))
        except PermissionError:
            node.error = "권한 없음 (video 그룹에 넣으세요: sudo usermod -aG video $USER)"
            nodes.append(node)
            continue
        except OSError as e:
            node.error = f"QUERYCAP 실패: {e}"
            nodes.append(node)
            continue
        node.card = card
        node.bus = bus
        node.is_capture = bool(caps & CAP_VIDEO_CAPTURE)
        node.is_meta = bool(caps & CAP_META_CAPTURE)
        if node.is_capture:
            node.formats = _enum_formats(str(path))
        nodes.append(node)
    return nodes


def capture_nodes(nodes: list[VideoNode]) -> list[VideoNode]:
    return [n for n in nodes if n.is_capture]


def real_cameras(nodes: list[VideoNode]) -> list[VideoNode]:
    """진짜 카메라만 — USB 에 꽂힌 캡처 장치.

    파이에서 그냥 "캡처 장치"를 세면 `bcm2835-isp` 가 4개씩 끼어서 8개가 됩니다.
    """
    return [n for n in capture_nodes(nodes) if n.is_usb]


def recommend_stable_scheme(cams: list[VideoNode]) -> str:
    """by-id 를 쓸 수 있나, by-path 를 써야 하나.

    같은 모델 카메라를 여러 대 꽂으면 by-id 이름이 **겹칩니다.** udev 는 링크를
    하나만 만들고, 그 링크가 재부팅·재연결 때 그중 **누구를 가리킬지 보장이
    없습니다.** 실제로 그런 일이 있었습니다 (3대가 Generic_USB_Camera_200901010001).
    겹치면 "꽂은 USB 포트" 기준인 by-path 를 써야 합니다.
    """
    if not cams:
        return "none"
    ids = [n.by_id for n in cams]
    if all(ids) and len(set(ids)) == len(cams):
        return "by-id"
    paths = [n.by_path for n in cams]
    if all(paths) and len(set(paths)) == len(cams):
        return "by-path"
    return "dev"


# =============================================================================
# 프레임 판정
# =============================================================================
def frame_fingerprint(frame) -> bytes:
    """프레임이 **새 것인지** 보기 위한 짧은 지문.

    전체를 해시하면 4대 x 30fps 에서 꽤 무겁습니다. 8픽셀마다 샘플링해도
    실제 카메라 노이즈 때문에 매 프레임 달라지므로 충분합니다.
    """
    return hashlib.blake2b(frame[::8, ::8].tobytes(), digest_size=8).digest()


def is_placeholder(frame) -> bool:
    """정확히 전부 0 — 클라이언트가 채운 자리표시자. "프레임이 안 왔다"는 뜻입니다.

    실제 카메라는 렌즈를 막아도 센서 노이즈 때문에 전부 0 이 되지 않습니다.
    """
    return bool(frame.max() == 0)


def is_dark(frame) -> bool:
    """거의 검정 — 렌즈 캡이 씌워졌거나 불이 꺼진 것."""
    return bool(frame.mean() < DARK_MEAN)


@dataclass
class CamStats:
    """카메라 한 대의 측정 결과."""

    name: str
    device: str = ""
    opened: bool = True
    error: str = ""
    reads: int = 0                 # read 를 시도해서 뭔가 받은 횟수
    unique: int = 0                # 그중 **새** 프레임 (멈춘 화면 판정용)
    placeholder: int = 0           # 전부 0 (= 안 온 프레임)
    dark: int = 0                  # 거의 검정
    fourcc: str = ""
    size: tuple[int, int] = (0, 0)
    jpeg_samples: list[int] = field(default_factory=list)
    _last: bytes | None = None

    def observe(self, frame) -> None:
        if frame is None:
            return
        self.reads += 1
        if is_placeholder(frame):
            self.placeholder += 1
            return
        fingerprint = frame_fingerprint(frame)
        if fingerprint == self._last:
            return
        self._last = fingerprint
        self.unique += 1
        if is_dark(frame):
            self.dark += 1
        if self.size == (0, 0):
            self.size = (frame.shape[1], frame.shape[0])
        # 대역폭 추정용 표본. 매 프레임 다시 인코딩하면 측정이 느려져서 솎아냅니다.
        if self.unique % 5 == 1 and len(self.jpeg_samples) < 40:
            import cv2
            ok, buf = cv2.imencode(".jpg", frame,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
            if ok:
                self.jpeg_samples.append(int(buf.size))

    def fps(self, elapsed: float) -> float:
        return self.unique / elapsed if elapsed > 0 else 0.0

    def mbps(self, elapsed: float) -> float:
        """추정 링크 대역폭 (Mbit/s). 호스트와 같은 JPEG 품질로 다시 인코딩해서 봅니다."""
        if not self.jpeg_samples:
            return 0.0
        avg = sum(self.jpeg_samples) / len(self.jpeg_samples)
        return avg * self.fps(elapsed) * 8 / 1e6


# =============================================================================
# 모드 1 — 파이에서 장치를 직접, 동시에 엽니다
# =============================================================================
def probe_local(cams: dict, seconds: float) -> tuple[dict[str, CamStats], float]:
    """카메라 전부를 **동시에** 열고 읽습니다.

    한 대씩 따로 열어보면 다 되는데 4대를 같이 열면 안 되는 일이 흔합니다
    (USB 대역폭). 그래서 반드시 동시에 엽니다.
    """
    import cv2

    stats = {name: CamStats(name=name, device=str(spec["index_or_path"]))
             for name, spec in cams.items()}
    caps: dict[str, object] = {}

    for name, spec in cams.items():
        device = spec["index_or_path"]
        cap = (cv2.VideoCapture(device, cv2.CAP_V4L2) if isinstance(device, str)
               else cv2.VideoCapture(int(device)))
        # 순서가 중요합니다: FOURCC 를 먼저 박아야 해상도 협상이 MJPEG 기준으로 갑니다.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, spec.get("width", 640))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, spec.get("height", 480))
        cap.set(cv2.CAP_PROP_FPS, spec.get("fps", 30))
        if not cap.isOpened():
            stats[name].opened = False
            stats[name].error = "열 수 없음 (다른 프로세스가 쓰는 중? host.sh 를 끄세요)"
            cap.release()
            continue
        stats[name].fourcc = fourcc_str(cap.get(cv2.CAP_PROP_FOURCC))
        caps[name] = cap

    if not caps:
        return stats, 0.0

    stop = threading.Event()

    def pump(name: str, cap) -> None:
        while not stop.is_set():
            ok, frame = cap.read()
            if not ok:
                continue
            stats[name].observe(frame)

    threads = [threading.Thread(target=pump, args=(n, c), daemon=True)
               for n, c in caps.items()]

    # 첫 프레임 몇 장은 노출·자동초점이 잡히는 중이라 버립니다.
    for cap in caps.values():
        cap.read()

    start = time.time()
    for t in threads:
        t.start()
    try:
        while time.time() - start < seconds:
            time.sleep(0.1)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=2.0)
        elapsed = time.time() - start
        for cap in caps.values():
            cap.release()
    return stats, elapsed


# =============================================================================
# 모드 2 — PC 에서, 녹화와 똑같은 경로 (파이 호스트 -> bi_so_base_client)
# =============================================================================
def probe_remote(cams: dict, remote_ip: str, seconds: float
                 ) -> tuple[dict[str, CamStats], float]:
    """파이 호스트에 붙어서 받은 프레임을 봅니다. 녹화에 들어갈 그림 그대로입니다."""
    import logging

    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
    from lerobot.robots.bi_so_follower import BiSOBaseClient, BiSOBaseClientConfig

    logging.basicConfig(level=logging.ERROR)   # "No frame yet" 가 매 프레임 찍히지 않게

    cfg = BiSOBaseClientConfig(
        remote_ip=remote_ip,
        cameras={
            name: OpenCVCameraConfig(
                index_or_path=spec["index_or_path"],
                width=spec.get("width", 640),
                height=spec.get("height", 480),
                fps=spec.get("fps", 30),
            )
            for name, spec in cams.items()
        },
    )
    stats = {name: CamStats(name=name, device="(파이에서 받음)") for name in cams}

    robot = BiSOBaseClient(cfg)
    robot.connect()
    try:
        # 연결 직후에는 아직 관측이 안 들어와 있습니다. 조금 기다립니다.
        time.sleep(1.0)
        start = time.time()
        while time.time() - start < seconds:
            # get_observation() 은 못 받은 카메라를 검은 화면으로 채웁니다. 그래서
            # 자리표시자와 진짜 프레임을 구분하려고 last_frames 를 직접 봅니다.
            robot.get_observation()
            for name in cams:
                stats[name].observe(robot.last_frames.get(name))
            time.sleep(0.005)
        elapsed = time.time() - start
    finally:
        robot.disconnect()   # 바퀴 정지 명령을 보냅니다 (보기만 했으니 해 없음)
    return stats, elapsed


# =============================================================================
# 판정
# =============================================================================
@dataclass
class Problem:
    camera: str
    detail: str
    fix: str


def judge(stats: dict[str, CamStats], elapsed: float, want_fps: int,
          local: bool) -> list[Problem]:
    """측정 결과 -> 고쳐야 할 것 목록. 비어 있으면 녹화해도 됩니다."""
    problems: list[Problem] = []
    for name, s in stats.items():
        if not s.opened:
            problems.append(Problem(name, s.error or "열 수 없음",
                                    "장치 경로를 --list 로 다시 확인하세요."))
            continue

        if s.unique == 0:
            if local:
                problems.append(Problem(
                    name, "프레임이 한 장도 안 옵니다",
                    "케이블·허브를 바꿔 꽂아보세요. --identify 로 장치를 다시 찾으세요."))
            else:
                problems.append(Problem(
                    name, "파이가 이 카메라를 **안 보내고 있습니다** (검은 화면만 옴)",
                    "파이의 host.sh 를 같은 구성으로 띄웠는지 확인하세요: "
                    "CAMERA_SET=<이 구성> ./scripts/host.sh"))
            continue

        fps = s.fps(elapsed)
        if fps < want_fps * FPS_FLOOR:
            problems.append(Problem(
                name, f"fps 가 낮습니다 — 실측 {fps:.1f} / 설정 {want_fps}",
                "허브를 나눠 꽂거나, yaml 의 fps 를 낮추세요 "
                "(policy.fps 도 같이 맞춰야 합니다)."
                if local else
                "무선 대역폭이 모자랍니다. LEROBOT_JPEG_QUALITY 를 낮추거나 "
                "yaml 의 fps 를 낮추세요."))

        if local and s.fourcc and s.fourcc != "MJPG":
            problems.append(Problem(
                name, f"MJPEG 이 아니라 {s.fourcc} 로 열렸습니다",
                "raw 포맷은 USB 대역폭을 몇 배로 먹습니다. 이 카메라가 MJPG 를 "
                "지원하는지 --list 로 확인하세요."))

        if s.dark == s.unique and s.unique > 0:
            problems.append(Problem(
                name, "받은 프레임이 전부 거의 검정입니다",
                "렌즈 캡을 벗기거나 불을 켜세요. 그래도 검으면 장치 배정이 틀렸습니다."))

        if s.placeholder and s.unique:
            # 섞여 나오면 중간에 끊긴 것. 녹화 중에도 끊길 수 있으니 알려줍니다.
            problems.append(Problem(
                name, f"중간에 프레임이 끊겼습니다 (검은 화면 {s.placeholder}회)",
                "무선이 불안정합니다. 파이를 AP 에 가까이 두세요."))
    return problems


# =============================================================================
# 출력
# =============================================================================
def print_nodes(nodes: list[VideoNode]) -> None:
    cams = real_cameras(nodes)
    scheme = recommend_stable_scheme(cams)
    others = [n for n in capture_nodes(nodes) if not n.is_usb]

    print(f"/dev/video* {len(nodes)}개 — 그중 **USB 카메라 {len(cams)}개**\n")
    for n in nodes:
        if n.error:
            print(f"  ✗ {n.path:<14} {n.error}")
            continue
        if n.is_meta and not n.is_capture:
            print(f"  · {n.path:<14} {n.card}  [메타데이터 노드 — 카메라가 아닙니다]")
            continue
        if not n.is_capture:
            print(f"  · {n.path:<14} {n.card}  [캡처 아님]")
            continue
        if not n.is_usb:
            # 파이 내장 ISP. 캡처라고 신고하지만 카메라가 아닙니다.
            print(f"  · {n.path:<14} {n.card}  [파이 내장 영상처리 — 카메라 아님]")
            continue

        mark = "✓" if n.has_mjpg else "⚠"
        print(f"  {mark} {n.path:<14} {n.card}"
              f"{'' if n.has_mjpg else '   ← MJPG 미지원!'}")
        print(f"      버스     {n.bus}")
        print(f"      by-id    {n.by_id or '(없음 — 같은 모델이 여러 대라 겹침)'}")
        print(f"      by-path  {n.by_path or '(없음)'}")

    print()
    if scheme == "by-id":
        print("고정 경로는 **by-id** 를 쓰세요 — 카메라마다 이름이 다릅니다.")
        print("USB 포트를 바꿔 꽂아도 그대로입니다.")
    elif scheme == "by-path":
        missing = [n.path for n in cams if not n.by_id]
        print("고정 경로는 **by-path** 를 쓰세요.")
        print(f"  같은 모델 카메라가 섞여 있어 by-id 가 겹칩니다 "
              f"(by-id 가 없는 장치: {', '.join(missing) or '없음'}).")
        print("  udev 는 겹치는 이름으로 링크를 **하나만** 만들고, 그 링크가")
        print("  재부팅·재연결 때 그중 누구를 가리킬지 보장이 없습니다.")
        print("  by-path 는 '꽂은 USB 포트' 기준이라 안전합니다 — 대신")
        print("  **포트를 바꿔 꽂으면 경로가 바뀝니다. 꽂은 자리를 테이프로 표시하세요.**")
    elif scheme == "dev":
        print("⚠ 고정 경로를 못 찾았습니다. /dev/videoN 은 재부팅하면 번호가 바뀝니다.")
    else:
        print("⚠ USB 카메라를 못 찾았습니다. 케이블·허브를 확인하세요.")

    if others:
        print(f"\n(파이 내장 영상처리 장치 {len(others)}개는 카메라가 아니라서 셈에서 뺐습니다: "
              f"{', '.join(n.path for n in others)})")

    if len(cams) < 4:
        print(f"\n⚠ USB 카메라가 {len(cams)}개뿐입니다. 4캠에는 4개가 필요합니다.")
    no_mjpg = [n.path for n in cams if not n.has_mjpg]
    if no_mjpg:
        print(f"\n⚠ MJPG 를 지원 안 하는 카메라: {', '.join(no_mjpg)}")
        print("  raw(YUYV) 로 열리면 4대 동시는 USB 대역폭을 못 버팁니다.")

    print("\n이름 배정(top / base / left_wrist / right_wrist)은 자동으로 알 수 없습니다.")
    print("  ./scripts/run_4cam.sh identify   ← 장치마다 한 장씩 찍어서 보고 정하세요")


def print_yaml_block(nodes: list[VideoNode], want_fps: int = 30) -> None:
    """config/cameras.4cam.yaml 에 붙여넣을 블록. 이름 배정은 사람이 합니다."""
    cams = real_cameras(nodes)
    scheme = recommend_stable_scheme(cams)
    slots = ["top", "base", "left_wrist", "right_wrist"]

    def entry(slot: str) -> tuple[str, str]:
        i = slots.index(slot)
        if i >= len(cams):
            return "/dev/video?", "  # 장치 부족"
        n = cams[i]
        return n.stable_path(scheme), f"  # {n.card} @ {n.bus}"

    print("# --- 아래를 config/cameras.4cam.yaml 에 옮기세요 -----------------------")
    print(f"# 고정 경로 방식: {scheme}")
    if scheme == "by-path":
        print("# ⚠ by-path 는 꽂은 USB 포트 기준입니다. 포트를 바꿔 꽂으면 경로가 바뀝니다.")
    print("# ⚠ 어느 장치가 어느 카메라인지는 identify 로 **직접 보고** 정하세요.")
    print("#   아래는 /dev/videoN 순서대로 배정한 것일 뿐입니다.")
    print()
    print("top_cameras:")
    for slot in ("top", "base"):
        dev, note = entry(slot)
        pad = " " * (6 - len(slot))
        print(f'  {slot}:{pad}{{index_or_path: "{dev}", '
              f"width: 640, height: 480, fps: {want_fps}}}{note}")
    for block, slot in (("left_cameras", "left_wrist"), ("right_cameras", "right_wrist")):
        dev, note = entry(slot)
        print(f"{block}:")
        print(f'  wrist: {{index_or_path: "{dev}", '
              f"width: 640, height: 480, fps: {want_fps}}}{note}")


def identify(nodes: list[VideoNode]) -> int:
    """캡처 장치마다 한 장씩 찍어 저장합니다. 보고 이름을 배정하세요."""
    import cv2

    caps = real_cameras(nodes)
    scheme = recommend_stable_scheme(caps)
    if not caps:
        print("USB 카메라가 없습니다.", file=sys.stderr)
        return 1

    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    saved = 0
    # 한 대씩 따로 엽니다 — 동시에 열면 대역폭 때문에 실패할 수 있고, 여기서는
    # "이 장치가 무엇을 보는지"만 알면 됩니다.
    for node in caps:
        cap = cv2.VideoCapture(node.path, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        if not cap.isOpened():
            print(f"  ✗ {node.path} 못 열었습니다 (host.sh 가 쓰는 중?)")
            cap.release()
            continue
        frame = None
        deadline = time.time() + 2.0      # 자동 노출이 잡힐 시간
        while time.time() < deadline:
            ok, f = cap.read()
            if ok:
                frame = f
        cap.release()
        if frame is None:
            print(f"  ✗ {node.path} 프레임을 못 받았습니다")
            continue
        name = Path(node.path).name
        out = SAVE_DIR / f"{stamp}_{name}.jpg"
        cv2.imwrite(str(out), frame)
        saved += 1
        print(f"  ✓ {out}")
        print(f"      {node.card} @ {node.bus}")
        print(f"      고정경로 {node.stable_path(scheme)}")

    print(f"\n{saved}장 저장했습니다. 그림을 보고 어느 게 top / base / "
          "left_wrist / right_wrist 인지 정한 다음,")
    print("그 **고정경로**를 config/cameras.4cam.yaml 에 적으세요.")
    return 0 if saved == len(caps) else 1


def print_report(stats: dict[str, CamStats], elapsed: float, want_fps: int,
                 local: bool) -> None:
    print(f"\n{elapsed:.1f}초 측정 — 카메라 {len(stats)}대 동시"
          if local else f"\n{elapsed:.1f}초 측정 — 파이에서 받은 것")
    print(f"{'카메라':<14} {'포맷':<6} {'해상도':<10} {'fps':>6}  "
          f"{'추정Mbps':>9}  상태")
    total = 0.0
    for name, s in stats.items():
        fps = s.fps(elapsed)
        mbps = s.mbps(elapsed)
        total += mbps
        size = f"{s.size[0]}x{s.size[1]}" if s.size != (0, 0) else "-"
        if not s.opened:
            state = "✗ 못 엶"
        elif s.unique == 0:
            state = "✗ 프레임 없음 (검은 화면)"
        elif fps < want_fps * FPS_FLOOR:
            state = f"△ 느림 (설정 {want_fps})"
        elif s.dark == s.unique:
            state = "△ 거의 검정"
        else:
            state = "✓"
        print(f"{name:<14} {s.fourcc or '-':<6} {size:<10} {fps:>6.1f}  "
              f"{mbps:>9.1f}  {state}")
    print(f"{'합계':<14} {'':<6} {'':<10} {'':>6}  {total:>9.1f}")
    if total > 0:
        where = "USB" if local else "무선"
        print(f"\n{where} 구간으로 약 {total:.0f} Mbps 가 흐릅니다 "
              f"(JPEG 품질 {JPEG_QUALITY} 기준 추정).")
        if not local and total > 40:
            print("  무선이 이걸 못 버티면 fps 가 먼저 떨어집니다. 위 fps 를 보세요.")
            print("  줄이려면: LEROBOT_JPEG_QUALITY=55 ./scripts/host.sh")


# =============================================================================
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="카메라 구성이 녹화해도 될 상태인지 검증합니다.")
    ap.add_argument("camera_set", nargs="?",
                    default=os.environ.get("CAMERA_SET", "4cam"),
                    help="카메라 구성 이름 (기본: $CAMERA_SET 또는 4cam)")
    ap.add_argument("--local", action="store_true",
                    help="장치를 이 기기에서 직접 엶 (파이에서 실행)")
    ap.add_argument("--list", action="store_true",
                    help="/dev/video* 를 분류해서 보여주고 끝냅니다 (파이에서)")
    ap.add_argument("--identify", action="store_true",
                    help="캡처 장치마다 한 장씩 저장 (이름 배정용, 파이에서)")
    ap.add_argument("--emit-yaml", action="store_true",
                    help="--list 와 함께. yaml 블록을 찍어줍니다")
    ap.add_argument("--remote-ip", help="파이 주소 (기본: robot.yaml arms.remote_ip)")
    ap.add_argument("--seconds", type=float, default=DEFAULT_SECONDS,
                    help=f"측정 시간 (기본 {DEFAULT_SECONDS}초)")
    args = ap.parse_args(argv)

    if args.list or args.identify:
        if not Path("/dev").is_dir():
            print("리눅스에서만 됩니다.", file=sys.stderr)
            return 1
        nodes = enumerate_video_nodes()
        if args.identify:
            return identify(nodes)
        print_nodes(nodes)
        if args.emit_yaml:
            print()
            print_yaml_block(nodes)
        return 0 if len(real_cameras(nodes)) >= 4 else 1

    try:
        cam_set = load_camera_set(args.camera_set)
        cams = flat_cameras(cam_set)
        want_fps = dataset_fps(cam_set)
    except CameraConfigError as e:
        print(f"오류: {e}", file=sys.stderr)
        print(f"쓸 수 있는 구성: {', '.join(list_camera_sets())}", file=sys.stderr)
        return 1

    print(f"카메라 구성 {args.camera_set} — {len(cams)}대, 설정 fps {want_fps}")
    for name, spec in cams.items():
        print(f"  observation.images.{name:<14} {spec['index_or_path']}")

    if args.local:
        print("\n장치를 이 기기에서 **동시에** 엽니다 "
              "(host.sh 가 떠 있으면 먼저 끄세요) ...")
        stats, elapsed = probe_local(cams, args.seconds)
    else:
        import yaml
        robot_yaml = yaml.safe_load(
            (PROJECT_ROOT / "config" / "robot.yaml").read_text(encoding="utf-8"))
        remote_ip = args.remote_ip or robot_yaml["arms"]["remote_ip"]
        print(f"\n파이 호스트({remote_ip})에 붙습니다 — 녹화와 같은 경로 ...")
        try:
            stats, elapsed = probe_remote(cams, remote_ip, args.seconds)
        except Exception as e:
            print(f"\n오류: 파이 호스트에 못 붙었습니다 — {e}", file=sys.stderr)
            print("파이에서 이걸 먼저 띄우세요: "
                  f"CAMERA_SET={args.camera_set} ./scripts/host.sh", file=sys.stderr)
            return 1

    print_report(stats, elapsed, want_fps, args.local)

    problems = judge(stats, elapsed, want_fps, args.local)
    if not problems:
        print(f"\n✓ 구성 {args.camera_set} — 녹화해도 됩니다.")
        if not args.local:
            print("  다음: CAMERA_SET=%s ./scripts/record.sh red 8 --first"
                  % args.camera_set)
        return 0

    print(f"\n✗ 고칠 것 {len(problems)}개 — 녹화하지 마세요:\n")
    for p in problems:
        print(f"  [{p.camera}] {p.detail}")
        print(f"       → {p.fix}")
    print("\n녹화는 되돌릴 수 없습니다. 여기서 고치는 게 훨씬 쌉니다.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
