#!/usr/bin/env bash
# 3단계 — PyTorch 2.7.0 + torchvision 0.22.0 (cu128)
# isaacsim 이 끌고 온 torch 를 지정 버전으로 덮어씁니다.
set -eo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./common.sh
skip_if_done 30_torch
activate_env

step "현재 torch"
python - <<'PY' || true
try:
    import torch
    print(f"       {torch.__version__}  (cuda {torch.version.cuda})")
except ImportError:
    print("       (없음)")
PY

step "torch==${TORCH_VERSION} / torchvision==${TORCHVISION_VERSION} (${TORCH_CUDA_TAG})"
pip install -U "torch==${TORCH_VERSION}" "torchvision==${TORCHVISION_VERSION}" \
    --index-url "${TORCH_INDEX}" \
  || die "torch 설치 실패"

step "검증"
TORCH_VERSION="${TORCH_VERSION}" EXPECTED_TORCH_CUDA="${EXPECTED_TORCH_CUDA}" python - <<'PY'
import os, sys, torch
want, want_cuda = os.environ["TORCH_VERSION"], os.environ["EXPECTED_TORCH_CUDA"]
print(f"       torch        {torch.__version__}")
print(f"       built cuda   {torch.version.cuda}")
print(f"       available    {torch.cuda.is_available()}")
if torch.cuda.is_available():
    free, total = torch.cuda.mem_get_info()
    print(f"       GPU          {torch.cuda.get_device_name(0)}  "
          f"({total // 1024**2} MiB, {free // 1024**2} MiB 여유)")
assert torch.__version__.startswith(want), f"{torch.__version__} != {want}"
assert torch.version.cuda == want_cuda, f"{torch.version.cuda} != {want_cuda}"
PY
ok "핀 일치"

# cuda.is_available() 이 False 면 뒤 단계가 전부 무의미하니 여기서 끊습니다.
python -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)" \
  || die "torch 가 GPU 를 못 봅니다. 컨테이너면 --gpus all / nvidia-container-toolkit 을 확인하세요."
ok "GPU 접근 가능"

mark_done 30_torch
echo
ok "완료 — steps/40_isaaclab.sh 로 넘어가세요"
