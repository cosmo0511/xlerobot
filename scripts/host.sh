#!/usr/bin/env bash
# =============================================================================
# host.sh — 🦾 라즈베리파이에서 실행. 팔 2개 + 바퀴 3개 + 카메라 3개를 엽니다.
# =============================================================================
#
#   ./scripts/host.sh
#
# 이게 떠 있는 동안에만 노트북의 teleop.sh / record.sh 가 동작합니다.
# 설정은 scripts/xle_env.sh 에서 고치세요.
#
# ⚠️ 처음 한 번은 캘리브레이션을 먼저 해야 합니다 (Pi 에서):
#
#     ./scripts/host.sh --calibrate
#
# ⚠️ 이 프로세스가 /dev/ttyACM* 를 **독점**합니다. 같은 Pi 에서 바퀴를 쓰는
#   다른 프로그램(Nav2 드라이버 등)을 동시에 띄울 수 없습니다. 바퀴가 오른팔과
#   같은 버스에 있어서 그렇습니다. 자세한 건 TELEOP.md 를 보세요.
# =============================================================================

set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/xle_env.sh"

if [ "${1:-}" = "--calibrate" ]; then
  cat <<EOF

==================================================================
  캘리브레이션 — 팔 4개(왼팔/오른팔) 관절을 손으로 돌립니다
  저장 위치: ~/.cache/huggingface/lerobot/calibration/robots/xlerobot/$ROBOT_ID.json
==================================================================
  순서: 왼팔 중간자세 -> 왼팔 전범위 -> 오른팔 중간자세 -> 오른팔 전범위
  바퀴는 건드리지 마세요. 자동으로 0~4095 가 들어갑니다.

EOF
  exec lerobot-calibrate \
    --robot.type=xlerobot \
    --robot.discover_packages_path=xlerobot_devices \
    --robot.id="$ROBOT_ID" \
    --robot.port1="$PI_PORT1" \
    --robot.port2="$PI_PORT2" \
    --robot.cameras="{}"
fi

ROBOT_ARGS=(
  "--robot.id=$ROBOT_ID"
  "--robot.port1=$PI_PORT1"
  "--robot.port2=$PI_PORT2"
  "--robot.cameras=$CAMERAS_ARG"
)
if [ -n "$MAX_REL_TARGET" ]; then
  ROBOT_ARGS+=("--robot.max_relative_target=$MAX_REL_TARGET")
fi

cat <<EOF

==================================================================
  XLeRobot host
==================================================================
  왼팔 버스        : $PI_PORT1        (ID 1~6)
  오른팔+르키위    : $PI_PORT2        (ID 1~6 팔, 7~9 바퀴)
  카메라           : $CAM_TOP / $CAM_LEFT_WRIST / $CAM_RIGHT_WRIST
  캘리브레이션 ID  : $ROBOT_ID
  동작 시간        : ${HOST_UPTIME_S}초 (지나면 스스로 종료)
  ZMQ              : 명령 5555 / 관측 5556
==================================================================

노트북에서 붙을 주소: --robot.remote_ip=\$(이 Pi 의 IP)
EOF

exec python -m xlerobot_devices.xlerobot_host \
  "${ROBOT_ARGS[@]}" \
  --host.max_loop_freq_hz="$FPS" \
  --host.connection_time_s="$HOST_UPTIME_S"
