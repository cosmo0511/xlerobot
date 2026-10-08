#!/usr/bin/env bash
# 기본 진입점: Isaac 쪽 환경을 깔고 넘겨받은 명령을 실행합니다.
# ROS 노드를 돌릴 때는 컨테이너 안에서 `ros-shell` 로 갈아타세요.
set -eo pipefail
source /opt/isaaclab-scripts/isaac-env.sh
exec "$@"
