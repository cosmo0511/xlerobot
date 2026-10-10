# =============================================================================
# dataset_path.sh — 데이터셋 이름·폴더·진행 개수의 **단일 진실 소스**. source 전용.
# =============================================================================
#
#   source "$SCRIPT_DIR/dataset_path.sh"
#   # -> REPO_ID, DATASET_ROOT, DONE, PUSH 가 채워집니다
#
# 들어오는 값: CAMERA_SET, HF_USER (필수), REPO_ID / DATASET_ROOT / PUSH_TO_HUB (선택)
#
# ■ 왜 폴더를 우리가 정하나 — 이게 이어찍기의 핵심입니다
# ---------------------------------------------------------------------------
# lerobot 0.6 은 데이터셋을 **새로 만들 때** repo_id 에 타임스탬프를 붙입니다
# (configs/dataset.py 의 stamp_repo_id — "각 녹화 세션이 고유한 이름을 갖도록").
# 그래서 --root 를 안 주면 폴더가 이렇게 갈립니다:
#
#   1회차  .../xlerobot-dice-4cam_20261010_145603/   <- 타임스탬프가 붙음
#   2회차  resume("xlerobot-dice-4cam") 로 찾음       <- 그런 폴더가 없음
#          -> 로컬에 없으니 Hub 에서 받으려 하다 RepositoryNotFoundError 401
#
# 즉 --root 없이는 **2회차부터 아예 녹화가 안 됩니다.** --root 를 고정하면
# 이름이 뭐가 되든 같은 폴더에 이어 붙습니다 (1개 -> 2개 -> 3개 확인했습니다).
#
# 녹화(record.sh)와 상태 확인(run_4cam.sh status / droplast)이 같은 폴더를 봐야
# 하므로, 경로 계산을 두 곳에 적지 않고 여기 한 곳에만 둡니다.
# =============================================================================

: "${CAMERA_SET:?dataset_path.sh: CAMERA_SET 이 필요합니다}"
: "${HF_USER:?환경변수 HF_USER 를 먼저 설정하세요. 예: export HF_USER=songyeon}"

# 카메라 구성이 다른 데이터를 한 데이터셋에 섞으면 관측 키가 안 맞아 깨집니다.
# 그래서 이름에 구성을 넣어 자동으로 분리합니다 (xlerobot-dice-3cam / -4cam).
REPO_ID="${REPO_ID:-$HF_USER/xlerobot-dice-$CAMERA_SET}"

LEROBOT_HOME="${HF_LEROBOT_HOME:-${HF_HOME:-$HOME/.cache/huggingface}/lerobot}"
DATASET_ROOT="${DATASET_ROOT:-$LEROBOT_HOME/$REPO_ID}"

# 지금까지 찍힌 에피소드 개수. 폴더가 없거나 깨졌으면 0.
DONE=0
if [ -f "$DATASET_ROOT/meta/info.json" ]; then
  DONE="$(python3 -c 'import json,sys
try: print(int(json.load(open(sys.argv[1])).get("total_episodes") or 0))
except Exception: print(0)' "$DATASET_ROOT/meta/info.json")"
fi

# Hub 업로드는 기본으로 끕니다. lerobot 기본값이 push_to_hub=true 라서, 그냥 두면
# 블록마다 데이터셋이 HuggingFace 로 **올라갑니다**. 올릴 준비가 됐을 때 PUSH_TO_HUB=1
# 로 켜세요 (토큰이 없으면 녹화가 끝난 뒤 401 로 시끄럽기만 합니다).
if [ "${PUSH_TO_HUB:-0}" = "1" ]; then PUSH="true"; else PUSH="false"; fi
