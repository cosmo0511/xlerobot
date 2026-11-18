# -*- coding: utf-8 -*-
"""주사위 좌우 판별 — HSV 색 분할 + 모양 필터.

책상 위 빨강/노랑 주사위의 중심 x 를 비교해 어느 쪽이 왼쪽인지 돌려준다.
화면 중앙선을 쓰지 않으므로 로봇 출발 위치가 달라도 그대로 동작한다.

단독 실행:
    python dice_vision.py <이미지들...>        판정 출력
    python dice_vision.py --debug <이미지>      마스크 그림 저장
"""
from __future__ import annotations
import cv2, numpy as np

# ── 색 범위 (OpenCV HSV: H 0~179) ──────────────────────────────────────
RANGES = {
    "red":    [((0, 90, 70), (10, 255, 255)), ((160, 90, 70), (179, 255, 255))],
    "yellow": [((20, 90, 110), (45, 255, 255))],
}
# ── 주사위로 인정할 모양 ───────────────────────────────────────────────
AREA_MIN, AREA_MAX = 40, 900     # 픽셀
ASPECT_MIN, ASPECT_MAX = 0.50, 2.10   # 가로/세로. 테이프는 길쭉해서 여기서 걸림
EXTENT_MIN = 0.55                # 면적 / 바운딩박스 면적. 비스듬한 테이프는 낮다.
                                 # 실측: 주사위 0.64~0.82, 테이프 0.35~0.46.
                                 # 0.45~0.64 는 결과가 모두 같아 빈 구간 한가운데를 골랐다.
ROI_Y_MAX  = 180                 # 이 아래(바닥)는 아예 보지 않는다. 주사위는 책상 위에만 있다
SAME_ROW_TOL = 70                # 두 주사위 y 차이 허용치
MIN_X_GAP = 12                   # 좌우로 인정할 최소 x 차이


def _mask(hsv, color):
    m = None
    for lo, hi in RANGES[color]:
        part = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
        m = part if m is None else (m | part)
    # 열기(open) 만 2회. 테이프는 폭이 몇 픽셀뿐이라 여기서 끊겨 사라지고,
    # 속이 찬 주사위는 살아남는다. 닫기(close)는 일부러 쓰지 않는다 —
    # 닫기를 넣으면 주사위와 테이프 사이 틈을 메워 한 덩어리로 붙여 버린다.
    # 2회인 이유: 1회도 정답 수는 같지만, 주사위와 테이프 사이 채움 간격이
    # 0.12 에서 0.25 로 넓어진다. 3회는 너무 깎여 오히려 나빠진다.
    k = np.ones((3, 3), np.uint8)
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, k, iterations=2)


def find_dice(hsv, color):
    """가장 주사위다운 덩어리 하나. 없으면 None."""
    mask = _mask(hsv, color)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in cnts:
        a = cv2.contourArea(c)
        if not (AREA_MIN <= a <= AREA_MAX):
            continue
        x, y, w, h = cv2.boundingRect(c)
        if h == 0 or w == 0:
            continue
        aspect, extent = w / h, a / (w * h)
        if not (ASPECT_MIN <= aspect <= ASPECT_MAX) or extent < EXTENT_MIN:
            continue
        M = cv2.moments(c)
        if M["m00"] == 0:
            continue
        if M["m01"] / M["m00"] > ROI_Y_MAX:      # 바닥(나무결·바닥 테이프) 제외
            continue
        cand = {"x": M["m10"] / M["m00"], "y": M["m01"] / M["m00"],
                "area": a, "aspect": aspect, "extent": extent, "box": (x, y, w, h)}
        # 꽉 차 있고 정사각형에 가까울수록 좋은 후보로 본다.
        # 면적은 일부러 넣지 않는다 — 넣으면 주사위보다 큰 테이프 조각이
        # 모양이 덜 주사위다워도 점수에서 이겨 버린다(ep083 에서 실제로 그랬다).
        cand["score"] = extent * (1.0 - abs(1.0 - aspect) * 0.5)
        if best is None or cand["score"] > best["score"]:
            best = cand
    return best


def detect_side(frame_bgr, color):
    """color 주사위가 'left' 인지 'right' 인지. 못 정하면 (None, 이유)."""
    if color not in RANGES:
        return None, f"모르는 색: {color}"
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    r, y = find_dice(hsv, "red"), find_dice(hsv, "yellow")
    if r is None and y is None:
        return None, "주사위를 둘 다 못 찾음"
    if r is None:
        return None, "빨강 주사위를 못 찾음"
    if y is None:
        return None, "노랑 주사위를 못 찾음"
    if abs(r["y"] - y["y"]) > SAME_ROW_TOL:
        return None, f"두 주사위 높이 차 {abs(r['y']-y['y']):.0f}px — 같은 줄이 아님"
    if abs(r["x"] - y["x"]) < MIN_X_GAP:
        return None, f"좌우 차이 {abs(r['x']-y['x']):.0f}px — 너무 가까움"
    tgt, oth = (r, y) if color == "red" else (y, r)
    side = "left" if tgt["x"] < oth["x"] else "right"
    why = (f"빨강 x={r['x']:.0f} / 노랑 x={y['x']:.0f} → {color}={'왼쪽' if side=='left' else '오른쪽'}")
    return side, why


def debug_image(frame_bgr):
    """마스크와 채택된 덩어리를 그려 넣은 그림."""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    vis = frame_bgr.copy()
    for color, bgr in (("red", (0, 0, 255)), ("yellow", (0, 255, 255))):
        vis[_mask(hsv, color) > 0] = bgr
        d = find_dice(hsv, color)
        if d:
            x, y, w, h = d["box"]
            cv2.rectangle(vis, (x - 4, y - 4), (x + w + 4, y + h + 4), (0, 255, 0), 1)
            cv2.putText(vis, color[0].upper(), (x - 4, y - 7),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
    return vis


if __name__ == "__main__":
    import sys, os
    args = sys.argv[1:]
    if args and args[0] == "--debug":
        for p in args[1:]:
            im = cv2.imread(p)
            out = os.path.splitext(p)[0] + "_debug.png"
            cv2.imwrite(out, cv2.resize(debug_image(im), None, fx=2, fy=2,
                                        interpolation=cv2.INTER_NEAREST))
            print("  저장:", out)
    else:
        for p in args:
            im = cv2.imread(p)
            side, why = detect_side(im, "red")
            print(f"  {os.path.basename(p):<34s} red={str(side):<6s} {why}")
