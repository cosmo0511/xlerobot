"""
camera_config.py — 카메라 구성의 **단일 진실 소스**.

    python src/camera_config.py                 # 쓸 수 있는 구성 목록
    python src/camera_config.py 3cam            # 그 구성의 관측 키 확인
    python src/camera_config.py 3cam --check    # /dev/video* 가 실제로 있는지 확인
    python src/camera_config.py 3cam --record-args   # lerobot-record 인자 출력
    python src/camera_config.py 4cam --record-args --robot-type=xlerobot
                                                #   ↑ 로봇 클래스에 맞는 형태로
    python src/camera_config.py 3cam --fps      # 데이터셋 fps
    python src/camera_config.py 3cam --table    # 표만 (배너용)

■ 왜 이 파일이 있나
---------------------------------------------------------------------------
카메라 이름이 **녹화 때와 추론 때 글자까지 같아야** 합니다. 다르면 정책이
행동을 하나도 못 내놓고 팔이 가만히 있습니다. 원인을 찾기도 어렵습니다.

전에는 같은 이름을 두 곳에 손으로 적어뒀습니다:

    scripts/record.sh   CAM_TOP=/dev/video0 ...   (녹화)
    config/robot.yaml   top_cameras: {...}        (추론)

한쪽만 고치면 그때부터 어긋납니다. 이제 둘 다 `config/cameras.<이름>.yaml`
하나를 읽습니다. 구성을 바꾸려면 그 파일만 고치면 됩니다.

■ 카메라 구성을 새로 만들려면
---------------------------------------------------------------------------
`config/cameras.<이름>.yaml` 을 하나 더 만들고, 녹화할 때
`CAMERA_SET=<이름> ./scripts/record.sh ...` 로 돌리면 됩니다.
브랜치를 나누지 마세요. 코드는 한 벌이고 설정만 여러 벌입니다.

■ 이름 규칙 (bi_so_follower 의 동작)
---------------------------------------------------------------------------
    top_cameras   에 적은 이름은 그대로        -> observation.images.top
    left_cameras  에 적은 이름은 left_  접두사 -> observation.images.left_wrist
    right_cameras 에 적은 이름은 right_ 접두사 -> observation.images.right_wrist

팔에 **안** 묶인 카메라(탑캠, 베이스캠)는 전부 `top_cameras` 에 넣습니다.
블록 이름이 `top_cameras` 라서 혼동스럽지만, "로봇 몸체에 달린 카메라"라는
뜻입니다. 베이스캠을 여기 넣으면 키가 observation.images.base 가 됩니다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

# 블록 이름 -> 관측 키 접두사
BLOCKS = {
    "top_cameras": "",
    "left_cameras": "left_",
    "right_cameras": "right_",
}

DEFAULT_SET = "3cam"

# 로봇 클래스에 따라 lerobot 이 카메라를 받는 방식이 다릅니다.
#
#   "per_arm" — bi_so_follower 계열. 카메라를 팔별로 나눠서 넘기고,
#               lerobot 이 left_/right_ 접두사를 **자동으로 붙입니다.**
#                 --robot.cameras / --robot.left_arm_config.cameras / ...
#
#   "flat"    — xlerobot 계열 (양팔 + 옴니휠 베이스). 카메라가 로봇 하나에
#               평평하게 달립니다. 접두사를 **자동으로 안 붙이므로**
#               우리가 최종 이름(left_wrist 등)을 그대로 적어 넘깁니다.
#                 --robot.cameras 하나만
#
# 둘 중 뭘 쓰든 **최종 관측 키는 똑같습니다** (observation.images.left_wrist 등).
# 그래서 로봇 클래스를 바꿔도 학습된 정책의 카메라 키는 안 바뀝니다.
LAYOUTS = ("per_arm", "flat")
DEFAULT_LAYOUT = "per_arm"

# 로봇 타입 -> 레이아웃. 모르는 타입은 per_arm 으로 둡니다.
#
# 우리 녹화 경로 (lerobot 0.6 + vendor/lerobot-0.6.patch):
#   PC  : bi_so_base_client   — 카메라를 열지 않고 파이가 보낸 JPEG 만 받음.
#                               이름을 키로 맞추므로 최종 이름을 그대로 넘김 → flat
#   파이 : bi_so_base_follower — 실제로 카메라를 엶 (bi_so_base_host 가 사용).
#                               bi_so_follower 를 상속해서 접두사 자동 → per_arm
ROBOT_LAYOUTS = {
    "bi_so_follower": "per_arm",
    "bi_so_base_follower": "per_arm",
    "bi_so_client": "flat",
    "bi_so_base_client": "flat",
    "bi_so101_follower": "per_arm",
    "xlerobot": "flat",
    "xlerobot_client": "flat",
    "xlerobot_2wheels": "flat",
    "xlerobot_mecanum": "flat",
}


class CameraConfigError(Exception):
    """카메라 구성이 잘못됐을 때. 메시지에 고칠 방법까지 담습니다."""


# =============================================================================
# 읽기
# =============================================================================
def camera_set_path(name: str) -> Path:
    return CONFIG_DIR / f"cameras.{name}.yaml"


def list_camera_sets() -> list[str]:
    """쓸 수 있는 카메라 구성 이름 목록."""
    return sorted(p.name[len("cameras."):-len(".yaml")]
                  for p in CONFIG_DIR.glob("cameras.*.yaml"))


def load_camera_set(name: str) -> dict:
    """`config/cameras.<name>.yaml` 을 읽어서 카메라 블록만 돌려줍니다."""
    path = camera_set_path(name)
    if not path.exists():
        available = ", ".join(list_camera_sets()) or "(없음)"
        raise CameraConfigError(
            f"카메라 구성 {name!r} 이 없습니다 ({path}).\n"
            f"쓸 수 있는 구성: {available}"
        )

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cams = {block: dict(raw.get(block) or {}) for block in BLOCKS}

    if not any(cams.values()):
        raise CameraConfigError(
            f"{path} 에 카메라가 하나도 없습니다. "
            f"{', '.join(BLOCKS)} 중 최소 하나를 채우세요."
        )

    # 같은 장치를 두 번 열면 한쪽이 검은 화면으로 녹화됩니다. 미리 막습니다.
    seen: dict[str, str] = {}
    for block, entries in cams.items():
        for cam_name, spec in entries.items():
            if "index_or_path" not in spec:
                raise CameraConfigError(
                    f"{path}: {block}.{cam_name} 에 index_or_path 가 없습니다."
                )
            device = str(spec["index_or_path"])
            if device in seen:
                raise CameraConfigError(
                    f"{path}: 장치 {device} 를 {seen[device]} 와 "
                    f"{block}.{cam_name} 가 함께 쓰고 있습니다. "
                    "한 장치는 한 카메라에만 배정하세요."
                )
            seen[device] = f"{block}.{cam_name}"

    return cams


def resolve_cameras(arms_cfg: dict) -> dict:
    """robot.yaml 의 arms 블록에서 카메라 구성을 뽑습니다.

    `camera_set: "3cam"` 이 있으면 그 파일을 읽습니다.
    없으면 arms 블록에 직접 적힌 카메라 블록을 씁니다(예전 방식 호환).
    """
    name = arms_cfg.get("camera_set")
    if name:
        return load_camera_set(str(name))

    inline = {block: dict(arms_cfg.get(block) or {}) for block in BLOCKS}
    if not any(inline.values()):
        raise CameraConfigError(
            "robot.yaml 의 arms 에 camera_set 도, 카메라 블록도 없습니다.\n"
            f'camera_set: "{DEFAULT_SET}" 를 추가하세요.'
        )
    return inline


# =============================================================================
# 파생 정보
# =============================================================================
def camera_names(cams: dict) -> list[str]:
    """접두사가 붙은 최종 카메라 이름 (관측 키의 뒷부분)."""
    return [f"{prefix}{name}"
            for block, prefix in BLOCKS.items()
            for name in (cams.get(block) or {})]


def observation_keys(cams: dict) -> list[str]:
    """정책이 보는 이미지 관측 키. 녹화 때와 추론 때 이게 같아야 합니다."""
    return [f"observation.images.{name}" for name in camera_names(cams)]


def missing_devices(cams: dict) -> list[str]:
    """설정에 적혀 있지만 실제로 없는 장치 경로.

    숫자 인덱스(예: 0)는 경로가 아니라서 검사하지 않습니다.
    """
    missing = []
    for block in BLOCKS:
        for spec in (cams.get(block) or {}).values():
            device = str(spec["index_or_path"])
            if device.startswith("/") and not Path(device).exists():
                missing.append(device)
    return missing


def dataset_fps(cams: dict) -> int:
    """데이터셋 fps. lerobot 데이터셋은 fps 가 하나뿐이라 전부 같아야 합니다.

    카메라마다 fps 가 다르면 어느 쪽에 맞춰야 할지 알 수 없고, 조용히
    한쪽이 버려집니다. 그래서 다르면 바로 막습니다.
    """
    rates = {int(spec.get("fps", 30))
             for block in BLOCKS
             for spec in (cams.get(block) or {}).values()}
    if len(rates) > 1:
        raise CameraConfigError(
            f"카메라 fps 가 서로 다릅니다: {sorted(rates)}. "
            "데이터셋 fps 는 하나뿐이라 전부 같아야 합니다."
        )
    return rates.pop()


def _spec_json(spec: dict) -> str:
    return json.dumps({
        "type": spec.get("type", "opencv"),
        "index_or_path": spec["index_or_path"],
        "width": spec.get("width", 640),
        "height": spec.get("height", 480),
        "fps": spec.get("fps", 30),
    })


def record_args(cams: dict, layout: str = DEFAULT_LAYOUT) -> list[str]:
    """lerobot-record 에 넘길 `--robot...cameras=...` 인자들.

    layout 이 뭐든 최종 관측 키는 같습니다 — LAYOUTS 주석 참고.
    """
    if layout not in LAYOUTS:
        raise CameraConfigError(
            f"알 수 없는 레이아웃 {layout!r}. 쓸 수 있는 값: {', '.join(LAYOUTS)}"
        )

    if layout == "flat":
        # 접두사가 자동으로 안 붙으므로 최종 이름을 그대로 씁니다.
        body = ", ".join(
            f"{prefix}{name}: " + _spec_json(spec)
            for block, prefix in BLOCKS.items()
            for name, spec in (cams.get(block) or {}).items()
        )
        return [f"--robot.cameras={{ {body} }}"]

    # per_arm: 블록별로 인자를 나눠 넘기고 접두사는 lerobot 이 붙입니다.
    # 빈 블록은 인자를 아예 안 내보냅니다(생략 = 카메라 없음과 같음).
    arg_for = {
        "top_cameras": "--robot.cameras",
        "left_cameras": "--robot.left_arm_config.cameras",
        "right_cameras": "--robot.right_arm_config.cameras",
    }

    args = []
    for block, flag in arg_for.items():
        entries = cams.get(block) or {}
        if not entries:
            continue
        body = ", ".join(f"{name}: " + _spec_json(spec)
                         for name, spec in entries.items())
        args.append(f"{flag}={{ {body} }}")
    return args


def layout_for_robot(robot_type: str) -> str:
    """로봇 타입에 맞는 카메라 레이아웃. 모르는 타입은 기본값."""
    return ROBOT_LAYOUTS.get(robot_type, DEFAULT_LAYOUT)


def describe(cams: dict) -> str:
    """사람이 읽는 요약. 녹화 시작 전 확인용."""
    lines = []
    for block, prefix in BLOCKS.items():
        for name, spec in (cams.get(block) or {}).items():
            key = f"observation.images.{prefix}{name}"
            lines.append(
                f"  {key:<34} "
                f"{str(spec['index_or_path']):<14} "
                f"{spec.get('width', 640)}x{spec.get('height', 480)} "
                f"@{spec.get('fps', 30)}fps"
            )
    return "\n".join(lines)


# =============================================================================
# CLI — record.sh 가 이걸 호출합니다
# =============================================================================
def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    flags = {a.split("=", 1)[0] for a in argv if a.startswith("--")}
    values = dict(a[2:].split("=", 1) for a in argv
                  if a.startswith("--") and "=" in a)

    # 레이아웃은 직접 주거나(--layout=flat) 로봇 타입에서 유도합니다
    # (--robot-type=xlerobot). 둘 다 없으면 기본값.
    if "layout" in values:
        layout = values["layout"]
    elif "robot-type" in values:
        layout = layout_for_robot(values["robot-type"])
    else:
        layout = DEFAULT_LAYOUT

    if not args:
        print("쓸 수 있는 카메라 구성:")
        for name in list_camera_sets():
            cams = load_camera_set(name)
            print(f"\n  {name}  — 카메라 {len(camera_names(cams))}개")
            print(describe(cams))
        print(f"\n기본값: {DEFAULT_SET}")
        print("녹화:  CAMERA_SET=<이름> ./scripts/record.sh <라벨키> <개수>")
        return 0

    try:
        cams = load_camera_set(args[0])
    except CameraConfigError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1

    if "--record-args" in flags:
        # record.sh 가 한 줄씩 읽어서 배열에 담습니다.
        try:
            for arg in record_args(cams, layout):
                print(arg)
        except CameraConfigError as e:
            print(f"오류: {e}", file=sys.stderr)
            return 1
        return 0

    if "--fps" in flags:
        try:
            print(dataset_fps(cams))
        except CameraConfigError as e:
            print(f"오류: {e}", file=sys.stderr)
            return 1
        return 0

    if "--table" in flags:
        # 녹화 배너에 그대로 끼워 넣는 표. 머리글·꼬리글 없음.
        print(describe(cams))
        return 0

    if "--keys" in flags:
        for key in observation_keys(cams):
            print(key)
        return 0

    print(f"카메라 구성 {args[0]} — {len(camera_names(cams))}개")
    print(describe(cams))

    if "--check" in flags:
        missing = missing_devices(cams)
        if missing:
            print(f"\n없는 장치: {', '.join(missing)}", file=sys.stderr)
            print("lerobot-find-cameras 로 실제 인덱스를 확인하세요.", file=sys.stderr)
            return 1
        print("\n장치 전부 확인됨.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
