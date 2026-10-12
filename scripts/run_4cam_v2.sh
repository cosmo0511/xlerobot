#!/usr/bin/env bash
# =============================================================================
# run_4cam_v2.sh — 빨강/노랑 재수집(2026-10-12~) 전용 진입점.
# =============================================================================
#
# run_4cam.sh 와 **하는 일이 같습니다.** 다른 건 하나뿐입니다:
# 데이터셋 이름을 `xlerobot-dice-4cam-v2` 로 **못 박습니다**.
#
#   ./scripts/run_4cam_v2.sh check
#   ./scripts/run_4cam_v2.sh record red    8 --first
#   ./scripts/run_4cam_v2.sh record yellow 8
#   ./scripts/run_4cam_v2.sh status
#
# 하위 명령(scan/identify/selftest/host/check/teleop/record/infer/status/
# droplast/view)과 인자는 run_4cam.sh 와 똑같습니다 — 그쪽 머리말을 보세요.
# `--first` 는 **record 의 인자**입니다. check 에 붙이면 preflight 가 거부합니다.
#
# ■ 왜 따로 있나
# ---------------------------------------------------------------------------
# 2026-10-12 에 주사위를 파랑 -> 노랑으로 바꿨습니다 (지시문 blue -> yellow).
# 예전 96개(`xlerobot-dice-4cam`, 빨강/파랑)와 **절대 섞이면 안 됩니다** — 지시문이
# 3종이 되면 "색 단어 하나만 다른 두 지시문" 이라는 실험 조건이 깨집니다
# (COLLECTING.md 2절). 이름이 눈에 보이는 진입점을 따로 두는 게 안전합니다.
#
#   이 스크립트         -> bilimili/xlerobot-dice-4cam-v2   (빨강/노랑, 새로 찍는 것)
#   DATASET_SUFFIX= 로  -> bilimili/xlerobot-dice-4cam      (빨강/파랑, 예전 96개)
#
# 카메라 목록도, 녹화 명령도 여기 안 적습니다. config/cameras.4cam.yaml 과
# scripts/record.sh 한 곳에만 있습니다.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 이 스크립트의 요점. dataset_path.sh 가 이걸 읽어 REPO_ID 를 정합니다.
# (dataset_path.sh 의 기본값도 -v2 지만, 기본값이 나중에 바뀌어도 이 진입점은
#  계속 v2 를 가리키도록 여기서 못 박습니다.)
export DATASET_SUFFIX="-v2"

exec "$SCRIPT_DIR/run_4cam.sh" "$@"
