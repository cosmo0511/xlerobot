#!/usr/bin/env bash
# =============================================================================
# upload_when_done.sh — 이미 돌고 있는 학습이 끝나길 기다렸다가 Hugging Face 에 올립니다.
# =============================================================================
#
# train.sh 를 다시 띄우지 않고, 옆에서 지켜보다가:
#   1. 그 OUTPUT_DIR 의 lerobot-train 이 끝날 때까지 기다림
#   2. 성공(exit 0)이고 checkpoints/last 가 있으면 → Hub 에 업로드 → 올라갔는지 확인
#   3. STOP_CMD 를 줬으면 그걸로 서버/컨테이너를 끔 (업로드가 실패하면 끄지 않음)
#
#   OUTPUT_DIR=/workspace/runs/smolvla_dice_armtext \
#   HUB_REPO=bilimili/xlerobot-dice-4cam-v2-smolvla-armtext \
#   nohup ./scripts/upload_when_done.sh > /workspace/runs/upload.out 2>&1 &
#
# 올리는 것: checkpoints/last/pretrained_model 전체 + 논문용 기록(<OUTPUT_DIR>.meta.json → train_meta.json)
# PRIVATE=1 (기본) 이면 비공개 repo 로 만듭니다. 이미 있는 repo 면 공개 여부는 그대로 둡니다.
#
# ■ 끄기 (STOP_CMD)
#   컨테이너 "안에서" 자기 자신을 끄는 방법은 플랫폼마다 다르고, 대부분 안 됩니다
#   (컨테이너의 1번 프로세스는 안에서 보낸 종료 신호를 무시합니다). 그래서 기본은 끄지 않고
#   알림만 남깁니다. 제공업체가 끄는 명령·API 를 주면 그걸 넣으세요:
#     STOP_CMD='runpodctl stop pod $RUNPOD_POD_ID'
# =============================================================================
set -uo pipefail

: "${OUTPUT_DIR:?OUTPUT_DIR 을 주세요 (train.sh 에 준 것과 같게)}"
: "${HUB_REPO:?HUB_REPO 를 주세요. 예: bilimili/xlerobot-dice-4cam-v2-smolvla-armtext}"
PRIVATE="${PRIVATE:-1}"
OUTPUT_DIR="${OUTPUT_DIR%/}"
META="$OUTPUT_DIR.meta.json"
MODEL_DIR="$OUTPUT_DIR/checkpoints/last/pretrained_model"
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*"; }

# --- 0. 지금 바로 로그인 확인 (몇 시간 기다린 뒤에 실패하지 않게) -----------------
if ! python - <<'PY'
from huggingface_hub import HfApi
try:
    print("HF 로그인:", HfApi().whoami()["name"])
except Exception as e:
    print("✗ Hugging Face 에 로그인돼 있지 않습니다:", e)
    print("  먼저:  hf auth login   (쓰기 권한 토큰)")
    raise SystemExit(1)
PY
then
  exit 1
fi

# --- 1. 학습이 끝날 때까지 기다리기 ---------------------------------------------
# pgrep(procps) 이 없는 슬림 이미지도 있어서 /proc 을 직접 봅니다.
# [l] 은 이 grep 자신의 명령줄이 걸리지 않게 하는 것.
running() {
  local f
  for f in /proc/[0-9]*/cmdline; do
    tr '\0' ' ' < "$f" 2>/dev/null | grep -q -- "[l]erobot-train.*--output_dir=$OUTPUT_DIR" && return 0
  done
  return 1
}
if running; then
  say "학습 대기 중: $OUTPUT_DIR (5분마다 확인)"
  while running; do sleep 300; done
else
  say "돌고 있는 학습이 없습니다 — 이미 끝난 것으로 보고 진행합니다."
fi
sleep 60   # train.sh 가 meta.json 에 종료 코드를 쓰고 정리할 시간

RC="$(python -c "import json;print(json.load(open('$META')).get('exit_code','?'))" 2>/dev/null || echo '?')"
say "학습 종료 코드: $RC"
if [ "$RC" != "0" ] || [ ! -f "$MODEL_DIR/config.json" ]; then
  say "✗ 학습이 성공하지 않았거나 $MODEL_DIR 이 없습니다. 업로드하지 않습니다."
  say "  로그: ${OUTPUT_DIR}.log"
  exit 1
fi

# --- 2. 업로드 (네트워크 오류면 3번까지 다시) -------------------------------------
ok=0
for try in 1 2 3; do
  say "업로드 시도 $try: $MODEL_DIR → $HUB_REPO"
  if MODEL_DIR="$MODEL_DIR" META="$META" HUB_REPO="$HUB_REPO" PRIVATE="$PRIVATE" python - <<'PY'
import os
from huggingface_hub import HfApi
api, repo = HfApi(), os.environ["HUB_REPO"]
api.create_repo(repo, repo_type="model", private=os.environ["PRIVATE"] == "1", exist_ok=True)
api.upload_folder(folder_path=os.environ["MODEL_DIR"], repo_id=repo, repo_type="model",
                  commit_message="학습 결과 (checkpoints/last)")
if os.path.exists(os.environ["META"]):
    api.upload_file(path_or_fileobj=os.environ["META"], path_in_repo="train_meta.json",
                    repo_id=repo, repo_type="model")
# 올라갔는지 확인: 로컬 파일이 전부 Hub 에 있는가
local = {os.path.relpath(os.path.join(d, f), os.environ["MODEL_DIR"])
         for d, _, fs in os.walk(os.environ["MODEL_DIR"]) for f in fs}
remote = set(api.list_repo_files(repo, repo_type="model"))
missing = sorted(local - remote)
if missing:
    raise SystemExit(f"Hub 에 없는 파일: {missing}")
print(f"✓ 업로드 확인: {len(local)}개 파일 → https://huggingface.co/{repo}")
PY
  then ok=1; break; fi
  sleep $((try * 60))
done
if [ "$ok" != "1" ]; then
  say "✗ 업로드 실패. 체크포인트는 $MODEL_DIR 에 그대로 있습니다. 끄지 않습니다."
  exit 1
fi

# --- 3. 끄기 -------------------------------------------------------------------
if [ -n "${STOP_CMD:-}" ]; then
  say "3분 뒤 끕니다: $STOP_CMD   (취소: kill $$)"
  sleep 180
  bash -c "$STOP_CMD" || say "⚠ 끄기 실패: $STOP_CMD — 콘솔에서 직접 끄세요."
else
  say "끝. STOP_CMD 를 안 줘서 끄지 않았습니다 — 콘솔에서 컨테이너를 중지하세요."
fi
