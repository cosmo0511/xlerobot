#!/usr/bin/env bash
# 4단계 — Isaac Lab v2.3.1 클론 + ./isaaclab.sh -i
# 끝에서 torch 를 다시 핀으로 되돌립니다. -i 가 RL 라이브러리를 깔면서
# torch 를 갈아치우는 경우가 있어서입니다.
set -eo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./common.sh
skip_if_done 40_isaaclab
activate_env

step "Isaac Lab ${ISAACLAB_REF} 소스"
if [[ -d "${ISAACLAB_PATH}/.git" ]]; then
  current="$(git -C "${ISAACLAB_PATH}" describe --tags --always 2>/dev/null || echo unknown)"
  ok "이미 있음: ${ISAACLAB_PATH} (${current})"
  if [[ "${current}" != "${ISAACLAB_REF}" ]]; then
    warn "${ISAACLAB_REF} 가 아닙니다. 체크아웃을 시도합니다."
    git -C "${ISAACLAB_PATH}" fetch --depth 1 origin "refs/tags/${ISAACLAB_REF}:refs/tags/${ISAACLAB_REF}" || true
    git -C "${ISAACLAB_PATH}" -c advice.detachedHead=false checkout "${ISAACLAB_REF}"
  fi
else
  mkdir -p "$(dirname "${ISAACLAB_PATH}")"
  # ${ISAACLAB_PATH} 가 도커 volume 의 마운트 지점이면 비어 있어도 디렉터리는 존재합니다.
  # git clone 은 "비어 있는" 디렉터리면 그대로 받아들이므로 그 경우는 문제없습니다.
  # 다만 이전 클론이 중간에 끊겨 찌꺼기가 남으면 거부되므로 먼저 알려줍니다.
  if [[ -d "${ISAACLAB_PATH}" ]] && [[ -n "$(ls -A "${ISAACLAB_PATH}" 2>/dev/null || true)" ]]; then
    bad "${ISAACLAB_PATH} 가 비어 있지 않은데 git 저장소도 아닙니다 (중단된 클론으로 보입니다)."
    info "  안을 비우고 다시 돌리세요:  rm -rf ${ISAACLAB_PATH}/{*,.[!.]*}"
    exit 1
  fi
  git clone --depth 1 --branch "${ISAACLAB_REF}" \
      https://github.com/isaac-sim/IsaacLab.git "${ISAACLAB_PATH}" \
    || die "클론 실패"
  ok "클론 완료"
fi

# RL 프레임워크 선택. 기본값은 공식 문서와 같은 all.
#   rsl_rl 만 쓸 거면 ISAACLAB_RL_FRAMEWORK=rsl_rl 로 두세요 — 아래 sb3 충돌이 사라집니다.
ISAACLAB_RL_FRAMEWORK="${ISAACLAB_RL_FRAMEWORK:-all}"
INSTALL_LOG="${STATE_DIR}/isaaclab_install.log"
mkdir -p "${STATE_DIR}"

step "./isaaclab.sh -i ${ISAACLAB_RL_FRAMEWORK}"
info "로그: ${INSTALL_LOG}"
info "몇 분 걸립니다."
# isaaclab.sh 는 확장 설치를 `find ... -exec bash -c` 서브셸로 돌리는데, 거기서 실패해도
# 스크립트 종료코드에 반영되지 않습니다. 그래서 로그를 남기고 아래에서 직접 검증합니다.
set +e
( cd "${ISAACLAB_PATH}" && ./isaaclab.sh -i "${ISAACLAB_RL_FRAMEWORK}" ) 2>&1 | tee "${INSTALL_LOG}"
rc=${PIPESTATUS[0]}
set -e
[[ ${rc} -eq 0 ]] || warn "isaaclab.sh -i 가 ${rc} 로 끝났습니다. 아래 검증 결과를 보세요."

step "확장이 실제로 이 환경에 깔렸는지 확인"
# ★ isaaclab.sh -i 가 '성공'으로 끝나도 isaaclab 이 안 깔리는 경우가 있습니다.
#   (확장 설치가 서브셸에서 조용히 건너뛰어짐) 직접 확인하고, 아니면 직접 깝니다.
if python -c "import isaaclab" 2>/dev/null; then
  ok "isaaclab import 통과"
else
  warn "isaaclab 이 import 되지 않습니다. source/ 의 확장을 직접 설치합니다."
  for d in "${ISAACLAB_PATH}"/source/*/; do
    [[ -f "${d}setup.py" || -f "${d}pyproject.toml" ]] || continue
    name="$(basename "${d}")"
    info "pip install -e ${name}"
    python -m pip install -e "${d}" --no-build-isolation 2>&1 | tail -3       || warn "${name} 설치 실패 (로그 확인)"
  done
  python -c "import isaaclab" 2>/dev/null     && ok "직접 설치 후 import 통과"     || die "여전히 isaaclab 을 import 할 수 없습니다. bash steps/diag.sh 결과를 확인하세요."
fi

step "torchaudio 복구"
# isaaclab.sh 의 ensure_cuda_torch() 는 매번 이렇게 합니다:
#     pip uninstall -y torch torchvision torchaudio
#     pip install -U --index-url <cuda index> torch torchvision
# torchaudio 를 지우고 다시 깔지 않습니다. 그런데 isaacsim-core 5.1.0 은
# torchaudio==2.7.0 을 요구하므로 여기서 복구합니다.
if python -c "import importlib.metadata as m; m.version('torchaudio')" 2>/dev/null; then
  ok "torchaudio 있음"
elif pip install "torchaudio==${TORCH_VERSION}" --index-url "${TORCH_INDEX}" >/dev/null 2>&1; then
  ok "torchaudio ${TORCH_VERSION} 복구 (${TORCH_CUDA_TAG})"
elif pip install "torchaudio==${TORCH_VERSION}" >/dev/null 2>&1; then
  warn "torchaudio 를 기본 PyPI 에서 설치했습니다 (CUDA 빌드가 torch 와 다를 수 있음)"
else
  warn "torchaudio 를 설치하지 못했습니다. isaacsim-core 가 의존성 경고를 냅니다."
  info "  Isaac Lab 사용에는 보통 지장이 없지만, isaacsim 쪽에서 문제가 생기면 수동 설치하세요."
fi

step "의존성 충돌 점검"
# sb3 최신판은 torch>=2.8 을 요구하는데 Isaac Lab 2.3.1 은 torch 2.7.0 에 고정돼 있습니다.
conflicts="$(pip check 2>&1 | grep -v "^No broken requirements" || true)"
if [[ -n "${conflicts}" ]]; then
  warn "pip check 가 보고한 충돌:"
  echo "${conflicts}" | sed 's/^/         /'
  if grep -q "stable-baselines3" <<<"${conflicts}"; then
    info "  stable-baselines3 는 Isaac Lab 2.3.1 의 torch 핀(2.7.0)과 맞지 않는 상위 문제입니다."
    info "  sb3 를 안 쓸 거면 무시해도 되고, 아예 빼려면:"
    info "    FORCE=1 ISAACLAB_RL_FRAMEWORK=rsl_rl bash steps/40_isaaclab.sh"
  fi
else
  ok "충돌 없음"
fi

step "torch 재핀"
# ★ 이 단계가 핵심입니다. -i 가 torch 를 바꿔놨는지 보고 되돌립니다.
before="$(python -c 'import torch; print(torch.__version__)')"
info "현재: ${before}"
if [[ "${before}" == "${TORCH_VERSION}"* ]]; then
  ok "그대로입니다"
else
  warn "${TORCH_VERSION} 에서 ${before} 로 바뀌었습니다. 되돌립니다."
  pip install -U "torch==${TORCH_VERSION}" "torchvision==${TORCHVISION_VERSION}" \
      --index-url "${TORCH_INDEX}" || die "torch 재설치 실패"
fi

step "검증"
TORCH_VERSION="${TORCH_VERSION}" EXPECTED_TORCH_CUDA="${EXPECTED_TORCH_CUDA}" python - <<'PY'
import os, sys, torch, isaaclab, isaaclab_tasks
print(f"       python       {sys.version.split()[0]}")
print(f"       torch        {torch.__version__}  (cuda {torch.version.cuda})")
print(f"       isaaclab     {getattr(isaaclab, '__version__', 'ok')}")
assert torch.__version__.startswith(os.environ["TORCH_VERSION"]), torch.__version__
assert torch.version.cuda == os.environ["EXPECTED_TORCH_CUDA"], torch.version.cuda
PY
ok "isaaclab / isaaclab_tasks import + 핀 일치"

mark_done 40_isaaclab
echo
ok "완료 — steps/50_verify.sh 로 넘어가세요"
