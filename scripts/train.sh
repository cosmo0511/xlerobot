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
#   평가는 checkpoints/last 만       -> 중간 체크포인트는 분석용 (loss·언어 테스트를 스텝별로)
#
# ■ 남는 것 (2026-10-12 갱신 — 논문에 쓸 자료를 영구 볼륨에 남깁니다)
# ---------------------------------------------------------------------------
#   결과와 로그는 **영구 볼륨**에 씁니다. 컨테이너가 재시작·삭제돼도 남아야 합니다
#   (2026-10-11 에 컨테이너 재시작으로 loss 기록을 통째로 잃은 적이 있습니다).
#   PERSIST_DIR 로 지정하고, 없으면 흔한 마운트 지점을 자동으로 찾습니다.
#   하나도 못 찾으면 레포 안(outputs/)에 쓰고 **경고합니다** — 그건 안 남을 수 있습니다.
#
#     PERSIST_DIR=/workspace/xlerobot ./scripts/train.sh smolvla
#
#   영구 볼륨에 남는 것:
#     <PERSIST_DIR>/train/<정책>_dice/            체크포인트
#     <PERSIST_DIR>/train/<정책>_dice.log         화면에 찍힌 것 전부 (loss 포함)
#     <PERSIST_DIR>/train/<정책>_dice.meta.json   논문용 기록 — 아래
#
#   meta.json 에 담는 것 (나중에 "그때 뭘로 돌렸더라" 가 안 되게):
#     xlerobot git 커밋 · lerobot 버전 · 데이터셋 repo/에피소드/프레임/지시문 분포
#     · batch/스텝/save_freq · GPU 이름과 메모리 · 시작·종료 시각 · 종료 코드
#
#   체크포인트는 SAVE_FREQ 스텝마다 (기본 2,500 -> 80k 면 32개). 학습 결과에는
#   영향 없고 저장만 합니다. 실측 크기: SmolVLA 0.91GB, ACT 0.21GB (모델만).
#     32개씩 둘 다 = 35.7GB. 50GB 볼륨에 들어갑니다.
#     40개씩(SAVE_FREQ=2000) = 44.7GB -> 빠듯합니다. 볼륨이 크면 그때 올리세요.
#   시작 전에 남은 용량을 재서 모자라면 **멈춥니다** (GPU 를 몇 시간 태우고 나서
#   디스크가 꽉 차는 게 제일 아깝습니다). 무시하려면 SKIP_DISK_CHECK=1.
#
#   옵티마이저 상태(training_state)는 가장 최근 것만 남기고 지웁니다 — 이어가기에는 last 만
#   필요하고, 전부 두면 SmolVLA 는 32개 x ~1.8GB 로 볼륨이 감당이 안 됩니다.
#   전부 남기려면 KEEP_ALL_STATES=1.
#
# 메모리 확인·연결 테스트처럼 짧게 돌릴 때만 env 로 바꿉니다 (바꾸면 경고를 찍습니다):
#   STEPS=20 ./scripts/train.sh act
#   BATCH=8 STEPS=5 OUTPUT_DIR=outputs/train/smoke ./scripts/train.sh smolvla
#
# 그 밖의 lerobot-train 인자는 뒤에 그대로 붙이면 넘어갑니다.

# ■ 끝나면 서버 끄기 (GPU 가 시간당 과금일 때)
# ---------------------------------------------------------------------------
#   SHUTDOWN_WHEN_DONE=1 ./scripts/train.sh smolvla
#
#   성공이든 실패든 학습이 끝나면 SHUTDOWN_GRACE 초(기본 180) 뒤에 서버를 끕니다.
#   그 사이에 Ctrl+C 를 누르면 취소됩니다.
#
#   ⚠ 체크포인트를 먼저 안전한 곳에 두세요. 컨테이너가 사라지면서 같이 날아가면
#     GPU 비용만 쓰고 아무것도 안 남습니다. POST_TRAIN_CMD 가 **끄기 전에** 돕니다:
#
#     SHUTDOWN_WHEN_DONE=1 \
#     POST_TRAIN_CMD='hf upload bilimili/xlerobot-dice-4cam-v2-smolvla \
#                     outputs/train/smolvla_dice/checkpoints/last/pretrained_model' \
#     ./scripts/train.sh smolvla
#
#     POST_TRAIN_CMD 가 실패하면 **끄지 않습니다** (올리다 실패했는데 끄면 끝입니다).
#
#   끄는 명령은 환경마다 다릅니다. 기본은 `sudo shutdown -h now` -> `shutdown -h now`
#   순으로 시도하고, 둘 다 없으면 끄지 않고 알려만 줍니다. 제공업체 CLI 가 있으면
#   그걸 주세요:  SHUTDOWN_CMD='runpodctl stop pod $RUNPOD_POD_ID'
#
#   ⚠ smolvla 와 act 를 **동시에** 돌릴 때: 먼저 끝난 쪽이 서버를 끄면 다른 쪽이
#     통째로 날아갑니다. 그래서 다른 lerobot-train 이 아직 돌고 있으면 끄지 않고
#     건너뜁니다 — 둘 다에 SHUTDOWN_WHEN_DONE=1 을 줘도 마지막 하나만 끕니다.
#
#
# ■ 데이터 (2026-10-12: v2 로 바꿈)
# ---------------------------------------------------------------------------
# 기본은 Hub 의 bilimili/xlerobot-dice-4cam-v2 — 빨강/노랑 104개(52/52), 66.2분.
# 2026-10-12 에 주사위를 파랑 -> 노랑으로 바꿔 처음부터 다시 찍은 것입니다
# (COLLECTING.md 2절, scripts/run_4cam_v2.sh). 예전 96개(빨강/파랑, `-4cam`)로
# 학습하려면 DATASET_REPO=bilimili/xlerobot-dice-4cam 를 주세요.
#
# 로컬 사본이 있으면 Hub 에서 다시 안 받습니다 — 표준 위치는 자동으로 찾고,
# 다른 데 있으면 DATASET_ROOT=<폴더> 로 주세요 (컨테이너에서 볼륨을 마운트한 경우 등).
# =============================================================================

set -euo pipefail

POLICY="${1:-}"
shift || true

BATCH_RULE=16
STEPS_RULE=80000
BATCH="${BATCH:-$BATCH_RULE}"
STEPS="${STEPS:-$STEPS_RULE}"
SAVE_FREQ="${SAVE_FREQ:-2500}"
NUM_WORKERS="${NUM_WORKERS:-4}"
DATASET_REPO="${DATASET_REPO:-bilimili/xlerobot-dice-4cam-v2}"

# 로컬 사본이 있으면 Hub 에서 다시 받지 않습니다.
# 표준 위치(<lerobot home>/<repo_id>)를 DATASET_REPO 에서 그대로 끌어내므로,
# DATASET_REPO 를 바꾸면 찾는 폴더도 같이 따라갑니다 (dataset_path.sh 와 같은 규칙).
# 예전 96개는 녹화 당시 HF 계정이 달라서 cosmo0511/ 아래에 있습니다 — 그것도 찾아봅니다.
LEROBOT_HOME="${HF_LEROBOT_HOME:-${HF_HOME:-$HOME/.cache/huggingface}/lerobot}"
if [ -z "${DATASET_ROOT:-}" ]; then
  for _cand in "$LEROBOT_HOME/$DATASET_REPO" \
               "$LEROBOT_HOME/cosmo0511/${DATASET_REPO##*/}"; do
    if [ -f "$_cand/meta/info.json" ]; then
      DATASET_ROOT="$_cand"
      break
    fi
  done
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

# --- 영구 볼륨 ---------------------------------------------------------------
# 컨테이너 안의 레포 폴더는 재시작하면 사라질 수 있습니다. 체크포인트·로그·메타는
# 반드시 마운트된 볼륨에 둡니다. PERSIST_DIR 이 없으면 흔한 마운트 지점을 찾습니다.
if [ -z "${PERSIST_DIR:-}" ]; then
  for _cand in /workspace /runpod-volume /persist /data /mnt/data; do
    if [ -d "$_cand" ] && [ -w "$_cand" ]; then
      PERSIST_DIR="$_cand/xlerobot"
      break
    fi
  done
fi
if [ -n "${PERSIST_DIR:-}" ]; then
  mkdir -p "$PERSIST_DIR/train"
  OUTPUT_DIR="${OUTPUT_DIR:-$PERSIST_DIR/train/${POLICY}_dice}"
else
  OUTPUT_DIR="${OUTPUT_DIR:-outputs/train/${POLICY}_dice}"
  echo "⚠ 영구 볼륨을 못 찾아 레포 안($OUTPUT_DIR)에 씁니다."
  echo "  컨테이너가 재시작되면 체크포인트와 loss 기록이 사라질 수 있습니다."
  echo "  볼륨이 있으면: PERSIST_DIR=/workspace/xlerobot $0 $POLICY"
  echo
fi

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
LOG_FILE="${OUTPUT_DIR%/}.log"
mkdir -p "$(dirname "$OUTPUT_DIR")"

META_FILE="${OUTPUT_DIR%/}.meta.json"
echo "결과     : $OUTPUT_DIR   (평가에는 checkpoints/last)"
echo "로그     : $LOG_FILE"
echo "기록     : $META_FILE   (논문용)"

# --- 디스크 확인 -------------------------------------------------------------
# 체크포인트 하나 크기 실측(2026-10-12, 모델만): SmolVLA 0.91GB / ACT 0.21GB.
# training_state 는 가장 최근 것만 남기므로 모델 크기의 ~2배를 한 번치만 더합니다.
case "$POLICY" in
  smolvla) CKPT_MB=910 ;;
  act)     CKPT_MB=210 ;;
  *)       CKPT_MB=910 ;;
esac
N_CKPT=$(( STEPS / SAVE_FREQ ))
[ "$N_CKPT" -lt 1 ] && N_CKPT=1
NEED_MB=$(( CKPT_MB * N_CKPT + CKPT_MB * 2 ))
AVAIL_MB="$(df -Pm "$(dirname "$OUTPUT_DIR")" 2>/dev/null | awk 'NR==2{print $4}')"
echo "체크포인트: ${N_CKPT}개 x ${CKPT_MB}MB + 옵티마이저 1벌 = 약 $(( NEED_MB / 1024 ))GB 필요" \
     "/ 남은 공간 $(( ${AVAIL_MB:-0} / 1024 ))GB"
if [ "${SKIP_DISK_CHECK:-0}" != "1" ] && [ -n "${AVAIL_MB:-}" ] && [ "$AVAIL_MB" -lt "$NEED_MB" ]; then
  echo >&2
  echo "✗ 디스크가 모자랍니다. 학습 도중에 꽉 차면 몇 시간치 GPU 를 버립니다." >&2
  echo "  SAVE_FREQ 를 올려 체크포인트를 줄이거나(예: SAVE_FREQ=5000 -> $(( STEPS / 5000 ))개)," >&2
  echo "  볼륨을 키우거나, 정말 괜찮으면 SKIP_DISK_CHECK=1 로 넘기세요." >&2
  exit 1
fi
echo

# --- 논문용 기록 -------------------------------------------------------------
# "그때 무슨 커밋·무슨 데이터로 돌렸더라" 가 안 되게 시작할 때 남깁니다.
write_meta() {
  python3 - "$META_FILE" "$1" "${2:-}" <<'PY' 2>/dev/null || true
import json, os, subprocess, sys, datetime, pathlib

path, phase, rc = sys.argv[1], sys.argv[2], sys.argv[3]
m = {}
if phase == "end" and os.path.exists(path):
    try:
        m = json.load(open(path))
    except Exception:
        m = {}

def sh(*c):
    try:
        return subprocess.run(c, capture_output=True, text=True, timeout=10).stdout.strip() or None
    except Exception:
        return None

now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")

if phase == "start":
    m["started_at"] = now
    m["policy"] = os.environ.get("POLICY")
    m["batch_size"] = int(os.environ.get("BATCH", 0))
    m["steps"] = int(os.environ.get("STEPS", 0))
    m["save_freq"] = int(os.environ.get("SAVE_FREQ", 0))
    m["output_dir"] = os.environ.get("OUTPUT_DIR")
    m["dataset"] = {"repo_id": os.environ.get("DATASET_REPO"),
                    "root": os.environ.get("DATASET_ROOT") or None}
    root = os.environ.get("DATASET_ROOT")
    if root and os.path.exists(f"{root}/meta/info.json"):
        try:
            i = json.load(open(f"{root}/meta/info.json"))
            m["dataset"].update(episodes=i.get("total_episodes"),
                                frames=i.get("total_frames"),
                                fps=i.get("fps"),
                                codebase_version=i.get("codebase_version"))
            if i.get("total_frames") and i.get("fps"):
                m["dataset"]["minutes"] = round(i["total_frames"] / i["fps"] / 60, 1)
            if m["batch_size"] and m["steps"] and i.get("total_frames"):
                m["epochs"] = round(m["batch_size"] * m["steps"] / i["total_frames"], 2)
        except Exception:
            pass
        try:
            import glob, pandas as pd
            fs = sorted(glob.glob(f"{root}/meta/episodes/**/*.parquet", recursive=True))
            df = pd.concat([pd.read_parquet(f) for f in fs])
            m["dataset"]["tasks"] = {k: int(v) for k, v in
                                     df.tasks.explode().value_counts().items()}
        except Exception:
            pass
    repo = os.environ.get("PROJECT_ROOT") or "."
    m["code"] = {
        "xlerobot_commit": sh("git", "-C", repo, "rev-parse", "HEAD"),
        "xlerobot_dirty": bool(sh("git", "-C", repo, "status", "--porcelain")),
        "lerobot_version": sh("python3", "-c", "import lerobot;print(lerobot.__version__)"),
    }
    gpu = sh("nvidia-smi", "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader")
    m["gpu"] = gpu
else:
    m["ended_at"] = now
    m["exit_code"] = int(rc) if rc.isdigit() else rc
    try:
        ck = pathlib.Path(m.get("output_dir", "")) / "checkpoints"
        m["checkpoints_saved"] = sorted(d.name for d in ck.iterdir() if d.name[:1].isdigit())
    except Exception:
        pass

pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
json.dump(m, open(path, "w"), indent=2, ensure_ascii=False)
PY
}
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT POLICY BATCH STEPS SAVE_FREQ OUTPUT_DIR DATASET_REPO
[ -n "${DATASET_ROOT:-}" ] && export DATASET_ROOT
write_meta start


# 지난 체크포인트의 training_state 를 1분마다, 그리고 끝날 때 한 번 더 정리. last 가 가리키는
# 것과, 지금 쓰고 있을 수 있는 가장 큰 번호는 건드리지 않습니다.
prune_old_states() {
  local ck="$OUTPUT_DIR/checkpoints" keep newest d
  [ -d "$ck" ] || return 0
  keep="$(readlink -f "$ck/last" 2>/dev/null || true)"
  newest="$( (ls -d "$ck"/[0-9]* 2>/dev/null || true) | sort | tail -n 1)"
  for d in "$ck"/[0-9]*; do
    [ -d "$d/training_state" ] || continue
    [ "$(readlink -f "$d")" = "$keep" ] && continue
    [ "$d" = "$newest" ] && continue
    rm -rf "$d/training_state"
  done
}
if [ "${KEEP_ALL_STATES:-0}" != "1" ]; then
  ( while sleep 60; do prune_old_states; done ) >/dev/null 2>&1 &
  PRUNE_PID=$!
  trap 'kill "$PRUNE_PID" 2>/dev/null || true; prune_old_states' EXIT
fi

# push_to_hub=false: lerobot 기본값(true)이면 --policy.repo_id 가 없다고 멈춥니다.
# 파이프(tee)로 나가도 줄 단위로 바로 써지도록 PYTHONUNBUFFERED.
set +e
PYTHONUNBUFFERED=1 lerobot-train \
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
  "$@" 2>&1 | tee -a "$LOG_FILE"
TRAIN_RC=${PIPESTATUS[0]}
set -e

write_meta end "$TRAIN_RC"

echo | tee -a "$LOG_FILE"
if [ "$TRAIN_RC" = "0" ]; then
  echo "학습 끝 ($POLICY). 결과: $OUTPUT_DIR/checkpoints/last" | tee -a "$LOG_FILE"
else
  echo "학습이 실패로 끝났습니다 ($POLICY, exit $TRAIN_RC). 로그: $LOG_FILE" | tee -a "$LOG_FILE"
fi

# --------------------------- 끝나면 서버 끄기 ---------------------------------
# GPU 가 시간당 과금일 때. 기본은 꺼져 있고, SHUTDOWN_WHEN_DONE=1 일 때만 돕니다.
if [ "${SHUTDOWN_WHEN_DONE:-0}" = "1" ]; then
  # 체크포인트를 밖으로 빼는 등, **끄기 전에** 해야 하는 일.
  # 여기서 실패하면 끄지 않습니다 — 백업이 실패했는데 끄면 되돌릴 수 없습니다.
  if [ -n "${POST_TRAIN_CMD:-}" ]; then
    echo "끄기 전 작업: $POST_TRAIN_CMD" | tee -a "$LOG_FILE"
    if ! bash -c "$POST_TRAIN_CMD" 2>&1 | tee -a "$LOG_FILE"; then
      echo "⚠ POST_TRAIN_CMD 가 실패했습니다. 체크포인트가 안전하지 않을 수 있어 **끄지 않습니다.**" \
        | tee -a "$LOG_FILE"
      exit "$TRAIN_RC"
    fi
  fi

  # 다른 lerobot-train 이 아직 돌고 있으면 끄지 않습니다 (smolvla + act 동시 실행).
  # 명령줄에 글자가 들어 있기만 한 프로세스에 속지 않도록 argv 를 직접 확인합니다.
  others=0
  for _pid in $(pgrep -f 'lerobot-train' 2>/dev/null || true); do
    [ "$_pid" = "$$" ] && continue
    _argv=()
    [ -r "/proc/$_pid/cmdline" ] || continue
    mapfile -d '' -t _argv < "/proc/$_pid/cmdline" 2>/dev/null || continue
    for _i in 0 1; do
      if [ "$(basename -- "${_argv[$_i]:-}")" = "lerobot-train" ]; then
        others=$((others + 1))
        break
      fi
    done
  done

  if [ "$others" -gt 0 ]; then
    echo "다른 lerobot-train 이 $others 개 돌고 있어 끄지 않습니다 (마지막에 끝나는 쪽이 끕니다)." \
      | tee -a "$LOG_FILE"
  else
    GRACE="${SHUTDOWN_GRACE:-180}"
    if [ -z "${SHUTDOWN_CMD:-}" ]; then
      if sudo -n true 2>/dev/null && command -v shutdown >/dev/null; then
        SHUTDOWN_CMD="sudo shutdown -h now"
      elif command -v shutdown >/dev/null; then
        SHUTDOWN_CMD="shutdown -h now"
      fi
    fi
    if [ -z "${SHUTDOWN_CMD:-}" ]; then
      echo "⚠ 끄는 명령을 못 찾았습니다 (shutdown 없음 / sudo 안 됨). 직접 끄세요." | tee -a "$LOG_FILE"
      echo "  다음부터는 SHUTDOWN_CMD='<제공업체 명령>' 로 주세요." | tee -a "$LOG_FILE"
    else
      echo "$GRACE 초 뒤에 서버를 끕니다: $SHUTDOWN_CMD" | tee -a "$LOG_FILE"
      echo "  취소하려면 지금 Ctrl+C." | tee -a "$LOG_FILE"
      sleep "$GRACE"
      echo "끕니다." | tee -a "$LOG_FILE"
      bash -c "$SHUTDOWN_CMD" || echo "⚠ 끄기 실패: $SHUTDOWN_CMD" | tee -a "$LOG_FILE"
    fi
  fi
fi

exit "$TRAIN_RC"
