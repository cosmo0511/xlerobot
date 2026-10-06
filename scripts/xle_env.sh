# =============================================================================
# xle_env.sh — host/client 공통 설정. 다른 스크립트가 source 합니다.
# =============================================================================
# **여기만 고치세요.** host.sh / teleop.sh / record.sh 는 건드릴 필요 없습니다.
#
# 쓰는 곳:
#   🦾 Pi       host.sh                  (PI_PORT1, PI_PORT2, CAM_*, ROBOT_ID)
#   💻 노트북   teleop.sh / record.sh    (PI_IP, LEADER_*, CAM_*, ROBOT_ID)
#
# ⚠️ CAM_* 와 ROBOT_ID 는 **양쪽에서 똑같아야** 합니다.
#   카메라 이름/해상도가 어긋나면 녹화된 이미지 키가 틀어지고,
#   ROBOT_ID 가 다르면 Pi 가 다른 캘리브레이션 파일을 찾습니다.
# =============================================================================

# --- 공통 ---------------------------------------------------------------------
ROBOT_ID="${ROBOT_ID:-home_xle}"           # Pi 의 캘리브레이션 파일 이름
LEADER_ID="${LEADER_ID:-home_xle_leader}"  # 리더암 캘리브레이션 파일 이름

FPS="${FPS:-30}"                           # 제어/녹화 주기. host 의 루프와 맞추세요.

# 카메라 3개. 이름이 그대로 데이터셋 키가 됩니다.
#   top          -> observation.images.top
#   left_wrist   -> observation.images.left_wrist
#   right_wrist  -> observation.images.right_wrist
CAM_TOP="${CAM_TOP:-/dev/video0}"
CAM_LEFT_WRIST="${CAM_LEFT_WRIST:-/dev/video2}"
CAM_RIGHT_WRIST="${CAM_RIGHT_WRIST:-/dev/video4}"
CAM_W="${CAM_W:-640}"
CAM_H="${CAM_H:-480}"

# --- 🦾 Pi (host) -------------------------------------------------------------
PI_PORT1="${PI_PORT1:-/dev/ttyACM0}"   # 왼팔 버스 (ID 1~6)
PI_PORT2="${PI_PORT2:-/dev/ttyACM1}"   # 오른팔 + 르키위 버스 (ID 1~6 팔, 7~9 바퀴)

# host 가 살아 있을 시간(초). 넘으면 **스스로 종료합니다.** 기본 10시간.
HOST_UPTIME_S="${HOST_UPTIME_S:-36000}"

# --- 💻 노트북 (client) -------------------------------------------------------
PI_IP="${PI_IP:-192.168.0.101}"            # 라즈베리파이 IP
LEADER_LEFT_PORT="${LEADER_LEFT_PORT:-/dev/ttyACM0}"
LEADER_RIGHT_PORT="${LEADER_RIGHT_PORT:-/dev/ttyACM1}"

# 안전장치: 한 스텝에 관절이 움직일 수 있는 최대량(정규화 단위).
# 리더암을 확 휘두르면 팔로워가 그대로 따라갑니다. 처음엔 켜두고 익숙해지면 빈 값으로.
MAX_REL_TARGET="${MAX_REL_TARGET:-}"

# -----------------------------------------------------------------------------
# 아래는 건드리지 마세요. 위 값들로 긴 인자를 조립합니다.
# -----------------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

# 카메라 3개를 draccus 가 읽는 형식으로. host 와 client 가 같은 문자열을 씁니다.
CAMERAS_ARG="{ top: {\"type\":\"opencv\",\"index_or_path\":\"$CAM_TOP\",\"width\":$CAM_W,\"height\":$CAM_H,\"fps\":$FPS}, left_wrist: {\"type\":\"opencv\",\"index_or_path\":\"$CAM_LEFT_WRIST\",\"width\":$CAM_W,\"height\":$CAM_H,\"fps\":$FPS}, right_wrist: {\"type\":\"opencv\",\"index_or_path\":\"$CAM_RIGHT_WRIST\",\"width\":$CAM_W,\"height\":$CAM_H,\"fps\":$FPS} }"

# client(노트북)에서 로봇을 가리키는 인자. 배열이라 공백이 들어가도 안 깨집니다.
CLIENT_ROBOT_ARGS=(
  --robot.type=xlerobot_client
  --robot.discover_packages_path=xlerobot_devices
  "--robot.remote_ip=$PI_IP"
  "--robot.id=$ROBOT_ID"
  "--robot.cameras=$CAMERAS_ARG"
)

# 리더암 2개 + 키보드.
LEADER_TELEOP_ARGS=(
  --teleop.type=bi_leader_base
  --teleop.discover_packages_path=xlerobot_devices
  "--teleop.id=$LEADER_ID"
  "--teleop.left_arm_config.port=$LEADER_LEFT_PORT"
  "--teleop.right_arm_config.port=$LEADER_RIGHT_PORT"
)
