#!/usr/bin/env bash
# =============================================================================
# host.sh — 🍓 라즈베리파이에서 로봇 호스트를 띄웁니다 (녹화 전에 먼저).
# =============================================================================
#
#   ./scripts/host.sh                      # 포트·id 는 config/robot.yaml 의 host 블록
#
#   CAMERA_SET=4cam ./scripts/host.sh      # PC 의 record.sh 와 같은 구성으로!
#
# 양팔 + 바퀴 3개(오른팔 버스, ID 7/8/9) + 카메라를 파이가 직접 열고,
# ZMQ 5555(명령) / 5556(관측) 으로 PC 의 bi_so_base_client 를 기다립니다.
#
# 녹화(record.sh)와 추론(arm_node.py) 둘 다 이 호스트에 붙습니다. 동시에는 하나만.
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

# 팔로워 포트와 id 는 config/robot.yaml 의 host 블록에서 읽습니다 (환경변수가 우선).
# 추측한 기본값으로 엉뚱한 팔을 열거나 캘리브레이션을 새로 만들지 않도록,
# 비어 있으면 멈춥니다. 캘리브레이션 파일: <id>_left.json / <id>_right.json
host_cfg() {
  python3 -c 'import sys, yaml
v = (yaml.safe_load(open(sys.argv[1], encoding="utf-8")).get("host") or {}).get(sys.argv[2])
print("" if v is None else v)' "$PROJECT_ROOT/config/robot.yaml" "$1"
}
FOLLOWER_LEFT_PORT="${FOLLOWER_LEFT_PORT:-$(host_cfg left_port)}"
FOLLOWER_RIGHT_PORT="${FOLLOWER_RIGHT_PORT:-$(host_cfg right_port)}"
FOLLOWER_ID="${FOLLOWER_ID:-$(host_cfg id)}"
for v in FOLLOWER_LEFT_PORT FOLLOWER_RIGHT_PORT FOLLOWER_ID; do
  if [ -z "${!v}" ]; then
    echo "$v 가 비어 있습니다. config/robot.yaml 의 host 블록을 채우거나 환경변수로 주세요." >&2
    exit 1
  fi
done

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
