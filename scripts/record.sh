#!/usr/bin/env bash
# =============================================================================
# record.sh — 🦾 Pi-A 에서 데모를 녹화합니다.
# =============================================================================
#
#   ./scripts/record.sh pick_red  40 --first    # 맨 처음 세션 (데이터셋 새로 만듦)
#   ./scripts/record.sh pick_blue 40            # 이어붙이기
#   ./scripts/record.sh place_red 40
#
# 카메라 구성을 바꿔서 찍으려면 (기본값 3cam):
#
#   CAMERA_SET=4cam ./scripts/record.sh pick_red 40 --first
#
#   구성 목록:  python src/camera_config.py
#   구성 파일:  config/cameras.<이름>.yaml
#
#   ※ 구성마다 데이터셋이 따로 만들어집니다 (xlerobot-dice-3cam / -4cam).
#     카메라 구성이 다른 데이터를 한 데이터셋에 섞으면 관측 키가 안 맞아
#     데이터셋이 깨집니다. 그래서 이름에 구성을 넣어 자동으로 분리합니다.
#
# 라벨 키:  pick_red  pick_blue  pick_yellow
#           place_red place_blue place_yellow
#
# 녹화 중 키 조작:
#   →     지금 에피소드 끝내고 다음으로
#   ←     방금 걸 다시 찍기   ← 색을 잘못 집었으면 무조건 이거
#   ESC   녹화 전체 중지
#
# ※ 카메라는 이제 여기 안 적습니다. config/cameras.<이름>.yaml 에만 있고
#   추론(src/arm_node.py)도 같은 파일을 읽습니다. 그래서 "녹화 때와 추론 때
#   카메라 이름이 달라서 팔이 안 움직이는" 문제가 구조적으로 안 생깁니다.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# ------------------------------- 설정 ----------------------------------------
HF_USER="${HF_USER:?환경변수 HF_USER 를 먼저 설정하세요. 예: export HF_USER=songyeon}"

# 카메라 구성. config/cameras.<이름>.yaml 이 있어야 합니다.
CAMERA_SET="${CAMERA_SET:-3cam}"

# 데이터셋 이름에 카메라 구성을 붙여서 섞이지 않게 합니다.
REPO_ID="${REPO_ID:-$HF_USER/xlerobot-dice-$CAMERA_SET}"

# 팔로워 팔 (로봇에 붙어 실제로 움직이는 쪽)
FOLLOWER_LEFT_PORT="/dev/ttyACM0"
FOLLOWER_RIGHT_PORT="/dev/ttyACM1"
FOLLOWER_ID="home_bi"

# 리더 팔 (사람이 손으로 잡고 조종하는 쪽)
LEADER_LEFT_PORT="/dev/ttyACM2"
LEADER_RIGHT_PORT="/dev/ttyACM3"
LEADER_ID="home_bi_leader"

EPISODE_TIME_S=25      # 에피소드 하나 최대 길이(초)
RESET_TIME_S=15        # 다음 에피소드 전 준비 시간(초)
# -----------------------------------------------------------------------------

CAM_TOOL="$PROJECT_ROOT/src/camera_config.py"

# 카메라 설정을 읽습니다. 장치가 없으면 여기서 멈춥니다 — 40개를 찍고 나서
# 한 카메라가 검은 화면이었다는 걸 알면 그 세션은 전부 버려야 합니다.
if ! python3 "$CAM_TOOL" "$CAMERA_SET" --check >/dev/null; then
  echo "카메라 구성 '$CAMERA_SET' 을 쓸 수 없습니다. 위 메시지를 보세요." >&2
  exit 1
fi

CAM_SUMMARY="$(python3 "$CAM_TOOL" "$CAMERA_SET" --table)"
CAM_FPS="$(python3 "$CAM_TOOL" "$CAMERA_SET" --fps)"
mapfile -t CAM_ARGS < <(python3 "$CAM_TOOL" "$CAMERA_SET" --record-args)

# 라벨 키 -> 실제 학습 라벨 문자열
# ※ config/tasks.yaml 의 prompt 와 **글자까지 동일**해야 합니다.
#   `python src/task_registry.py` 출력과 대조해서 쓰세요.
label_for() {
  case "$1" in
    pick_red)     echo "Pick up the red dice" ;;
    pick_blue)    echo "Pick up the blue dice" ;;
    pick_yellow)  echo "Pick up the yellow dice" ;;
    place_red)    echo "Place the dice on the red spot" ;;
    place_blue)   echo "Place the dice on the blue spot" ;;
    place_yellow) echo "Place the dice on the yellow spot" ;;
    *) return 1 ;;
  esac
}

# 어느 책상에서 찍는 세션인지 (안내 메시지용)
desk_for() {
  case "$1" in
    pick_*)  echo "1번 책상 — 주사위 3개를 다 놓고, 매 에피소드 자리를 섞으세요" ;;
    place_*) echo "2번 책상 — 색깔 자리 3개를 다 보이게, 주사위는 그리퍼에 쥐여준 채 시작" ;;
  esac
}

# ------------------------------ 인자 처리 -------------------------------------
KEY="${1:-}"
EPISODES="${2:-40}"
FIRST="${3:-}"

if [ -z "$KEY" ] || ! TASK="$(label_for "$KEY")"; then
  echo "사용법: $0 <라벨키> [에피소드수] [--first]"
  echo
  echo "라벨키:"
  for k in pick_red pick_blue pick_yellow place_red place_blue place_yellow; do
    printf "  %-13s %s\n" "$k" "$(label_for "$k")"
  done
  echo
  echo "예: $0 pick_red 40 --first"
  echo "    CAMERA_SET=4cam $0 pick_red 40 --first"
  exit 1
fi

# 첫 세션만 resume=false. 나머지는 같은 데이터셋에 이어붙입니다.
if [ "$FIRST" = "--first" ]; then
  RESUME="false"
else
  RESUME="true"
fi

cat <<EOF

==================================================================
  라벨      : "$TASK"
  데이터셋  : $REPO_ID
  에피소드  : $EPISODES 개   (이어붙이기: $RESUME)
  자리      : $(desk_for "$KEY")

  카메라 구성: $CAMERA_SET   (fps $CAM_FPS)
$CAM_SUMMARY
==================================================================

  → 다음으로   ← 다시 찍기   ESC 중지

  · 파킹 자세에서 시작해서 파킹 자세로 끝내세요
  · 지시문과 다른 색을 집었으면 반드시 ← 로 다시
  · 40개 중 10개쯤은 로봇을 5~10cm 틀어서 찍으세요 (Nav2 오차 대비)
  · 위 관측 키가 **이전 세션과 같은지** 확인하세요. 다르면 섞이면 안 됩니다.

EOF
read -r -p "위 내용이 맞으면 Enter, 아니면 Ctrl+C: " _

# ------------------------------ 녹화 실행 -------------------------------------
lerobot-record \
  --robot.type=bi_so_follower \
  --robot.id="$FOLLOWER_ID" \
  --robot.left_arm_config.port="$FOLLOWER_LEFT_PORT" \
  --robot.left_arm_config.id="${FOLLOWER_ID}_left" \
  --robot.right_arm_config.port="$FOLLOWER_RIGHT_PORT" \
  --robot.right_arm_config.id="${FOLLOWER_ID}_right" \
  "${CAM_ARGS[@]}" \
  --teleop.type=bi_so_leader \
  --teleop.id="$LEADER_ID" \
  --teleop.left_arm_config.port="$LEADER_LEFT_PORT" \
  --teleop.left_arm_config.id="${LEADER_ID}_left" \
  --teleop.right_arm_config.port="$LEADER_RIGHT_PORT" \
  --teleop.right_arm_config.id="${LEADER_ID}_right" \
  --dataset.repo_id="$REPO_ID" \
  --dataset.single_task="$TASK" \
  --dataset.num_episodes="$EPISODES" \
  --dataset.episode_time_s="$EPISODE_TIME_S" \
  --dataset.reset_time_s="$RESET_TIME_S" \
  --dataset.fps="$CAM_FPS" \
  --resume="$RESUME" \
  --display_data=true

echo
echo "완료: \"$TASK\" $EPISODES 개  (구성 $CAMERA_SET)"
echo "확인: lerobot-dataset-viz --repo-id=$REPO_ID"
