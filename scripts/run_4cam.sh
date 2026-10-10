#!/usr/bin/env bash
# =============================================================================
# run_4cam.sh — 4캠(탑 + 베이스 + 손목 x2) 구성 전용 진입점.
# =============================================================================
#
# CAMERA_SET=4cam 을 **한 곳에서** 박아서 내보냅니다. 파이와 PC 의 구성이
# 어긋나는 걸 막는 게 이 스크립트의 존재 이유입니다 — 어긋나면 파이가 안 보낸
# 카메라 칸이 **검은 화면으로 조용히 녹화됩니다** (bi_so_base_client 가 못 받은
# 카메라를 np.zeros 로 채웁니다. 경고 한 줄만 찍고 넘어갑니다).
# 그걸 96 에피소드 찍은 뒤에 알면 전부 다시 찍어야 합니다.
#
# 순서대로 하세요:
#
#   🍓 파이에서 (처음 한 번, 카메라 자리 정하기)
#     ./scripts/run_4cam.sh scan        어떤 /dev/video* 가 카메라인지 + yaml 블록
#     ./scripts/run_4cam.sh identify    장치마다 한 장 찍어 저장 -> 보고 이름 배정
#     ./scripts/run_4cam.sh selftest    4대가 **동시에** 열리는지 + 실측 fps
#
#   🍓 파이에서 (매번)
#     ./scripts/run_4cam.sh host        호스트 띄우기
#
#   💻 PC 에서 (매번, 녹화 전)
#     ./scripts/run_4cam.sh check       녹화와 같은 경로로 검증
#     ./scripts/run_4cam.sh teleop      팔·바퀴 움직여보기 (데이터 안 남음)
#     ./scripts/run_4cam.sh record red 8 --first
#
#   💻 PC 에서 (아무 때나)
#     ./scripts/run_4cam.sh status      몇 개 찍었나
#     ./scripts/run_4cam.sh droplast    마지막 에피소드 지우기 (ESC 로 생긴 토막)
#
#   💻 PC 에서 (학습 끝난 뒤)
#     ./scripts/run_4cam.sh infer       추론 (robot.yaml 을 안 고쳐도 4cam)
#
# record 는 check 를 **먼저 돌리고, 통과해야** 녹화를 시작합니다.
# 정말 건너뛰어야 하면 SKIP_CHECK=1 을 주세요 (권하지 않습니다).
#
# 중간에 끊었다가 이어 찍는 건 그냥 같은 명령을 다시 치면 됩니다 (--first 없이).
# 깔끔하게 멈추려면 → 로 에피소드를 끝내고 **리셋 시간에** ESC 를 누르세요.
# 에피소드 도중 ESC 는 토막을 저장합니다 -> droplast 로 지우세요.
#
# 카메라 목록은 여기 안 적습니다 — config/cameras.4cam.yaml 에만 있습니다.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 이 스크립트의 요점. 하위 스크립트(host.sh / record.sh)와 arm_node.py 가 이걸 읽습니다.
export CAMERA_SET=4cam

PREFLIGHT="$PROJECT_ROOT/src/preflight_cameras.py"

# lerobot venv 의 python (cv2 / lerobot 이 필요한 것들). venv 를 활성화해서
# 쓰는 게 기본이고, 안 했으면 PYTHON= 으로 직접 줄 수 있습니다.
PY="${PYTHON:-python}"
# 장치 목록만 보는 건 표준 라이브러리 + pyyaml 로 됩니다 (venv 없이도).
PY3="${PYTHON3:-python3}"

# 사용법은 위 머리말 주석 하나만 유지합니다 (두 군데 적으면 한쪽이 낡습니다).
# 셔뱅 다음부터 주석이 끝나는 줄까지 찍고, 앞의 '# ' 를 떼고, 구분선은 버립니다.
usage() {
  awk 'NR>1 && /^#/ {sub(/^# ?/, ""); if ($0 !~ /^=+$/) print; next} NR>1 {exit}' \
    "${BASH_SOURCE[0]}"
  exit 1
}

cmd="${1:-}"
shift || true

case "$cmd" in

  # --- 🍓 파이: 장치 찾기 ----------------------------------------------------
  scan)
    exec "$PY3" "$PREFLIGHT" --list --emit-yaml "$@"
    ;;

  identify)
    echo "장치마다 한 장씩 찍습니다. host.sh 가 떠 있으면 장치를 못 엽니다 — 먼저 끄세요."
    exec "$PY" "$PREFLIGHT" --identify "$@"
    ;;

  selftest)
    # 파이에서 장치를 직접, 4대 동시에 엽니다. host.sh 와 같은 장치를 쓰므로
    # 호스트가 떠 있으면 실패합니다.
    echo "4대를 동시에 엽니다. host.sh 가 떠 있으면 먼저 끄세요."
    exec "$PY" "$PREFLIGHT" 4cam --local "$@"
    ;;

  # --- 🍓 파이: 호스트 -------------------------------------------------------
  host)
    echo "CAMERA_SET=$CAMERA_SET 로 호스트를 띄웁니다."
    echo "PC 쪽도 반드시 같은 구성으로 띄우세요 (./scripts/run_4cam.sh check)."
    exec "$SCRIPT_DIR/host.sh" "$@"
    ;;

  # --- 💻 PC: 검증 -----------------------------------------------------------
  check)
    exec "$PY" "$PREFLIGHT" 4cam "$@"
    ;;

  # --- 💻 PC: 연습 (데이터 안 남음) ------------------------------------------
  teleop)
    # 녹화와 **같은 로봇·같은 텔레옵·같은 키**로 움직여만 봅니다. 데이터는 안 남습니다.
    # 키를 안 넘기면 lerobot 기본값(회전 q/e, 속도 r/f)으로 돌아서 손에 익은 게
    # 틀어집니다. 그래서 record.sh 와 같은 파일에서 가져옵니다.
    # shellcheck source=scripts/teleop_keys.sh
    source "$SCRIPT_DIR/teleop_keys.sh"
    PI_HOST="${PI_HOST:-xlerobot2.local}"
    # 카메라도 녹화와 같은 yaml 에서 넘깁니다. 빠지면 클라이언트가 카메라 없는
    # 로봇으로 떠서 화면(--display_data)에 관절 값만 나옵니다.
    mapfile -t CAM_ARGS < <(python3 "$PROJECT_ROOT/src/camera_config.py" "$CAMERA_SET" \
      --record-args --robot-type=bi_so_base_client)
    echo "파이($PI_HOST)의 host.sh 가 떠 있어야 합니다. 카메라는 rerun 창에 뜹니다."
    echo
    echo "  g        바퀴 잠금 해제/잠금 — **시작은 잠김**입니다. 한 번 눌러야 움직입니다"
    echo "  w/s/a/d  앞/뒤/좌/우      z/x 회전      c/v 속도      t 종료"
    echo
    exec lerobot-teleoperate \
      --robot.type=bi_so_base_client \
      --robot.remote_ip="$PI_HOST" \
      --robot.id=bi_so101 \
      "${CAM_ARGS[@]}" \
      --teleop.type=bi_so_base_leader \
      --teleop.id=bi_so101_leader \
      --teleop.left_arm_config.port=/dev/so101_leader_left \
      --teleop.right_arm_config.port=/dev/so101_leader_right \
      --teleop.teleop_keys="$TELEOP_KEYS" \
      --display_data=true \
      "$@"
    ;;

  # --- 💻 PC: 녹화 -----------------------------------------------------------
  record)
    if [ "${SKIP_CHECK:-0}" = "1" ]; then
      echo "⚠ SKIP_CHECK=1 — 카메라 검증을 건너뜁니다. 검은 화면이 녹화돼도 모릅니다."
    else
      echo "녹화 전 카메라 검증 ..."
      if ! "$PY" "$PREFLIGHT" 4cam; then
        echo >&2
        echo "✗ 카메라 검증 실패 — 녹화를 시작하지 않습니다." >&2
        echo "  위에 적힌 걸 고치고 다시 하세요. 녹화는 되돌릴 수 없습니다." >&2
        exit 1
      fi
      echo
    fi
    exec "$SCRIPT_DIR/record.sh" "$@"
    ;;

  # --- 💻 PC: 추론 -----------------------------------------------------------
  infer)
    # arm_node.py 는 robot.yaml 의 camera_set 을 읽지만, CAMERA_SET 이 있으면
    # 그게 이깁니다 (경고를 찍습니다). robot.yaml 을 고치지 않아도 됩니다.
    echo "CAMERA_SET=$CAMERA_SET 로 추론 노드를 띄웁니다."
    echo "⚠ 정책이 4cam 데이터로 학습된 것이어야 합니다. 3cam 정책에 4cam 을 주면"
    echo "  관측 키가 안 맞아 팔이 아예 안 움직입니다."
    exec "$PY" "$PROJECT_ROOT/src/arm_node.py" "$@"
    ;;

  # --- 💻 PC: 진행 상황 / 토막 정리 -----------------------------------------
  status)
    # shellcheck source=scripts/dataset_path.sh
    source "$SCRIPT_DIR/dataset_path.sh"
    echo "데이터셋 : $REPO_ID"
    echo "폴더     : $DATASET_ROOT"
    echo "에피소드 : $DONE 개"
    if [ "$DONE" = "0" ]; then
      echo
      echo "아직 없습니다. 처음이면:  ./scripts/run_4cam.sh record red 8 --first"
    else
      echo
      echo "이어 찍기 :  ./scripts/run_4cam.sh record red 8"
      echo "눈으로 확인:  lerobot-dataset-viz --repo-id=$REPO_ID --root=$DATASET_ROOT"
      echo "손실 검사 :  python src/check_dataset.py $REPO_ID"
    fi
    ;;

  droplast)
    # 에피소드 도중 ESC 를 누르면 토막이 저장됩니다. 그걸 지우는 용도입니다.
    # shellcheck source=scripts/dataset_path.sh
    source "$SCRIPT_DIR/dataset_path.sh"
    if [ "$DONE" = "0" ]; then
      echo "지울 에피소드가 없습니다 ($DATASET_ROOT)" >&2
      exit 1
    fi
    LAST=$((DONE - 1))
    echo "마지막 에피소드 #$LAST 를 지웁니다 (전체 $DONE 개 -> $LAST 개)."
    echo "폴더: $DATASET_ROOT"
    echo "되돌릴 수 없습니다."
    read -r -p "지우려면 yes 를 입력하세요: " answer
    if [ "$answer" != "yes" ]; then
      echo "취소했습니다."
      exit 1
    fi
    exec lerobot-edit-dataset \
      --repo_id "$REPO_ID" \
      --root "$DATASET_ROOT" \
      --operation.type delete_episodes \
      --operation.episode_indices "[$LAST]"
    ;;

  view)
    # 그림을 직접 보고 싶을 때 (rerun 창). 검증은 check 가 합니다.
    exec "$PY" "$PROJECT_ROOT/src/view_cameras.py" 4cam "$@"
    ;;

  ""|-h|--help|help) usage ;;
  *)
    echo "모르는 명령: $cmd" >&2
    echo >&2
    usage
    ;;
esac
