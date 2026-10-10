#!/usr/bin/env bash
# =============================================================================
# record.sh — 💻 PC 에서 데모를 녹화합니다 (양팔 + 바퀴 주행까지).
# =============================================================================
#
# 먼저 라즈베리파이에서 호스트를 띄워 두세요:   ./scripts/host.sh
# (로봇·카메라는 파이에 USB 로 붙어 있고, PC 는 무선으로 붙습니다.)
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
# 바퀴 (키보드, 리더암과 같이 씀):
#   g      바퀴 잠금/해제 토글 — **시작은 잠김 상태**입니다. 한 번 눌러야 움직입니다.
#   w/s    앞/뒤     a/d  좌/우 평행이동     z/x  좌/우 회전
#   c/v    속도 올림/내림
#
# 녹화되는 액션 (15차원) — 바퀴가 들어가야 정책이 주행까지 배웁니다:
#   left_*.pos (6) + right_*.pos (6) + x.vel, y.vel, theta.vel (3)
#
# 로봇 클래스는 우리가 lerobot 0.6 에 직접 붙인 것입니다 (vendor/README.md).
#   PC   --robot.type=bi_so_base_client   --teleop.type=bi_so_base_leader
#   파이  bi_so_base_host (bi_so_base_follower)
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

# 라즈베리파이 (bi_so_base_host 가 떠 있는 쪽). IP 로 줘도 됩니다.
PI_HOST="${PI_HOST:-xlerobot2.local}"
ROBOT_TYPE="bi_so_base_client"
ROBOT_ID="bi_so101"

# 리더 팔 (PC 에 USB 로 꽂음, udev 심볼릭 링크)
LEADER_LEFT_PORT="/dev/so101_leader_left"
LEADER_RIGHT_PORT="/dev/so101_leader_right"
# 캘리브레이션 파일 이름이 여기서 나옵니다: <ID>_left.json / <ID>_right.json
# (~/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/)
# 바꾸면 캘리브레이션을 다시 하라고 나옵니다.
LEADER_ID="bi_so101_leader"

# 바퀴 키. 실제로 쓰던 배치 그대로입니다 (기본값의 q/e 회전 대신 z/x).
TELEOP_KEYS='{"forward":"w","backward":"s","left":"a","right":"d","rotate_left":"z","rotate_right":"x","speed_up":"c","speed_down":"v","quit":"t"}'

EPISODE_TIME_S=25      # 에피소드 하나 최대 길이(초)
RESET_TIME_S=15        # 다음 에피소드 전 준비 시간(초)
# -----------------------------------------------------------------------------

CAM_TOOL="$PROJECT_ROOT/src/camera_config.py"

# 카메라 설정을 읽습니다. 장치는 **파이에** 있으므로 여기서는 장치 확인을
# 하지 않습니다 — host.sh 가 파이에서 --check 로 확인합니다. 여기서는 구성
# 파일이 제대로 읽히는지만 봅니다.
if ! python3 "$CAM_TOOL" "$CAMERA_SET" >/dev/null; then
  echo "카메라 구성 '$CAMERA_SET' 을 쓸 수 없습니다. 위 메시지를 보세요." >&2
  exit 1
fi

CAM_SUMMARY="$(python3 "$CAM_TOOL" "$CAMERA_SET" --table)"
CAM_FPS="$(python3 "$CAM_TOOL" "$CAMERA_SET" --fps)"
# 클라이언트는 카메라를 열지 않고, 파이가 보낸 프레임을 이 이름으로 받습니다.
# 그래서 최종 이름(top, left_wrist ...)을 그대로 넘기는 flat 레이아웃입니다.
# 파이(host.sh)도 같은 yaml 을 읽으므로 이름이 어긋나지 않습니다.
mapfile -t CAM_ARGS < <(python3 "$CAM_TOOL" "$CAMERA_SET" --record-args --robot-type="$ROBOT_TYPE")

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

  파이      : $PI_HOST   (host.sh 를 같은 CAMERA_SET 으로 띄웠나요?)
  카메라 구성: $CAMERA_SET   (fps $CAM_FPS)
$CAM_SUMMARY
==================================================================

  → 다음으로   ← 다시 찍기   ESC 중지
  g 바퀴 잠금 해제/잠금   w/s/a/d 이동   z/x 회전   c/v 속도

  · 파킹 자세에서 시작해서 파킹 자세로 끝내세요
  · 지시문과 다른 색을 집었으면 반드시 ← 로 다시
  · 40개 중 10개쯤은 로봇을 5~10cm 틀어서 찍으세요 (Nav2 오차 대비)
  · 위 관측 키가 **이전 세션과 같은지** 확인하세요. 다르면 섞이면 안 됩니다.

EOF
read -r -p "위 내용이 맞으면 Enter, 아니면 Ctrl+C: " _

# ------------------------------ 녹화 실행 -------------------------------------
lerobot-record \
  --robot.type="$ROBOT_TYPE" \
  --robot.remote_ip="$PI_HOST" \
  --robot.id="$ROBOT_ID" \
  "${CAM_ARGS[@]}" \
  --teleop.type=bi_so_base_leader \
  --teleop.id="$LEADER_ID" \
  --teleop.left_arm_config.port="$LEADER_LEFT_PORT" \
  --teleop.right_arm_config.port="$LEADER_RIGHT_PORT" \
  --teleop.teleop_keys="$TELEOP_KEYS" \
  --dataset.repo_id="$REPO_ID" \
  --dataset.single_task="$TASK" \
  --dataset.num_episodes="$EPISODES" \
  --dataset.episode_time_s="$EPISODE_TIME_S" \
  --dataset.reset_time_s="$RESET_TIME_S" \
  --dataset.fps="$CAM_FPS" \
  --dataset.streaming_encoding=true \
  --dataset.encoder_threads=4 \
  --resume="$RESUME" \
  --display_data=true

echo
echo "완료: \"$TASK\" $EPISODES 개  (구성 $CAMERA_SET)"
echo "확인: lerobot-dataset-viz --repo-id=$REPO_ID"
