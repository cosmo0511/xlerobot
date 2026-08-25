#!/usr/bin/env bash
# =============================================================================
# record.sh — 🦾 Pi-A 에서 데모를 녹화합니다.
# =============================================================================
#
#   ./scripts/record.sh pick_red  40 --first    # 맨 처음 세션 (데이터셋 새로 만듦)
#   ./scripts/record.sh pick_blue 40            # 이어붙이기
#   ./scripts/record.sh place_red 40
#
# 라벨 키:  pick_red  pick_blue  pick_yellow
#           place_red place_blue place_yellow
#
# 녹화 중 키 조작:
#   →     지금 에피소드 끝내고 다음으로
#   ←     방금 걸 다시 찍기   ← 색을 잘못 집었으면 무조건 이거
#   ESC   녹화 전체 중지
#
# ※ 아래 "설정" 부분만 실제 환경에 맞게 고치고, 그 뒤로는 건드리지 마세요.
#   특히 카메라 이름(top / wrist)은 6개 세션 내내 똑같아야 합니다.
# =============================================================================

set -euo pipefail

# ------------------------------- 설정 ----------------------------------------
HF_USER="${HF_USER:?환경변수 HF_USER 를 먼저 설정하세요. 예: export HF_USER=songyeon}"
REPO_ID="$HF_USER/xlerobot-dice"

# 팔로워 팔 (로봇에 붙어 실제로 움직이는 쪽)
FOLLOWER_LEFT_PORT="/dev/ttyACM0"
FOLLOWER_RIGHT_PORT="/dev/ttyACM1"
FOLLOWER_ID="home_bi"

# 리더 팔 (사람이 손으로 잡고 조종하는 쪽)
LEADER_LEFT_PORT="/dev/ttyACM2"
LEADER_RIGHT_PORT="/dev/ttyACM3"
LEADER_ID="home_bi_leader"

# 카메라 3개. 이름은 절대 바꾸지 마세요.
#   top   -> observation.images.top
#   wrist -> observation.images.left_wrist / right_wrist  (접두사 자동)
CAM_TOP="/dev/video0"
CAM_LEFT_WRIST="/dev/video2"
CAM_RIGHT_WRIST="/dev/video4"
CAM_W=640
CAM_H=480
CAM_FPS=30

EPISODE_TIME_S=25      # 에피소드 하나 최대 길이(초)
RESET_TIME_S=15        # 다음 에피소드 전 준비 시간(초)
# -----------------------------------------------------------------------------

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
==================================================================

  → 다음으로   ← 다시 찍기   ESC 중지

  · 파킹 자세에서 시작해서 파킹 자세로 끝내세요
  · 지시문과 다른 색을 집었으면 반드시 ← 로 다시
  · 40개 중 10개쯤은 로봇을 5~10cm 틀어서 찍으세요 (Nav2 오차 대비)

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
  --robot.cameras="{ top: {\"type\":\"opencv\",\"index_or_path\":\"$CAM_TOP\",\"width\":$CAM_W,\"height\":$CAM_H,\"fps\":$CAM_FPS} }" \
  --robot.left_arm_config.cameras="{ wrist: {\"type\":\"opencv\",\"index_or_path\":\"$CAM_LEFT_WRIST\",\"width\":$CAM_W,\"height\":$CAM_H,\"fps\":$CAM_FPS} }" \
  --robot.right_arm_config.cameras="{ wrist: {\"type\":\"opencv\",\"index_or_path\":\"$CAM_RIGHT_WRIST\",\"width\":$CAM_W,\"height\":$CAM_H,\"fps\":$CAM_FPS} }" \
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
echo "완료: \"$TASK\" $EPISODES 개"
echo "확인: lerobot-dataset-viz --repo-id=$REPO_ID"
