#!/usr/bin/env bash
# =============================================================================
# train.sh — 💻 SmolVLA / ACT 학습. 실험 규칙(둘 다 같은 조건)을 여기 한 곳에 고정합니다.
# =============================================================================
#
#   ./scripts/train.sh smolvla
#   ./scripts/train.sh act
#
#   # 컨테이너 안에서도 똑같이 (docker/README.md)
#
# ■ 규칙 (2026-10-10 결정, RUNNING.md 3단계) — 평가 전에 고정, 결과 보고 바꾸지 않음
# ---------------------------------------------------------------------------
#   batch 16, 80,000 스텝 (둘 다)   -> 본 샘플 128만 = SmolVLA 공식 파인튜닝(64 x 20k)과 같은 양
#   학습률·옵티마이저는 각자 기본값  -> 구조가 달라서 같은 값을 쓰면 한쪽이 망가짐
#   평가는 checkpoints/last 만       -> save_freq 는 끊겼을 때 이어가기용
#
# 메모리 확인·연결 테스트처럼 짧게 돌릴 때만 env 로 바꿉니다 (바꾸면 경고를 찍습니다):
#   STEPS=20 ./scripts/train.sh act
#   BATCH=8 STEPS=5 OUTPUT_DIR=outputs/train/smoke ./scripts/train.sh smolvla
#
# 그 밖의 lerobot-train 인자는 뒤에 그대로 붙이면 넘어갑니다.
#
# ■ 데이터
# ---------------------------------------------------------------------------
# 기본은 Hub 의 bilimili/xlerobot-dice-4cam (공개). 로컬에 이미 있으면 DATASET_ROOT 로
# 그 폴더를 주세요 (다시 안 받음). 원본 PC 는 아래 경로가 있으면 자동으로 씁니다.
# =============================================================================

set -euo pipefail

POLICY="${1:-}"
shift || true

BATCH_RULE=16
STEPS_RULE=80000
BATCH="${BATCH:-$BATCH_RULE}"
STEPS="${STEPS:-$STEPS_RULE}"
SAVE_FREQ="${SAVE_FREQ:-20000}"
NUM_WORKERS="${NUM_WORKERS:-4}"
DATASET_REPO="${DATASET_REPO:-bilimili/xlerobot-dice-4cam}"

# 원본 PC 의 로컬 사본 (녹화한 폴더). 있으면 Hub 에서 다시 받지 않습니다.
PC_LOCAL="$HOME/.cache/huggingface/lerobot/cosmo0511/xlerobot-dice-4cam"
if [ -z "${DATASET_ROOT:-}" ] && [ -f "$PC_LOCAL/meta/info.json" ]; then
  DATASET_ROOT="$PC_LOCAL"
fi

case "$POLICY" in
  smolvla)
    # input_features=null: smolvla_base 는 camera1/2/3 을 기대하는데 우리는 4대
    # (top/base/left_wrist/right_wrist). null 이면 데이터셋에서 4대를 그대로 가져옵니다.
    # --rename_map 으로 3대만 맞추면 4번째가 조용히 버려져 ACT 와 입력이 달라집니다.
    POLICY_ARGS=(--policy.path=lerobot/smolvla_base
                 --policy.input_features=null --policy.output_features=null)
    ;;
  act)
    POLICY_ARGS=(--policy.type=act)
    ;;
  *)
    echo "사용법: $0 smolvla|act [lerobot-train 추가 인자...]" >&2
    exit 1
    ;;
esac

OUTPUT_DIR="${OUTPUT_DIR:-outputs/train/${POLICY}_dice}"

if [ "$BATCH" != "$BATCH_RULE" ] || [ "$STEPS" != "$STEPS_RULE" ]; then
  echo "⚠ 실험 규칙(batch $BATCH_RULE / $STEPS_RULE 스텝)과 다릅니다: batch $BATCH / $STEPS 스텝."
  echo "  테스트용이면 괜찮지만, 이 결과를 평가에 쓰면 SmolVLA 와 ACT 의 조건이 달라집니다."
  echo
fi

ROOT_ARGS=()
if [ -n "${DATASET_ROOT:-}" ]; then
  ROOT_ARGS=(--dataset.root="$DATASET_ROOT")
fi

echo "정책     : $POLICY"
echo "데이터셋 : $DATASET_REPO ${DATASET_ROOT:+(로컬: $DATASET_ROOT)}"
echo "batch    : $BATCH   스텝: $STEPS   저장 간격: $SAVE_FREQ"
echo "결과     : $OUTPUT_DIR   (평가에는 checkpoints/last)"
echo

# push_to_hub=false: lerobot 기본값(true)이면 --policy.repo_id 가 없다고 멈춥니다.
exec lerobot-train \
  "${POLICY_ARGS[@]}" \
  --dataset.repo_id="$DATASET_REPO" \
  "${ROOT_ARGS[@]}" \
  --batch_size="$BATCH" \
  --steps="$STEPS" \
  --save_freq="$SAVE_FREQ" \
  --num_workers="$NUM_WORKERS" \
  --output_dir="$OUTPUT_DIR" \
  --job_name="${POLICY}_dice" \
  --policy.device=cuda \
  --policy.push_to_hub=false \
  --wandb.enable=false \
  "$@"
