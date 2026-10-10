#!/usr/bin/env bash
# =============================================================================
# host.sh — 🍓 라즈베리파이에서 로봇 호스트를 띄웁니다 (녹화 전에 먼저).
# =============================================================================
#
#   FOLLOWER_LEFT_PORT=/dev/... FOLLOWER_RIGHT_PORT=/dev/... FOLLOWER_ID=... \
#     ./scripts/host.sh
#
#   CAMERA_SET=4cam ./scripts/host.sh      # PC 의 record.sh 와 같은 구성으로!
#
# 양팔 + 바퀴 3개(오른팔 버스, ID 7/8/9) + 카메라를 파이가 직접 열고,
# ZMQ 5555(명령) / 5556(관측) 으로 PC 의 bi_so_base_client 를 기다립니다.
#
# 카메라는 record.sh 와 같은 config/cameras.<이름>.yaml 을 읽습니다.
# PC 쪽은 이 이름으로 프레임을 받으므로, 이름이 어긋나면 검은 화면이 녹화됩니다.
# 그래서 두 스크립트 모두 yaml 만 보고, 장치 경로를 여기 적지 않습니다.
#
# ※ 파이에도 패치된 lerobot 0.6 이 깔려 있어야 합니다 (vendor/README.md).
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CAM_TOOL="$PROJECT_ROOT/src/camera_config.py"

CAMERA_SET="${CAMERA_SET:-3cam}"

# 팔로워 포트와 id 는 파이마다 다릅니다. 추측한 기본값으로 엉뚱한 팔을 열거나
# 캘리브레이션을 새로 만들지 않도록 일부러 기본값을 두지 않습니다.
# 캘리브레이션 파일: <FOLLOWER_ID>_left.json / <FOLLOWER_ID>_right.json
FOLLOWER_LEFT_PORT="${FOLLOWER_LEFT_PORT:?왼팔 팔로워 포트를 주세요. 예: FOLLOWER_LEFT_PORT=/dev/ttyACM0}"
FOLLOWER_RIGHT_PORT="${FOLLOWER_RIGHT_PORT:?오른팔(바퀴 포함) 포트를 주세요. 예: FOLLOWER_RIGHT_PORT=/dev/ttyACM1}"
FOLLOWER_ID="${FOLLOWER_ID:?캘리브레이션 id 를 주세요 (~/.cache/huggingface/lerobot/calibration/robots/ 확인)}"

# 카메라 장치는 여기(파이)에 있으니 여기서 확인합니다.
if ! python3 "$CAM_TOOL" "$CAMERA_SET" --check; then
  echo "카메라 구성 '$CAMERA_SET' 을 열 수 없습니다. 위 메시지를 보세요." >&2
  exit 1
fi

# 파이 쪽 로봇은 bi_so_follower 를 상속하므로 접두사를 lerobot 이 붙입니다 (per_arm).
mapfile -t CAM_ARGS < <(python3 "$CAM_TOOL" "$CAMERA_SET" --record-args --robot-type=bi_so_base_follower)

python -m lerobot.robots.bi_so_follower.bi_so_base_host \
  --robot.id="$FOLLOWER_ID" \
  --robot.left_arm_config.port="$FOLLOWER_LEFT_PORT" \
  --robot.right_arm_config.port="$FOLLOWER_RIGHT_PORT" \
  "${CAM_ARGS[@]}"
