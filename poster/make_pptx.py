"""학회 포스터 PPTX 생성 (실물 100 x 180 cm).

PowerPoint 슬라이드 최대 크기(142 cm) 때문에 슬라이드는 절반인 50 x 90 cm 로 만든다.
아래 좌표·글자 크기는 모두 '실물 기준'으로 적고 S(=0.5)를 곱해 넣는다.
인쇄는 PDF(100 x 180 cm)로, 또는 PPTX 를 200% 로 출력.
"""
import math, os
HERE = os.path.dirname(os.path.abspath(__file__))
from pptx import Presentation
from pptx.util import Cm, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_LABEL_POSITION
from pptx.oxml.ns import qn
from lxml import etree

S = 0.5
W, H = 100, 180
# POSTER_FONT=malgun : 맑은 고딕 (Windows 기본, 설치 불필요) / 기본: Pretendard (PDF 인쇄용)
MALGUN = os.environ.get("POSTER_FONT", "") == "malgun"
FONT = "Malgun Gothic" if MALGUN else "Pretendard"
# POSTER_CANVA=1 : 캔바 가져오기용. 글꼴 이름을 "Pretendard" 하나로(굵기는 굵게 속성), 차트는 그림으로,
#                  말풍선은 기본 도형으로 바꾼다. (캔바는 "Pretendard ExtraBold" 같은 이름·네이티브 차트를 잘 못 읽음)
CANVA = os.environ.get("POSTER_CANVA", "") == "1"
FONT_XB = "Malgun Gothic" if MALGUN else ("Pretendard" if CANVA else "Pretendard ExtraBold")
EA = {"Malgun Gothic": "맑은 고딕"}
OUT = os.environ.get("POSTER_OUT", os.path.join(HERE, "poster_100x180.pptx"))


def rgb(h):
    return RGBColor.from_string(h.lstrip("#"))


C = dict(
    main="1D4F91", dark="153B6E", tint="E4ECF7", pill="D5E2F3",
    ink="1E2227", sub="4B525C", line="1D4F91",
    act="1D4F91", vla="E8662E", pre="A9BAD3",
)

prs = Presentation()
prs.slide_width = Cm(W * S)
prs.slide_height = Cm(H * S)
slide = prs.slides.add_slide(prs.slide_layouts[6])
sh = slide.shapes


def cm(v):
    return Cm(v * S)


def pt(v):
    return Pt(v * S)


def no_line(shape):
    shape.line.fill.background()


def rect(x, y, w, h, fill=None, line=None, lw=4, shape=MSO_SHAPE.RECTANGLE, radius=None, dash=False):
    s = sh.add_shape(shape, cm(x), cm(y), cm(w), cm(h))
    if radius is not None:
        s.adjustments[0] = radius
    if fill:
        s.fill.solid(); s.fill.fore_color.rgb = rgb(fill)
    else:
        s.fill.background()
    if line:
        s.line.color.rgb = rgb(line); s.line.width = pt(lw)
        if dash:
            s.line.dash_style = 4  # dash
    else:
        no_line(s)
    s.shadow.inherit = False
    tf = s.text_frame
    tf.text = ""
    return s


def set_font(run, size, bold=False, color="ink", font=None):
    f = run.font
    f.size = pt(size); f.bold = bold
    f.color.rgb = rgb(C.get(color, color))
    name = font or FONT
    if (MALGUN or CANVA) and font == FONT_XB:
        f.bold = True
    f.name = name
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = etree.SubElement(rPr, qn(tag))
        el.set("typeface", EA.get(name, name))


def text(x, y, w, h, paras, size=40, color="ink", align=PP_ALIGN.LEFT, spacing=1.2,
         anchor=MSO_ANCHOR.TOP, bold=False, font=None, space_after=0):
    """paras: list of paragraphs; each paragraph = str or list of (text, opts) runs.
    paragraph may also be dict(runs=..., bullet=True, size=.., color=..)."""
    tb = sh.add_textbox(cm(x), cm(y), cm(w), cm(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    bodyPr = tf._txBody.find(qn("a:bodyPr"))
    for i, p in enumerate(paras):
        opts = {}
        if isinstance(p, dict):
            opts = p; runs = p["runs"]
        else:
            runs = p
        if isinstance(runs, str):
            runs = [(runs, {})]
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = opts.get("align", align)
        para.line_spacing = opts.get("spacing", spacing)
        if space_after or opts.get("after"):
            para.space_after = pt(opts.get("after", space_after))
        if opts.get("before"):
            para.space_before = pt(opts["before"])
        psize = opts.get("size", size)
        if opts.get("bullet"):
            pPr = para._p.get_or_add_pPr()
            ind = int(cm(1.25))
            pPr.set("marL", str(ind)); pPr.set("indent", str(-ind))
            bu = etree.SubElement(pPr, qn("a:buChar")); bu.set("char", "•")
        for t, o in runs:
            r = para.add_run(); r.text = t
            set_font(r, o.get("size", psize), o.get("bold", opts.get("bold", bold)),
                     o.get("color", opts.get("color", color)), o.get("font", font))
    return tb


def chart_fonts(chart):
    """차트 안 모든 글자에 라틴·한글 글꼴을 함께 지정 (없으면 한글이 대체 글꼴로 나옴)."""
    cs = chart._chartSpace
    for d in list(cs.iter(qn("a:defRPr"))) + list(cs.iter(qn("a:rPr"))):
        for tag in ("a:latin", "a:ea", "a:cs"):
            el = d.find(qn(tag))
            if el is None:
                el = etree.SubElement(d, qn(tag))
            el.set("typeface", EA.get(FONT, FONT) if tag == "a:ea" else FONT)


import json
CHART_BOXES = {}
CANVA_DIR = os.path.join(HERE, "_canva")


def as_picture(gf, name):
    """캔바용: 차트 자리를 미리 렌더링한 그림으로 바꾼다 (make_canva.sh 가 그림을 만든다)."""
    CHART_BOXES[name] = [gf.left, gf.top, gf.width, gf.height]
    if CANVA:
        rid = gf.chart_part.partname and gf._element.xpath(".//c:chart/@r:id")[0]
        el = gf._element; el.getparent().remove(el)
        slide.part.drop_rel(rid)
        sh.add_picture(os.path.join(CANVA_DIR, name + ".png"), gf.left, gf.top, gf.width, gf.height)


def line(x1, y1, x2, y2, color="sub", lw=4, arrow=False, dash=False):
    c = sh.add_connector(MSO_CONNECTOR.STRAIGHT, cm(x1), cm(y1), cm(x2), cm(y2))
    c.line.color.rgb = rgb(C.get(color, color)); c.line.width = pt(lw)
    ln = c.line._get_or_add_ln()
    if dash:
        prst = etree.SubElement(ln, qn("a:prstDash")); prst.set("val", "dash")
    if arrow:
        te = etree.SubElement(ln, qn("a:tailEnd")); te.set("type", "triangle"); te.set("w", "med"); te.set("len", "med")
    return c


def pill(x, y, w, h, label, size=34, fill="pill", color="dark", bold=True):
    s = rect(x, y, w, h, fill=C.get(fill, fill), shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.5)
    tf = s.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = label
    set_font(r, size, bold, color)
    return s


# ---- 텍스트 높이 대략 추정 (배치용) -------------------------------------
from PIL import ImageFont
_F = {}


def est_lines(s, size, width):
    """실제 폰트(Regular)로 단어 단위 줄바꿈을 흉내 내 줄 수를 센다."""
    key = round(size * 4)
    if key not in _F:
        _F[key] = ImageFont.truetype(os.path.join(HERE, "fonts/Pretendard-Regular.ttf"), size * 4)
    f = _F[key]
    maxw = width / 2.54 * 72 * 4 * 0.94  # 맑은 고딕이 조금 더 넓어 여유를 둠
    n, cur = 1, 0.0
    sp = f.getlength(" ")
    for word in s.split(" "):
        wl = f.getlength(word)
        add = wl if cur == 0 else sp + wl
        if cur + add <= maxw:
            cur += add
        elif wl <= maxw:
            n += 1; cur = wl
        else:  # 아주 긴 단어: 글자 단위
            n += 1; cur = 0
            for ch in word:
                cl = f.getlength(ch)
                if cur + cl > maxw:
                    n += 1; cur = cl
                else:
                    cur += cl
    return n


def est_h(paras, size, width, spacing=1.2, bullet=False):
    em = size / 72 * 2.54
    n = 0
    for p in paras:
        s = p if isinstance(p, str) else "".join(t for t, _ in p)
        n += est_lines(s, size, width - (1.25 if bullet else 0))
    return n * em * spacing * 1.16  # Pretendard 줄 높이 (LibreOffice ≈1.12, PowerPoint 여유 포함)


# ============================ 헤더 ============================
HEAD = 29
rect(0, 0, W, HEAD, fill=C["main"])
# 장식: 오른쪽에 옅은 원호 (로봇팔 관절 느낌의 절제된 장식)
rect(0, HEAD, W, 0.6, fill=C["dark"])

text(6, 4.0, 90, 13, [[("양팔 이동 조작 정책의 조작 성능과", {})], [("언어 지시 추종의 괴리", {})]],
     size=150, color="FFFFFF", font=FONT_XB, spacing=1.08)
text(6, 19.6, 56, 6, [[("Dissociation between Manipulation Performance and Language Instruction Following", {})], [("in a Bimanual Mobile Manipulation Policy", {})]],
     size=40, color="DCE6F4", spacing=1.25)
text(58, 20.0, 36, 3, [[("김미송*, 김송연*, 최명기*, 김현우†, 조혜경*", {})]], size=46, color="FFFFFF", align=PP_ALIGN.RIGHT, bold=True)
text(58, 23.6, 36, 3, [[("*한성대학교 AI응용학과   †주식회사 로보시지", {})]], size=38, color="DCE6F4", align=PP_ALIGN.RIGHT)

# ============================ 본문 레이아웃 ============================
M = 6            # 좌우 바깥 여백
GAP = 3          # 단 사이
CW = (W - 2 * M - GAP) / 2   # 단 너비 42.5
PAD = 2.6        # 박스 안쪽 여백
IW = CW - 2 * PAD
BODY = 32        # 본문 글자 (실물 pt)
SMALL = 30
TOP = HEAD + 3.8
BOTTOM = 171.5

col_x = [M, M + CW + GAP]


class Box:
    """둥근 테두리 박스 안에 위에서부터 차례로 쌓는다."""

    def __init__(self, col, y, title):
        self.x = col_x[col]; self.y0 = y
        self.cx = self.x + PAD
        self.y = y + 2.3
        text(self.cx, self.y, IW, 4, [[(title, {})]], size=86, color="main", font=FONT_XB, spacing=1.0)
        self.y += 4.6
        self.items = []

    def gap(self, v):
        self.y += v

    def para(self, paras, size=BODY, color="ink", spacing=1.2, bullet=False, after=0.7, width=None, x=None):
        w = width or IW
        PG = 16  # 문단 사이 간격 (실물 pt)
        h = est_h(paras, size, w, spacing, bullet) + (len(paras) - 1) * PG / 72 * 2.54
        ps = [dict(runs=p, bullet=bullet, after=PG if k < len(paras) - 1 else 0) for k, p in enumerate(paras)]
        text(x if x is not None else self.cx, self.y, w, h + 0.5, ps, size=size, color=color, spacing=spacing)
        self.y += h + after
        return h

    def sub(self, label, size=50):
        text(self.cx, self.y, IW, 2.6, [[("▶ " + label, {})]], size=size, color="main", bold=True, spacing=1.0)
        self.y += 2.9

    def close(self, extra=1.6):
        h = self.y - self.y0 + extra
        b = rect(self.x, self.y0, CW, h, line=C["line"], lw=5, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.035)
        # 테두리를 맨 뒤로
        sp = b._element; sp.getparent().remove(sp); sh._spTree.insert(2, sp)
        return self.y0 + h


def B(t):
    return (t, {"bold": True})


def N(t):
    return (t, {})


def O(t):
    return (t, {"bold": True, "color": "vla"})


GV = 2.2   # 박스 사이 세로 간격


def caption(bx, s_):
    bx.para([[N(s_)]], size=27, color="sub", spacing=1.1, after=0.2)


# ---------------------------- 왼쪽 단 ----------------------------
y = TOP
bx = Box(0, y, "연구 배경 및 목적")
bx.para([[N("저가형 로봇의 VLA(Vision-Language-Action) 정책 평가는 주로 고정형 단팔에서 이루어졌다. SO-101 비교 연구에서는 사전학습된 SmolVLA가 모방학습 정책인 ACT보다 대체로 우수한 조작 성능을 보였고, Mobile ALOHA는 이동 베이스와 양팔을 하나의 정책으로 학습했으나 언어 지시는 사용하지 않았다.")],
         [N("최근에는 높은 조작 성공률이 언어 지시 추종을 보장하지 않는다는 문제가 제기되고 있다. 입력 교란 분석에서 언어 지시의 영향은 제한적이었고, 언어 지시만 바꾸는 반사실적 실험에서는 시각 단서가 언어보다 행동 선택에 강하게 작용하였다.")],
         [N("양팔 로봇은 목표 물체에 따라 사용할 팔을 골라야 하므로, 언어 지시가 행동 결정에 반영되는지 직접 확인할 수 있다. 본 연구는 XLeRobot 기반 실제 양팔 이동 로봇에서 이를 평가한다.")]], after=1.2)
bx.gap(-1.5)  # 첫 문단이 추정보다 한 줄 짧게 렌더링됨 (괄호 속 긴 영문)
for tag, q in [("RQ1", "SmolVLA가 ACT보다 높은 조작 성능을 보이는가?"), ("RQ2", "언어 지시에 따라 올바른 팔을 선택하는가?")]:
    pill(bx.cx, bx.y, 6.2, 2.5, tag, size=36, fill="main", color="FFFFFF")
    text(bx.cx + 7.2, bx.y + 0.1, IW - 7.2, 2.5, [[N(q)]], size=BODY, spacing=1.1, anchor=MSO_ANCHOR.MIDDLE)
    bx.gap(3.3)
bx.gap(0.3)
bx.para([[N("또한 팔 선택 분기 전후로 언어·영상·관절 상태 입력을 하나씩 바꿔 정책이 무엇에 반응하는지 분석한다.")]], after=0.3)
y = bx.close() + GV

bx = Box(0, y, "시스템 구성")
bx.para([[N("로봇은 SO-ARM101 양팔과 3-옴니휠 베이스로 구성된다. 행동과 관측 상태는 양팔 관절 12개와 베이스 속도(x, y, θ) 3개의 15차원이며, 관측에는 카메라 4대(상단·베이스·양 손목, 30 fps)가 더해진다. 라즈베리파이는 연산 없이 센서·모터를 중계하고, PC가 정책을 실행해 행동 청크를 만든 뒤 30 Hz로 1스텝씩 보낸다. 명령이 500 ms 이상 끊기면 호스트가 팔을 고정하고 바퀴를 멈춘다. 학습·추론은 LeRobot을 사용하였다.")]], after=1.4)
fx, fy = bx.cx, bx.y
bw, bh = 14.2, 15.2
for i, (ttl, col, lines_) in enumerate([
    ("라즈베리파이", C["main"], ["로봇 호스트 · 연산 없음", "", "카메라 4대", "640×480, 30 fps", "", "모터 15개", "양팔 12 · 바퀴 3"]),
    ("PC (GPU)", C["vla"], ["정책 실행", "", "ACT / SmolVLA", "행동 청크 생성", "", "1스텝씩 전송", "제어 주기 30 Hz"]),
]):
    xx = fx if i == 0 else fx + IW - bw
    rect(xx, fy, bw, bh, fill="FFFFFF", line=col, lw=5, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
    rect(xx, fy, bw, 3.0, fill=col, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.3)
    text(xx, fy + 0.35, bw, 2.4, [[B(ttl)]], size=40, color="FFFFFF", align=PP_ALIGN.CENTER, spacing=1.0)
    paras = []
    for l in lines_:
        hd = l in ("카메라 4대", "모터 15개", "ACT / SmolVLA", "1스텝씩 전송")
        paras.append(dict(runs=[(l if l else " ", {"bold": hd})], size=31 if l else 14, color="ink" if hd else "sub", spacing=1.18))
    text(xx + 1.0, fy + 4.0, bw - 2.0, bh - 4.5, paras, size=31, align=PP_ALIGN.CENTER)
mx1, mx2 = fx + bw + 0.6, fx + IW - bw - 0.6
line(mx1, fy + 5.6, mx2, fy + 5.6, color="ink", lw=5, arrow=True)
text(mx1, fy + 2.9, mx2 - mx1, 2.4, [[B("관측")], [N("영상 + 관절")]], size=29, align=PP_ALIGN.CENTER, spacing=1.05)
line(mx2, fy + 10.6, mx1, fy + 10.6, color="ink", lw=5, arrow=True)
text(mx1, fy + 11.1, mx2 - mx1, 2.4, [[B("행동")], [N("15차원")]], size=29, align=PP_ALIGN.CENTER, spacing=1.05)
bx.y = fy + bh + 1.0
caption(bx, "그림 1. 분산 제어 구조. 무선은 평균 812 ms 지연으로 관측이 갱신되지 않아, 모든 평가는 유선(왕복 평균 2.8 ms)·30 Hz 고정에서 수행")
y = bx.close() + GV

bx = Box(0, y, "과제 및 실험 설정")
bx.para([[N("로봇은 1 m 앞 책상까지 이동한 뒤, 좌우에 놓인 빨강·노랑 주사위 중 지시된 색을 그쪽 팔로 집어 바구니에 넣는다. 지시문은 색 단어 하나만 다르고 두 주사위가 늘 함께 있어, 영상만으로는 어느 팔을 써야 할지 정할 수 없다.")]], after=1.2)

# ---- 그림 2: 같은 장면, 다른 지시 -> 다른 팔 ----
fx, fy = bx.cx, bx.y
PW = (IW - 1.6) / 2
PH = 20.4
RED, YEL, YTXT = "D7312B", "F2C318", "A27F00"
for i, (word, wcol, side) in enumerate([("red", RED, "L"), ("yellow", YTXT, "R")]):
    px = fx + i * (PW + 1.6)
    rect(px, fy, PW, PH, fill="F7F8FA", line="C9CED6", lw=3, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
    # 지시문 말풍선
    if CANVA:
        rect(px + 1.0, fy + 1.0, PW - 2.0, 5.0, fill="FFFFFF", line=C["main"], lw=4,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.2)
        tx = px + 1.0 + (PW - 2.0) * 0.32
        tri = rect(tx - 0.9, fy + 5.95, 1.8, 1.4, fill="FFFFFF", line=C["main"], lw=4, shape=MSO_SHAPE.ISOSCELES_TRIANGLE)
        tri.rotation = 180
        rect(tx - 0.72, fy + 5.7, 1.44, 0.5, fill="FFFFFF")  # 이음매 가리기
    else:
        bub = rect(px + 1.0, fy + 1.0, PW - 2.0, 5.0, fill="FFFFFF", line=C["main"], lw=4,
                   shape=MSO_SHAPE.ROUNDED_RECTANGULAR_CALLOUT)
        bub.adjustments[0] = -0.18; bub.adjustments[1] = 0.85
    text(px + 1.6, fy + 1.15, PW - 3.2, 4.7,
         [[N("“Pick up the "), (word, {"color": wcol}), N(" dice and put it in the basket”")]],
         size=28, spacing=1.05, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    # 책상 위 (로봇 시점): 왼쪽 빨강, 가운데 바구니, 오른쪽 노랑
    ty = fy + 8.2
    dl_x, dr_x = px + 2.3, px + PW - 2.3 - 2.6
    rect(dl_x, ty, 2.6, 2.6, fill=RED)
    rect(dr_x, ty, 2.6, 2.6, fill=YEL)
    bkx = px + PW / 2 - 2.6
    rect(bkx, ty - 0.2, 5.2, 3.0, fill="FFFFFF", line="6B7280", lw=4)
    text(bkx, ty + 0.4, 5.2, 1.8, [[N("바구니")]], size=24, color="sub", align=PP_ALIGN.CENTER)
    # 로봇 몸체
    rb_w, rb_h = 7.0, 4.0
    rbx, rby = px + PW / 2 - rb_w / 2, fy + PH - 6.8
    rect(rbx, rby, rb_w, rb_h, fill=C["dark"], shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.25)
    text(rbx, rby + 0.9, rb_w, 2.2, [[N("로봇")]], size=28, color="FFFFFF", align=PP_ALIGN.CENTER)
    # 팔: 쓰는 팔은 주황 굵은 화살표, 안 쓰는 팔은 회색 짧게
    lx0, rx0 = rbx + 0.6, rbx + rb_w - 0.6
    if side == "L":
        line(lx0, rby, dl_x + 1.3, ty + 3.0, color=C["vla"], lw=11, arrow=True)
        line(rx0, rby, rx0 + 0.8, rby - 2.2, color="B8BEC7", lw=9)
    else:
        line(rx0, rby, dr_x + 1.3, ty + 3.0, color=C["vla"], lw=11, arrow=True)
        line(lx0, rby, lx0 - 0.8, rby - 2.2, color="B8BEC7", lw=9)
    text(px + 0.6, rby + 1.0, 5.5, 2, [[N("왼팔")]], size=26, color="sub")
    text(px + PW - 6.1, rby + 1.0, 5.5, 2, [[N("오른팔")]], size=26, color="sub", align=PP_ALIGN.RIGHT)
    text(px, fy + PH - 2.5, PW, 2.2,
         [[N("정답: "), (("왼팔" if side == "L" else "오른팔"), {"color": "vla"}), N(" 사용")]],
         size=32, align=PP_ALIGN.CENTER, spacing=1.0)
bx.y = fy + PH + 1.0
caption(bx, "그림 2. 같은 장면이라도 지시문의 색 단어에 따라 써야 하는 팔이 바뀐다 (좌우 배치는 시행마다 바뀜)")
bx.gap(0.8)
for lab, body in [
    ("데이터", "텔레오퍼레이션으로 104 에피소드(평균 38.2초)를 수집했고 색상×팔은 26/26/26/26으로 균등하다. 두 팔의 동작은 중앙값 23.6초에서 갈라지며, 그 전까지는 지시와 무관하게 행동이 같다."),
    ("학습", "ACT와 SmolVLA를 같은 데이터로 batch 16, 80k 스텝 학습하였다."),
    ("평가", "모델당 40회(주사위 배치 2 × 시작 위치 2 × 지시 2, 각 5회). 단계별 성공을 독립 판정하고 Fisher 정확 검정과 이항 검정으로 비교하였다."),
]:
    text(bx.cx, bx.y, IW, 2, [[(lab, {"bold": True, "color": "main"})]], size=38, spacing=1.0)
    bx.y += 2.2
    bx.para([[N(body)]], after=0.9)
left_end = bx.close(extra=0.9)

# ---------------------------- 오른쪽 단 ----------------------------
y = TOP
bx = Box(1, y, "연구 결과")
cd = CategoryChartData()
cd.categories = ["베이스 도달", "팔 움직임", "파지", "바구니 투입", "지시 색상 일치"]
cd.add_series("ACT", (67.5, 85.0, 67.5, 62.5, None))
cd.add_series("SmolVLA", (97.5, 100, 100, 97.5, 50.0))
CH = 19
gf = sh.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, cm(bx.cx - 0.6), cm(bx.y), cm(IW + 1.2), cm(CH), cd)
ch = gf.chart
ch.font.size = pt(28); ch.font.name = FONT
ch.has_legend = True; ch.legend.position = XL_LEGEND_POSITION.TOP; ch.legend.include_in_layout = False
ch.legend.font.size = pt(30)
va = ch.value_axis; va.maximum_scale = 100; va.minimum_scale = 0; va.major_unit = 25
va.has_major_gridlines = True; va.major_gridlines.format.line.color.rgb = rgb("E1E5EA")
va.format.line.fill.background(); va.tick_labels.font.size = pt(26)
ca = ch.category_axis; ca.tick_labels.font.size = pt(30); ca.format.line.color.rgb = rgb("888888")
plot = ch.plots[0]; plot.gap_width = 55; plot.overlap = -8
plot.has_data_labels = True
dl = plot.data_labels; dl.font.size = pt(27); dl.number_format = '0.0'; dl.number_format_is_linked = False
dl.position = XL_LABEL_POSITION.OUTSIDE_END
for s_, col in zip(plot.series, [C["act"], C["vla"]]):
    s_.format.fill.solid(); s_.format.fill.fore_color.rgb = rgb(col)
chart_fonts(ch); as_picture(gf, "chart1")
bx.y += CH + 0.6
caption(bx, "그림 3. 단계별 성공률(%), 모델당 40회. ACT는 언어 입력을 받지 않으므로 지시 색상 일치는 SmolVLA만 해당")
bx.gap(0.8)
bx.para([[N("SmolVLA는 조작 네 단계 모두 ACT보다 유의하게 높았다(RQ1). 바구니 투입까지 성공한 비율은 SmolVLA 97.5%, ACT 62.5%였다. 그러나 지시 색상 일치율은 50.0%에 그쳤다(RQ2). 8개 조건 전부에서 지시와 관계없이 오른쪽 주사위를 집었고, 주사위 배치가 좌우 균형이라 산술적으로 50%가 된 것이다. ACT도 팔이 움직인 34회 중 32회(94.1%)가 오른팔이었다.")]], after=0.6)
bx.gap(0.2)
y = bx.close() + GV

bx = Box(1, y, "입력 민감도 분석")
bx.para([[N("팔 선택이 어떤 입력에 민감한지 보기 위해 학습 데이터 104 에피소드에서 입력을 하나씩 교체하였다. 사용한 팔의 관절이 처음 값에서 10° 이상 벗어난 첫 프레임을 분기 시점으로 두고, 분기 0.17·0.5·1.0초 전(312장면)과 0.5·1.5초 후(208장면)를 평가하였다.")],
         [N("예측한 50스텝 행동 청크에서 첫 스텝 대비 관절 변화량이 더 큰 팔을 예측 팔로 정했다. 같은 계산을 사람 시연에 적용하면 520장면 모두 실제 사용 팔과 일치한다. 교체 입력은 같은 색 지시이면서 주사위 배치가 반대인 짝 에피소드의 같은 시점에서 가져왔다.")]], after=0.6)
cd = CategoryChartData()
cd.categories = ["잡음", "지시문", "영상", "관절 상태"]
cd.add_series("분기 전", (0.6, 1.3, 58.7, 45.2))
cd.add_series("분기 후", (0.0, 0.0, 8.7, 91.3))
CH2 = 18
gf = sh.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, cm(bx.cx - 0.6), cm(bx.y), cm(IW + 1.2), cm(CH2), cd)
ch = gf.chart
ch.font.size = pt(28); ch.font.name = FONT
ch.has_legend = True; ch.legend.position = XL_LEGEND_POSITION.TOP; ch.legend.include_in_layout = False
ch.legend.font.size = pt(30)
va = ch.value_axis; va.maximum_scale = 100; va.minimum_scale = 0; va.major_unit = 25
va.has_major_gridlines = True; va.major_gridlines.format.line.color.rgb = rgb("E1E5EA")
va.tick_labels.font.size = pt(26); va.format.line.fill.background()
ca = ch.category_axis; ca.reverse_order = True; ca.tick_labels.font.size = pt(30)
plot = ch.plots[0]; plot.gap_width = 45; plot.overlap = -5
plot.has_data_labels = True
dl = plot.data_labels; dl.font.size = pt(27); dl.number_format = '0.0'; dl.number_format_is_linked = False
dl.position = XL_LABEL_POSITION.OUTSIDE_END
for s_, col in zip(plot.series, [C["pre"], C["dark"]]):
    s_.format.fill.solid(); s_.format.fill.fore_color.rgb = rgb(col)
chart_fonts(ch); as_picture(gf, "chart2")
bx.y += CH2 + 0.5
caption(bx, "그림 4. 입력 교체 시 예측 팔이 뒤집힌 비율(%). 잡음은 난수 시드만, 나머지는 반대 색·반대 배치 입력으로 교체")
bx.gap(1.0)
LW = 8.6
for lab, body in [
    ("지시문", "지시문만 바꾸면 출력이 달라져 계산에는 반영되지만, 예측 팔이 바뀐 비율은 1.3%(4/312)로 잡음 기준(0.6%)과 비슷했다."),
    ("영상·관절", "분기 전에는 영상(58.7%)과 관절 상태(45.2%), 분기 후에는 관절 상태(91.3%)의 영향이 지배적이었다. 분기 후는 이미 움직이기 시작한 팔의 동작이 이어지는 것으로, 팔을 고른 근거로 보기는 어렵다."),
    ("상태 복사", "관절값을 그대로 복사하기만 해도 오차가 1/4.3로 줄어(6.741→1.555) 정책이 줄인 오차의 84%에 해당한다. 상태 복사 문제와 비슷하나 직접 원인인지는 판단할 수 없다."),
    ("일반화", "학습 데이터에서는 예측 팔이 99.7% 맞았지만 실기에서는 오른팔만 썼다. 배치가 같은 다른 에피소드 입력으로 바꿔도 51.3%·47.8%가 뒤집혀, 에피소드별 장면·자세의 미세한 차이에 반응했을 가능성이 있다."),
]:
    pill(bx.cx, bx.y, LW, 2.7, lab, size=34)
    bx.para([[N(body)]], x=bx.cx + LW + 1.0, width=IW - LW - 1.0, spacing=1.16, after=1.1)
y = bx.close(extra=0.6) + GV

bx = Box(1, y, "결론")
bx.para([[N("SmolVLA는 조작 네 단계 모두 ACT보다 유의하게 높은 성공률을 보였으나, 지시 색상 일치율은 50.0%에 그쳤고 40회 모두 오른팔을 사용하였다. 입력 교체 실험에서도 지시문 변경은 예측 팔에 거의 영향을 주지 않았고, 영상과 관절 상태 변경에는 크게 반응하였다. 선행 연구에서 보고된 조작 성능과 언어 지시 추종의 괴리가 양팔 이동 조작에서도 나타나며, 두 능력은 분리해서 평가해야 한다.")]], after=1.2)
bx.para([[("한계  ", {"bold": True, "color": "main"}), N("실기 평가는 모델당 40회·단일 시드, 입력 교체 분석은 학습 데이터 대상, 과제는 단일 장면·단일 작업이다.")],
         [("향후  ", {"bold": True, "color": "main"}), N("같은 배치의 짝 에피소드 일부를 빼고 재학습해 에피소드별 미세한 차이에 의존하는지 확인하고, 주사위 배치와 초기 상태를 다양화해 일반화 성능을 확인할 예정이다.")]],
        size=BODY, spacing=1.2, after=0.4)
right_end = bx.close(extra=0.8)

print(f"left_end={left_end:.1f}  right_end={right_end:.1f}  (page H={H}, 하단 여백 목표 ~174)")
if not CANVA:
    os.makedirs(CANVA_DIR, exist_ok=True)
    json.dump({"slide_w": prs.slide_width, "slide_h": prs.slide_height, "charts": CHART_BOXES},
              open(os.path.join(CANVA_DIR, "chart_boxes.json"), "w"))
prs.save(OUT)
