#!/usr/bin/env bash
# 설치가 어디서 어긋났는지 한 번에 모읍니다. 아무것도 바꾸지 않습니다.
#   bash /workspace/xlerobot/docker/isaaclab/steps/diag.sh
set -eo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./common.sh
activate_env

step "1. 어떤 파이썬을 쓰고 있나"
info "CONDA_PREFIX  = ${CONDA_PREFIX:-(없음)}"
info "which python  = $(command -v python || echo '(없음)')"
python -c "import sys; print('       sys.executable=', sys.executable)"
python -c "import sys; print('       version       =', sys.version.split()[0])"

step "2. conda 환경에 뭐가 깔려 있나"
pip list 2>/dev/null | grep -iE "^(isaac|torch|triton|stable|rsl|rl-games|skrl)" | sed 's/^/       /' \
  || info "(해당 패키지 없음)"

step "3. isaaclab 계열 import"
for m in isaacsim isaaclab isaaclab_tasks isaaclab_rl isaaclab_assets isaaclab_mimic; do
  if python -c "import ${m}" 2>/dev/null; then
    ok "${m}"
  else
    bad "${m}  →  $(python -c "import ${m}" 2>&1 | tail -1)"
  fi
done

step "4. 소스 트리와 editable 설치 흔적"
if [[ -d "${ISAACLAB_PATH}/source" ]]; then
  ls -1 "${ISAACLAB_PATH}/source" | sed 's/^/       /'
  info "setup.py 보유 여부:"
  for d in "${ISAACLAB_PATH}"/source/*/; do
    [[ -f "${d}setup.py" ]] && echo "         O  ${d}" || echo "         X  ${d}"
  done
else
  bad "${ISAACLAB_PATH}/source 가 없습니다"
fi
info "site-packages 의 editable 연결:"
python - <<'PY'
import site, pathlib
found = False
for d in site.getsitepackages():
    p = pathlib.Path(d)
    for f in list(p.glob("__editable__*")) + list(p.glob("*.pth")):
        if "isaaclab" in f.name.lower() or "isaac" in f.name.lower():
            print("        ", f.name)
            found = True
if not found:
    print("         (isaaclab editable 흔적 없음)")
PY

step "5. 다른 파이썬에 잘못 깔렸는지"
for py in /usr/bin/python3 /usr/bin/python; do
  if [[ -x "${py}" ]]; then
    n="$(${py} -m pip list 2>/dev/null | grep -ci isaaclab || true)"
    if [[ "${n}" != "0" ]]; then
      warn "${py} 에 isaaclab 이 깔려 있습니다 (conda 가 아니라 여기로 들어갔을 수 있음)"
      ${py} -m pip list 2>/dev/null | grep -i isaac | sed 's/^/         /'
    else
      ok "${py} — isaaclab 없음 (정상)"
    fi
  fi
done

step "6. 지난 설치 로그"
if [[ -f "${STATE_DIR}/isaaclab_install.log" ]]; then
  info "${STATE_DIR}/isaaclab_install.log 에서 에러만 추립니다:"
  grep -nE "ERROR|error:|Failed|No module|Traceback|Successfully installed isaaclab" \
    "${STATE_DIR}/isaaclab_install.log" | tail -30 | sed 's/^/       /' || info "(해당 줄 없음)"
else
  info "(아직 로그 없음 — 40_isaaclab.sh 를 새 버전으로 다시 돌리면 남습니다)"
fi

echo
info "이 출력을 그대로 공유해 주세요."
