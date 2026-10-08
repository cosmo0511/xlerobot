#!/usr/bin/env bash
# =============================================================================
# base.sh — 베이스(바퀴)만 키보드로 몹니다. 팔은 안 건드립니다.
# =============================================================================
#
#   🦾 Pi 에서:      ./scripts/base.sh
#       -> port2 를 직접 열고 바퀴만 돌립니다.
#          host.sh 도, 팔 캘리브레이션도, 카메라도 필요 없습니다.
#
#   💻 노트북에서:   ./scripts/base.sh --remote
#       -> Pi 의 host 를 통해 몹니다. Pi 에서 host.sh 가 떠 있어야 합니다.
#
# 조작: i k (전후)  j l (좌우)  u o (회전)  n m (속도)  스페이스 (정지)  q (종료)
# =============================================================================

set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/xle_env.sh"

if [ "${1:-}" = "--remote" ]; then
  exec python -m xlerobot_devices.teleop_base --remote-ip "$PI_IP"
fi

exec python -m xlerobot_devices.teleop_base --port2 "$PI_PORT2"
