#!/usr/bin/env bash
# =============================================================================
# record.sh — 💻 노트북에서 실행. 리더암으로 조종하면서 데모를 녹화합니다.
# =============================================================================
#
#   ./scripts/record.sh pick_red  40 --first    # 맨 처음 세션 (데이터셋 새로 만듦)
#   ./scripts/record.sh pick_blue 40            # 이어붙이기
#   ./scripts/record.sh place_red 40
#
# 먼저 Pi 에서 ./scripts/host.sh 가 떠 있어야 합니다.
# 포트·IP·카메라 설정은 scripts/xle_env.sh 에서 고치세요.
#
# 라벨 키:  pick_red  pick_blue  pick_yellow
#           place_red place_blue place_yellow
#
# 녹화 중 키 조작:
#   →     지금 에피소드 끝내고 다음으로
#   ←     방금 걸 다시 찍기   ← 색을 잘못 집었으면 무조건 이거
#   ESC   녹화 전체 중지
#   ijkl uo nm  베이스 주행 (조작 데모에선 쓰지 마세요, 아래 참고)
#
# ⚠️ 데이터셋 형식이 바뀌었습니다.
#   전: bi_so_follower  -> action/state 키가 left_shoulder_pan.pos ...
#   후: xlerobot_client -> left_arm_shoulder_pan.pos ... + x.vel/y.vel/theta.vel
#   예전에 찍은 데이터와는 **섞을 수 없습니다.** repo_id 를 새로 쓰세요.
#
# ⚠️ action 에 베이스 속도 3개가 들어갑니다. 조작 데모를 찍는 동안에는 주행 키를
#   누르지 마세요. 그러면 그 3개가 전부 정확히 0 으로 들어가서, 정책이
#   "조작 중엔 안 움직인다"를 깔끔하게 배웁니다. 중간에 조금씩 밀면 그 노이즈를
#   그대로 학습합니다.
# =============================================================================

set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/xle_env.sh"

# ------------------------------- 설정 ----------------------------------------
HF_USER="${HF_USER:?환경변수 HF_USER 를 먼저 설정하세요. 예: export HF_USER=songyeon}"
REPO_ID="${REPO_ID:-$HF_USER/xlerobot-dice}"

EPISODE_TIME_S="${EPISODE_TIME_S:-25}"   # 에피소드 하나 최대 길이(초)
RESET_TIME_S="${RESET_TIME_S:-15}"       # 다음 에피소드 전 준비 시간(초)
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
  로봇      : Pi($PI_IP) 의 host 에 접속  /  리더암은 이 노트북
==================================================================

  → 다음으로   ← 다시 찍기   ESC 중지

  · 파킹 자세에서 시작해서 파킹 자세로 끝내세요
  · 지시문과 다른 색을 집었으면 반드시 ← 로 다시
  · 40개 중 10개쯤은 로봇을 5~10cm 틀어서 찍으세요 (Nav2 오차 대비)
  · 주행 키(ijkl)는 누르지 마세요 — 베이스 명령은 0 으로 남겨둡니다

EOF
read -r -p "위 내용이 맞으면 Enter, 아니면 Ctrl+C: " _

# ------------------------------ 녹화 실행 -------------------------------------
# `--resume` 은 `--dataset.` 아래가 아니라 **최상위 옵션**입니다. 자주 틀리는 부분이에요.
exec lerobot-record \
  "${CLIENT_ROBOT_ARGS[@]}" \
  "${LEADER_TELEOP_ARGS[@]}" \
  --dataset.repo_id="$REPO_ID" \
  --dataset.single_task="$TASK" \
  --dataset.num_episodes="$EPISODES" \
  --dataset.episode_time_s="$EPISODE_TIME_S" \
  --dataset.reset_time_s="$RESET_TIME_S" \
  --dataset.fps="$FPS" \
  --resume="$RESUME" \
  --display_data=true
