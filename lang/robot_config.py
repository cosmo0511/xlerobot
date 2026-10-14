"""lang_infer / act_infer 가 로봇에 붙을 때 쓰는 설정을 레포 설정 파일에서 읽는다.

녹화(record.sh)·추론(arm_node.py)과 같은 곳에서 읽어야 카메라 이름이 안 어긋난다.

    카메라   config/cameras.<구성>.yaml   (--camera-set > CAMERA_SET > 정책에서 추정)
    파이 주소 PI_HOST > robot.yaml 의 arms.remote_ip
    로봇 id  robot.yaml 의 arms.id
"""

import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from camera_config import camera_kwargs, flat_cameras, list_camera_sets, load_camera_set  # noqa: E402


def arms_defaults() -> dict:
    """robot.yaml 의 arms 블록. 파일이 없으면 빈 dict."""
    try:
        cfg = yaml.safe_load((ROOT / "config" / "robot.yaml").read_text(encoding="utf-8"))
        return cfg.get("arms") or {}
    except FileNotFoundError:
        return {}


def default_remote_ip() -> str:
    return os.environ.get("PI_HOST") or arms_defaults().get("remote_ip") or "xlerobot2.local"


def default_robot_id() -> str:
    return arms_defaults().get("id") or "bi_so101"


def policy_image_names(policy_path: str) -> list[str]:
    """정책 config.json 에서 카메라 이름만 뽑는다 (observation.images.<이름>)."""
    p = Path(policy_path) / "config.json"
    if not p.exists():
        from huggingface_hub import hf_hub_download
        p = Path(hf_hub_download(policy_path, "config.json"))
    feats = json.loads(p.read_text())["input_features"]
    pre = "observation.images."
    return sorted(k[len(pre):] for k in feats if k.startswith(pre))


def build_cameras(args) -> tuple[str, dict]:
    """(구성 이름, {이름: OpenCVCameraConfig}). 정책이 기대하는 카메라와 다르면 멈춘다.

    --cameras(JSON) 를 직접 주면 그대로 쓴다 (예전 방식).
    """
    from lerobot.cameras.opencv import OpenCVCameraConfig

    want = policy_image_names(args.policy_path)

    if args.cameras:
        raw = {n: {k: v for k, v in c.items() if k != "type"}
               for n, c in json.loads(args.cameras).items()}
        set_name = "--cameras"
    else:
        set_name = args.camera_set or os.environ.get("CAMERA_SET")
        if not set_name:
            # 정책이 기대하는 카메라와 이름이 똑같은 구성을 찾는다
            for name in list_camera_sets():
                try:
                    names = sorted(flat_cameras(load_camera_set(name)))
                except Exception:
                    continue
                if names == want:
                    set_name = name
                    break
            else:
                raise RuntimeError(
                    f"정책 카메라 {want} 와 맞는 config/cameras.*.yaml 이 없습니다. "
                    f"--camera-set 으로 지정하세요.")
        raw = {n: camera_kwargs(c) for n, c in flat_cameras(load_camera_set(set_name)).items()}

    if sorted(raw) != want:
        raise RuntimeError(
            f"카메라 이름이 정책과 다릅니다. 정책 {want} / '{set_name}' {sorted(raw)}. "
            f"파이 host.sh 와 같은 CAMERA_SET 을 쓰세요.")
    return set_name, {n: OpenCVCameraConfig(**c) for n, c in raw.items()}


def diag_row(robot, C: dict) -> str:
    """파이 호스트가 관측에 실어 보내는 상태(_diag)를 한 줄로. 경고 기준은 호스트와 같다."""
    d = getattr(robot, "last_diag", None) or {}
    if not d:
        return f"  파이   {C['dim']}상태 정보 없음 (호스트가 옛 버전이거나 아직 첫 측정 전){C['r']}"
    warn = (d.get("pi_temp_c", 0) >= 75 or d.get("pi_throttled", "0") not in ("0", "0x0")
            or d.get("servo_temp_max_c", 0) >= 60 or "servo_error" in d)
    col = C["w"] if warn else C["dim"]
    servo = (f"서보 최고 {d['servo_temp_max_c']:.0f}°C ({d['servo_temp_max_name']}) "
             f"최저 {d['servo_volt_min_v']}V" if "servo_temp_max_c" in d
             else f"서보 읽기 실패 {d.get('servo_error', '')}")
    return (f"  파이   {col}CPU {d.get('pi_temp_c', '?')}°C  스로틀 {d.get('pi_throttled', '?')}  "
            f"{servo}  관측 {d.get('obs_hz', '?')}Hz{C['r']}")
