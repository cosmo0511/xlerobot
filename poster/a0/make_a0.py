"""A0 포스터 (841 x 1189 mm) - 파란 헤더 / 색 띠 섹션 제목 / 회색 그림 패널 양식.
python3 make_a0.py  ->  poster_a0.html  (render_a0.js 로 PDF)
"""
import math, os

HERE = os.path.dirname(os.path.abspath(__file__))
BLUE, BLUE2, ACT, VLA, INK, SUB = "#1d4e9a", "#3a74c4", "#2f64b5", "#e8662e", "#1f2329", "#555b64"


# ---------------- 헤더 장식: 점으로 된 구 ----------------
def globe():
    dots = []
    R, cx, cy = 150, 160, 160
    tilt = math.radians(-25)
    for la in range(-80, 81, 10):
        n = max(6, int(36 * math.cos(math.radians(la))))
        for k in range(n):
            lo = 2 * math.pi * k / n + la * 0.02
            x = math.cos(math.radians(la)) * math.cos(lo)
            y = math.sin(math.radians(la))
            z = math.cos(math.radians(la)) * math.sin(lo)
            y, z = y * math.cos(tilt) - z * math.sin(tilt), y * math.sin(tilt) + z * math.cos(tilt)
            if z < -0.15:
                continue
            r = 1.2 + 4.2 * max(0, z)
            op = 0.18 + 0.55 * max(0, z)
            dots.append(f'<ellipse cx="{cx + R * x:.1f}" cy="{cy - R * y:.1f}" rx="{r * (0.6 + 0.4 * abs(x)):.2f}" ry="{r:.2f}" fill="#fff" opacity="{op:.2f}"/>')
    return f'<svg class="globe" viewBox="0 0 320 320">{"".join(dots)}</svg>'


# ---------------- 그림 1: 분산 제어 구조 ----------------
def fig_system():
    def box(x, title, col, lines):
        t = [f'<rect x="{x}" y="0" width="120" height="70" rx="4" fill="#fff" stroke="{col}" stroke-width="0.8"/>',
             f'<path d="M{x} 4 a4 4 0 0 1 4 -4 h112 a4 4 0 0 1 4 4 v9 h-120z" fill="{col}"/>',
             f'<text x="{x + 60}" y="9.6" text-anchor="middle" fill="#fff" font-size="7" font-weight="700">{title}</text>']
        y = 24
        for s, w, c in lines:
            if s:
                t.append(f'<text x="{x + 60}" y="{y}" text-anchor="middle" font-size="6.2" font-weight="{w}" fill="{c}">{s}</text>')
            y += 9 if s else 4
        return "".join(t)
    a = box(0, "라즈베리파이 (로봇 호스트)", BLUE, [("연산 없음 · 센서/모터 중계", 400, SUB), ("", 0, 0),
                                              ("카메라 4대", 700, INK), ("640×480, 30 fps", 400, SUB), ("모터 15개", 700, INK), ("양팔 12 · 바퀴 3", 400, SUB)])
    b = box(214, "PC (GPU, 정책 실행)", VLA, [("ACT / SmolVLA", 700, INK), ("행동 청크 50스텝", 400, SUB), ("", 0, 0),
                                             ("제어 주기 30 Hz", 700, INK), ("학습 데이터 fps와 같음", 400, SUB)])
    mid = (f'<line x1="124" y1="26" x2="208" y2="26" stroke="{INK}" stroke-width="0.7" marker-end="url(#ah)"/>'
           f'<text x="167" y="21" text-anchor="middle" font-size="6.2" font-weight="700">관측</text>'
           f'<text x="167" y="33" text-anchor="middle" font-size="5.6" fill="{SUB}">영상 + 관절</text>'
           f'<line x1="208" y1="50" x2="124" y2="50" stroke="{INK}" stroke-width="0.7" marker-end="url(#ah)"/>'
           f'<text x="167" y="45" text-anchor="middle" font-size="6.2" font-weight="700">행동</text>'
           f'<text x="167" y="57" text-anchor="middle" font-size="5.6" fill="{SUB}">15차원, 1스텝씩</text>')
    defs = f'<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10z" fill="{INK}"/></marker></defs>'
    return f'<svg viewBox="0 -1 334 72">{defs}{a}{mid}{b}</svg>'


# ---------------- 그림 2: 같은 장면, 다른 지시 ----------------
def fig_task():
    out = []
    for i, (word, wc, arm) in enumerate([("red", "#d03a2f", "왼팔"), ("yellow", "#b07a00", "오른팔")]):
        x = i * 171
        out.append(f'<rect x="{x}" y="0" width="163" height="64" rx="3" fill="#fff" stroke="#d3d8e0" stroke-width="0.5"/>')
        out.append(f'<text x="{x + 81.5}" y="12" text-anchor="middle" font-size="6.3">"Pick up the <tspan fill="{wc}" font-weight="700">{word}</tspan> dice</text>')
        out.append(f'<text x="{x + 81.5}" y="20.5" text-anchor="middle" font-size="6.3">and put it in the basket"</text>')
        out.append(f'<rect x="{x + 43}" y="28" width="13" height="13" rx="1.5" fill="#d7312b"/>')
        out.append(f'<rect x="{x + 61}" y="28" width="41" height="13" rx="1.5" fill="#fff" stroke="#9aa2ad" stroke-width="0.5"/>')
        out.append(f'<text x="{x + 81.5}" y="36.6" text-anchor="middle" font-size="5" fill="{SUB}">바구니</text>')
        out.append(f'<rect x="{x + 107}" y="28" width="13" height="13" rx="1.5" fill="#f2c318"/>')
        out.append(f'<text x="{x + 81.5}" y="55" text-anchor="middle" font-size="7.2" font-weight="700" fill="{BLUE}">→ {arm}</text>')
    return f'<svg viewBox="0 0 334 64">{"".join(out)}</svg>'


# ---------------- 그림 4: 단계별 성공률 ----------------
def fig_stages():
    cats = ["베이스 도달", "팔 움직임", "파지", "바구니 투입", "지시 색상 일치"]
    act = [67.5, 85.0, 67.5, 62.5, None]
    vla = [97.5, 100, 100, 97.5, 50.0]
    x0, x1, y0, y1 = 20, 332, 16, 112
    h = y1 - y0
    o = []
    for v in (0, 25, 50, 75, 100):
        y = y1 - h * v / 100
        o.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="{"#9aa2ad" if v == 0 else "#dfe3e8"}" stroke-width="{0.5 if v == 0 else 0.3}"/>')
        o.append(f'<text x="{x0 - 3}" y="{y + 2:.1f}" text-anchor="end" font-size="5.4" fill="{SUB}">{v}</text>')
    gw = (x1 - x0) / 5
    for i, c in enumerate(cats):
        gx = x0 + gw * i + gw / 2
        for j, (vals, col) in enumerate([(act, ACT), (vla, VLA)]):
            v = vals[i]
            if v is None:
                o.append(f'<text x="{gx - 11}" y="{y1 - 3}" text-anchor="middle" font-size="4.6" fill="{SUB}">해당 없음</text>')
                continue
            bx = gx - 22 + j * 23
            by = y1 - h * v / 100
            o.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="21" height="{y1 - by:.1f}" fill="{col}"/>')
            o.append(f'<text x="{bx + 10.5:.1f}" y="{by - 2:.1f}" text-anchor="middle" font-size="5.6" font-weight="700" fill="{INK}">{v:.1f}</text>')
        o.append(f'<text x="{gx:.1f}" y="{y1 + 9}" text-anchor="middle" font-size="6.4" fill="{INK}">{c}</text>')
    o.append(f'<rect x="{x1 - 92}" y="1" width="6" height="6" fill="{ACT}"/><text x="{x1 - 84}" y="6.4" font-size="6">ACT</text>')
    o.append(f'<rect x="{x1 - 56}" y="1" width="6" height="6" fill="{VLA}"/><text x="{x1 - 48}" y="6.4" font-size="6">SmolVLA</text>')
    return f'<svg viewBox="0 0 334 124">{"".join(o)}</svg>'


# ---------------- 그림 5: 입력 교체 시 뒤집힘 ----------------
def fig_swap():
    rows = [("잡음 (난수 시드)", 0.6), ("지시문 (반대 색)", 1.3), ("영상 (반대 배치)", 58.7),
            ("관절 상태 (반대 배치)", 45.2), ("영상 (같은 배치)", 51.3), ("관절 상태 (같은 배치)", 47.8)]
    x0, x1, top = 96, 324, 20
    w = x1 - x0
    o = []
    for v in (0, 25, 50, 75, 100):
        x = x0 + w * v / 100
        o.append(f'<line x1="{x:.1f}" y1="{top - 2}" x2="{x:.1f}" y2="{top + 6 * 15}" stroke="{"#9aa2ad" if v == 0 else "#dfe3e8"}" stroke-width="{0.5 if v == 0 else 0.3}"/>')
        o.append(f'<text x="{x:.1f}" y="{top - 5}" text-anchor="middle" font-size="5.4" fill="{SUB}">{v}</text>')
    o.append(f'<text x="{x1}" y="5" text-anchor="end" font-size="5.4" fill="{SUB}">예측 팔이 뒤집힌 비율 (%)</text>')
    for i, (lab, v) in enumerate(rows):
        y = top + i * 15 + 3
        hi = lab.startswith("지시문")
        o.append(f'<text x="{x0 - 4}" y="{y + 7}" text-anchor="end" font-size="6.2" fill="{INK}">{lab}</text>')
        bw = max(0.8, w * v / 100)
        o.append(f'<rect x="{x0}" y="{y}" width="{bw:.1f}" height="9.5" fill="{VLA if hi else ACT}"/>')
        o.append(f'<text x="{x0 + bw + 2.5:.1f}" y="{y + 7}" font-size="6" font-weight="700" fill="{VLA if hi else INK}">{v}</text>')
    return f'<svg viewBox="0 0 334 112">{"".join(o)}</svg>'


# ---------------- 왜 언어가 불리한가: 타임라인 ----------------
def fig_timeline():
    pts = [(10, "0초", "출발"), (95, "", "주행"), (180, "", "접근"), (250, "23.6초", "팔이 갈림"), (322, "", "파지")]
    o = [f'<line x1="10" y1="20" x2="322" y2="20" stroke="#9aa2ad" stroke-width="1"/>',
         f'<rect x="250" y="16.5" width="72" height="7" fill="{VLA}" opacity="0.25"/>',
         f'<text x="130" y="10" text-anchor="middle" font-size="5.6" fill="{SUB}">지시와 무관하게 행동이 같은 구간</text>',
         f'<text x="286" y="10" text-anchor="middle" font-size="5.6" fill="{VLA}" font-weight="700">언어가 필요한 구간</text>']
    for x, t, lab in pts:
        hi = t == "23.6초"
        o.append(f'<circle cx="{x}" cy="20" r="{3.2 if hi else 2.4}" fill="{VLA if hi else BLUE}"/>')
        o.append(f'<text x="{x}" y="32" text-anchor="middle" font-size="6.2" fill="{INK}" font-weight="{700 if hi else 400}">{lab}</text>')
        if t:
            o.append(f'<text x="{x}" y="40" text-anchor="middle" font-size="5.6" fill="{SUB}">{t}</text>')
    return f'<svg viewBox="0 0 334 42">{"".join(o)}</svg>'


# ---------------- 방법 아이콘 ----------------
ICON = {
    "data": '<ellipse cx="20" cy="9" rx="13" ry="5"/><path d="M7 9v10c0 3 6 5 13 5s13-2 13-5V9"/><path d="M7 19v10c0 3 6 5 13 5s13-2 13-5V19"/>',
    "train": '<rect x="9" y="9" width="22" height="22" rx="2"/><rect x="15" y="15" width="10" height="10"/><path d="M14 4v5M20 4v5M26 4v5M14 31v5M20 31v5M26 31v5M4 14h5M4 20h5M4 26h5M31 14h5M31 20h5M31 26h5"/>',
    "eval": '<circle cx="20" cy="20" r="14"/><circle cx="20" cy="20" r="8"/><circle cx="20" cy="20" r="2.5" fill="currentColor"/>',
    "swap": '<path d="M6 13h24l-6-6M34 27H10l6 6"/>',
}


def icon(k):
    return f'<svg class="ic" viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">{ICON[k]}</svg>'


html = open(os.path.join(HERE, "template.html"), encoding="utf8").read()
for k, v in {
    "{{GLOBE}}": globe(), "{{FIG_SYSTEM}}": fig_system(), "{{FIG_TASK}}": fig_task(),
    "{{FIG_STAGES}}": fig_stages(), "{{FIG_SWAP}}": fig_swap(), "{{FIG_TIMELINE}}": fig_timeline(),
    "{{IC_DATA}}": icon("data"), "{{IC_TRAIN}}": icon("train"), "{{IC_EVAL}}": icon("eval"), "{{IC_SWAP}}": icon("swap"),
}.items():
    html = html.replace(k, v)
open(os.path.join(HERE, "poster_a0.html"), "w", encoding="utf8").write(html)
print("ok")
