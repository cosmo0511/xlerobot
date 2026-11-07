#!/usr/bin/env bash
# 캔바 가져오기용 PPTX 만들기: 일반 PPTX -> PDF 렌더 -> 차트 부분을 300dpi 그림으로 잘라 -> 캔바용 PPTX
set -euo pipefail
cd "$(dirname "$0")"
python3 make_pptx.py
python3 to_pdf.py poster_100x180.pptx _canva/render.pdf 2>/dev/null
python3 - <<'PY'
import json, subprocess
b = json.load(open("_canva/chart_boxes.json"))
EMU_PER_IN = 914400; DPI = 300
for name, (x, y, w, h) in b["charts"].items():
    px = lambda v: str(round(v / EMU_PER_IN * DPI))
    subprocess.run(["pdftoppm", "-r", str(DPI), "-png", "-singlefile", "-x", px(x), "-y", px(y),
                    "-W", px(w), "-H", px(h), "_canva/render.pdf", "_canva/" + name], check=True)
PY
POSTER_CANVA=1 POSTER_OUT=poster_100x180_canva.pptx python3 make_pptx.py
echo "ok: poster_100x180_canva.pptx"
