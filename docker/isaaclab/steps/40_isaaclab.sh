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

step "./isaaclab.sh -i (확장 + RL 라이브러리 전부)"
info "rl_games / rsl_rl / sb3 / skrl 까지 깔립니다. 몇 분 걸립니다."
( cd "${ISAACLAB_PATH}" && ./isaaclab.sh -i ) || die "isaaclab.sh -i 실패"

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
