"""
robot.yaml 의 travel_pose(= park 자세)를 데이터셋 첫 프레임 중앙값으로 바꿉니다.
주석은 그대로 두고 값만 바꿉니다. 원본은 config/robot.yaml.bak 으로 백업.

    cd ~/xlerobot
    python3 set_travel_pose.py
"""

import re
import shutil
from pathlib import Path

# bilimili/xlerobot-dice-4cam, 96 에피소드 첫 프레임 중앙값
POSE = {
    "left_shoulder_pan.pos": -9.1,
    "left_shoulder_lift.pos": -100.3,
    "left_elbow_flex.pos": 99.0,
    "left_wrist_flex.pos": 69.6,
    "left_wrist_roll.pos": 0.7,
    "left_gripper.pos": 3.9,
    "right_shoulder_pan.pos": -8.7,
    "right_shoulder_lift.pos": -101.4,
    "right_elbow_flex.pos": 95.5,
    "right_wrist_flex.pos": 68.7,
    "right_wrist_roll.pos": -4.4,
    "right_gripper.pos": 2.6,
}

path = Path("config/robot.yaml")
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

# travel_pose: 블록 찾기
start = next((i for i, l in enumerate(lines) if re.match(r"^\s*travel_pose:\s*(#.*)?$", l)), None)
if start is None:
    raise SystemExit("✗ robot.yaml 에 travel_pose: 가 없습니다. 아무것도 안 바꿉니다.")
base_indent = len(lines[start]) - len(lines[start].lstrip())

done = set()
i = start + 1
while i < len(lines):
    l = lines[i]
    if l.strip() and not l.lstrip().startswith("#"):
        indent = len(l) - len(l.lstrip())
        if indent <= base_indent:
            break  # 블록 끝
        m = re.match(r'^(\s*)("?)([\w.]+)("?)(\s*:\s*)([-\d.]+)(.*)$', l.rstrip("\n"))
        if m and m.group(3) in POSE:
            key = m.group(3)
            lines[i] = f"{m.group(1)}{m.group(2)}{key}{m.group(4)}{m.group(5)}{POSE[key]}{m.group(7)}\n"
            done.add(key)
    i += 1

missing = [k for k in POSE if k not in done]
if missing:
    raise SystemExit(f"✗ travel_pose 에서 못 찾은 관절: {missing}. 아무것도 안 바꿉니다.")

shutil.copy(path, path.with_suffix(".yaml.bak"))
path.write_text("".join(lines), encoding="utf-8")
print("✓ travel_pose 를 데이터셋 시작 자세로 바꿨습니다 (원본: config/robot.yaml.bak)")
print("".join(lines[start:i]))
