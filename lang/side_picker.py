#!/usr/bin/env python3
"""탑 카메라 한 장으로 지시한 색 주사위가 왼쪽/오른쪽 어디 있는지 보고, 팔을 넣은 지시문을 만든다.

armtext 모델(bilimili/xlerobot-dice-4cam-v2-smolvla-armtext)은 relabel_arm.py 가 만든
지시문으로 학습됐다. 그래서 여기서 만드는 문장도 **글자 하나까지** 같아야 한다:

    color_arm : "Pick up the yellow dice with the left arm and put it in the basket"
    arm       : "Pick up the dice with the left arm and put it in the basket"   (armonly 모델)

판정 방법 (OpenCV HSV 임계값, 학습 없음)
    * 빨강·노랑 영역 중 가장 큰 덩어리의 중심 x 를 구한다.
    * 둘 다 보이면 서로 비교 (주사위는 항상 좌우에 하나씩 놓이므로 이게 제일 확실).
    * 지시한 색만 보이면 화면 가운데와 비교.
    * 탑캠 화면 왼쪽 = 로봇 왼쪽으로 본다. 카메라가 뒤집혀 달렸으면 --mirror.

단독 실행 (로봇 없이 시험):
    python lang/side_picker.py 사진.jpg yellow          판정 + outputs/side_check.jpg 에 표시 그림
    python lang/side_picker.py --test                   합성 그림으로 자체 시험
"""

import argparse
import os
import sys

import cv2
import numpy as np

# HSV (OpenCV: H 0~179). 빨강은 0 근처와 179 근처로 나뉜다.
# 조명이 바뀌어 못 찾으면 여기를 고친다. --save 로 마스크를 보면 맞추기 쉽다.
HSV_RANGES = {
    "red": [((0, 120, 70), (8, 255, 255)), ((170, 120, 70), (179, 255, 255))],
    "yellow": [((18, 100, 100), (35, 255, 255))],
}
MIN_AREA = 30          # px. 1m 떨어진 시작 위치에서도 주사위가 작게 보이므로 작게 잡는다

# relabel_arm.py 의 new_task() 와 같은 문장
TEMPLATES = {
    "color_arm": "Pick up the {color} dice with the {arm} arm and put it in the basket",
    "arm": "Pick up the dice with the {arm} arm and put it in the basket",
}


def find_dice(img_rgb: np.ndarray) -> dict:
    """{색: (cx, cy, 넓이)}. 못 찾은 색은 빠진다. 입력은 lerobot 카메라와 같은 RGB."""
    hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV)
    kernel = np.ones((3, 3), np.uint8)
    out = {}
    for color, ranges in HSV_RANGES.items():
        mask = np.zeros(hsv.shape[:2], np.uint8)
        for lo, hi in ranges:
            mask |= cv2.inRange(hsv, np.array(lo), np.array(hi))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        n, _, stats, cents = cv2.connectedComponentsWithStats(mask)
        if n <= 1:
            continue
        i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area >= MIN_AREA:
            out[color] = (float(cents[i][0]), float(cents[i][1]), area)
    return out


def pick_side(img_rgb: np.ndarray, color: str, mirror: bool = False) -> tuple[str | None, str]:
    """('left'/'right' 또는 None, 근거)."""
    found = find_dice(img_rgb)
    if color not in found:
        return None, f"{color} 주사위를 화면에서 못 찾음 (찾은 것: {list(found) or '없음'})"
    x = found[color][0]
    others = [v[0] for k, v in found.items() if k != color]
    if others:
        ref, how = others[0], "다른 색 주사위"
    else:
        ref, how = img_rgb.shape[1] / 2, "화면 가운데"
    side = "left" if x < ref else "right"
    if mirror:
        side = "right" if side == "left" else "left"
    return side, f"{color} x={x:.0f} vs {how} x={ref:.0f}" + (" (좌우 반전)" if mirror else "")


def make_task(color: str, side: str, mode: str = "color_arm") -> str:
    return TEMPLATES[mode].format(color=color, arm=side)


def draw(img_rgb: np.ndarray, color: str, side: str | None) -> np.ndarray:
    """판정 결과를 그린 BGR 그림 (저장용)."""
    vis = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    for c, (x, y, a) in find_dice(img_rgb).items():
        r = max(6, int((a ** 0.5)))
        cv2.circle(vis, (int(x), int(y)), r, (0, 255, 0) if c == color else (200, 200, 200), 2)
        cv2.putText(vis, c, (int(x) - r, int(y) - r - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(vis, f"{color} -> {side or '?'} arm", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    return vis


# ── 시험 ────────────────────────────────────────────────────────────────

def _synthetic(left_color, right_color, w=640, h=480):
    img = np.full((h, w, 3), 90, np.uint8)            # 회색 책상
    rgb = {"red": (220, 30, 30), "yellow": (230, 210, 30)}
    for color, cx in ((left_color, 200), (right_color, 440)):
        if color:
            cv2.rectangle(img, (cx - 15, 300), (cx + 15, 330), rgb[color], -1)
    return img


def self_test() -> bool:
    cases = [
        (("yellow", "red"), "yellow", "left"), (("yellow", "red"), "red", "right"),
        (("red", "yellow"), "yellow", "right"), (("red", "yellow"), "red", "left"),
        ((None, "yellow"), "yellow", "right"), (("red", None), "red", "left"),
        (("red", None), "yellow", None),
    ]
    ok = True
    for (lc, rc), want_color, want in cases:
        got, why = pick_side(_synthetic(lc, rc), want_color)
        mark = "✓" if got == want else "✗"
        ok &= got == want
        print(f"  {mark} 왼쪽={lc} 오른쪽={rc}  {want_color} → {got}  ({why})")
    t = make_task("yellow", "left")
    exp = "Pick up the yellow dice with the left arm and put it in the basket"
    ok &= t == exp
    print(f"  {'✓' if t == exp else '✗'} 지시문: {t}")
    return ok


def main():
    p = argparse.ArgumentParser(description="탑캠 사진으로 좌우 판정")
    p.add_argument("image", nargs="?")
    p.add_argument("color", nargs="?", choices=list(HSV_RANGES))
    p.add_argument("--mirror", action="store_true")
    p.add_argument("--mode", default="color_arm", choices=list(TEMPLATES))
    p.add_argument("--test", action="store_true")
    a = p.parse_args()
    if a.test or not a.image:
        sys.exit(0 if self_test() else 1)
    bgr = cv2.imread(a.image)
    if bgr is None:
        sys.exit(f"그림을 못 읽음: {a.image}")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    side, why = pick_side(rgb, a.color, a.mirror)
    print(f"판정: {side}  ({why})")
    if side:
        print(f"지시문: {make_task(a.color, side, a.mode)}")
    os.makedirs("outputs", exist_ok=True)
    cv2.imwrite("outputs/side_check.jpg", draw(rgb, a.color, side))
    print("표시 그림: outputs/side_check.jpg")


if __name__ == "__main__":
    main()
