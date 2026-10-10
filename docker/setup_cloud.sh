#!/usr/bin/env bash
# =============================================================================
# setup_cloud.sh — 클라우드 컨테이너(AIEEV Air Container 등) 안에서 학습 환경을 만듭니다.
# =============================================================================
#
# 이미지를 직접 만들어 올리는 대신, 공개 이미지 python:3.12-slim 으로 컨테이너를
# 띄우고 웹 터미널에서 이걸 한 번 실행합니다. 결과는 docker/Dockerfile.train 과
# 같습니다 (lerobot v0.6.0 + vendor 패치 + torch 2.11 + [training,smolvla]).
#
#   curl -fsSL https://raw.githubusercontent.com/cosmo0511/xlerobot/main/docker/setup_cloud.sh | bash
#
# 전부 영구 볼륨(/workspace) 안에 깔립니다. 컨테이너가 재시작돼도 다시 안 깔아도 되고,
# 학습 결과도 남습니다. 다시 들어왔을 때는:
#
#   source /workspace/env.sh
#
# ■ 바꿀 수 있는 것
#   WORKSPACE=/workspace   영구 볼륨 마운트 경로 (콘솔의 Mount Path 와 같게)
#   TORCH_CUDA=cu128       드라이버 580 이상이면 cu130 도 됨 (5090 은 cu128 이상 필수)
# =============================================================================

set -euo pipefail

WORKSPACE="${WORKSPACE:-/workspace}"
TORCH_CUDA="${TORCH_CUDA:-cu128}"

mkdir -p "$WORKSPACE"
cd "$WORKSPACE"

echo "== 1/5 시스템 패키지 (git, ffmpeg)"
if command -v apt-get >/dev/null; then
  SUDO=""; [ "$(id -u)" = "0" ] || SUDO="sudo"
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq --no-install-recommends git ffmpeg libglib2.0-0 build-essential curl >/dev/null
fi

echo "== 2/5 가상환경 ($WORKSPACE/venv)"
[ -d venv ] || python3.12 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
pip install -q --upgrade pip

echo "== 3/5 PyTorch 2.11 ($TORCH_CUDA)"
pip install -q torch==2.11.0 torchvision==0.26.0 --index-url "https://download.pytorch.org/whl/$TORCH_CUDA"

echo "== 4/5 xlerobot + lerobot v0.6.0 + 우리 패치"
[ -d xlerobot ] || git clone -q https://github.com/cosmo0511/xlerobot.git
git -C xlerobot pull -q --ff-only || true
if [ ! -d lerobot_0.6 ]; then
  git clone -q --depth 1 --branch v0.6.0 https://github.com/huggingface/lerobot.git lerobot_0.6
  git -C lerobot_0.6 apply "$WORKSPACE/xlerobot/vendor/lerobot-0.6.patch"
fi
pip install -q -e "lerobot_0.6[training,smolvla]"

echo "== 5/5 환경변수 ($WORKSPACE/env.sh)"
# 받은 모델·데이터셋도 영구 볼륨에 둡니다 (재시작 때 3GB 를 다시 안 받게).
cat > env.sh <<EOF
source $WORKSPACE/venv/bin/activate
export HF_HOME=$WORKSPACE/cache/huggingface
export TORCH_HOME=$WORKSPACE/cache/torch
export USER=\${USER:-xlerobot}
cd $WORKSPACE/xlerobot
EOF

# shellcheck disable=SC1091
source env.sh
python -c "import torch; print('torch', torch.__version__, 'GPU:', torch.cuda.is_available() and torch.cuda.get_device_name(0))"

cat <<EOF

✓ 준비 끝. 이제:

  source $WORKSPACE/env.sh
  STEPS=20 OUTPUT_DIR=/tmp/probe ./scripts/train.sh act        # 메모리 확인 (mem_gb)
  ./scripts/train.sh smolvla                                     # 본 학습

학습 결과: $WORKSPACE/xlerobot/outputs/train/
EOF
