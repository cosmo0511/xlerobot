#!/usr/bin/env bash
# =============================================================================
# teleop.sh — 💻 노트북에서 실행. 리더암 2개로 Pi 의 팔을 조종합니다.
# =============================================================================
#
#   ./scripts/teleop.sh              # 화면에 카메라 3개 띄우고 조종
#   ./scripts/teleop.sh --no-display # 느릴 때. rerun 끄기
#
# 먼저 Pi 에서 ./scripts/host.sh 가 떠 있어야 합니다.
#
# 손 조작:
#   리더암 왼쪽/오른쪽  -> 팔로워 왼팔/오른팔
#   i k j l             -> 베이스 전/후/좌/우
#   u o                 -> 베이스 제자리 회전
#   n m                 -> 베이스 속도 단계 올리기/내리기
#
# ⚠️ 처음 한 번은 리더암 캘리브레이션이 필요합니다 (노트북에서):
#
#     ./scripts/teleop.sh --calibrate
# =============================================================================

set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/xle_env.sh"

if [ "${1:-}" = "--calibrate" ]; then
  cat <<EOF

==================================================================
  리더암 캘리브레이션 (노트북에 꽂힌 두 팔)
  저장 위치: ~/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/
             ${LEADER_ID}_left.json, ${LEADER_ID}_right.json
==================================================================
  왼쪽 리더암 : $LEADER_LEFT_PORT
  오른쪽      : $LEADER_RIGHT_PORT

EOF
  # bi_so_leader 로 캘리브레이션해도 파일 이름이 같아서 그대로 재사용됩니다.
  exec lerobot-calibrate \
    --teleop.type=bi_so_leader \
    --teleop.id="$LEADER_ID" \
    --teleop.left_arm_config.port="$LEADER_LEFT_PORT" \
    --teleop.right_arm_config.port="$LEADER_RIGHT_PORT"
fi

DISPLAY_DATA=true
[ "${1:-}" = "--no-display" ] && DISPLAY_DATA=false

cat <<EOF

==================================================================
  텔레옵 — 노트북 리더암 -> Pi($PI_IP) 팔로워
==================================================================
  리더암    : $LEADER_LEFT_PORT / $LEADER_RIGHT_PORT  (id: $LEADER_ID)
  주행 키   : i k j l (이동)  u o (회전)  n m (속도)
  제어 주기 : ${FPS}Hz
==================================================================

EOF

exec lerobot-teleoperate \
  "${CLIENT_ROBOT_ARGS[@]}" \
  "${LEADER_TELEOP_ARGS[@]}" \
  --fps="$FPS" \
  --display_data="$DISPLAY_DATA"
