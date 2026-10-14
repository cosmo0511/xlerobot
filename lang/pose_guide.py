#!/usr/bin/env python3
"""에피소드마다 리더암을 똑같은 자세로 맞추도록 도와준다. (PC 에서 실행)

왜 필요한가
    녹화 중 팔로워는 리더를 그대로 따라간다. 그래서 팔로워를 고정하려면
    리더를 고정 자세에 두는 수밖에 없다. 그런데 사람이 손으로 잡고 있으면
    매번 조금씩 달라진다.

    이 도구는 목표 자세와 지금 자세의 차이를 실시간으로 보여준다.
    리셋 시간 동안 화면을 보며 리더를 움직여 전부 초록이 되면 녹화를 시작한다.

    python pose_guide.py --save              지금 자세를 목표로 저장
    python pose_guide.py                     목표에 맞추도록 안내
    python pose_guide.py --tol 15            허용 오차를 15 로 (기본 25)

주의
    * 리더암은 PC 에 꽂혀 있어야 한다.
    * 녹화(lerobot-record)와 동시에 쓸 수 없다. 같은 포트를 못 나눠 쓴다.
      리셋 시간에 쓰려면 녹화를 잠시 멈추거나, 녹화 전에 자세를 맞춰 두고 시작한다.
"""

import argparse
import json
import os
import sys
import time

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex",
          "wrist_flex", "wrist_roll", "gripper"]
PORTS = {"left": "/dev/so101_leader_left", "right": "/dev/so101_leader_right"}
TARGET_FILE = os.path.expanduser("~/.cache/lerobot_pose_target.json")

ADDR_POS = (56, 2)          # Present_Position, 2바이트
FULL = 4096                 # 엔코더 한 바퀴

C = {"r": "\033[0m", "b": "\033[1m", "dim": "\033[2m", "ok": "\033[32m",
     "w": "\033[33m", "no": "\033[31m", "hi": "\033[36m"}
if not sys.stdout.isatty():
    C = dict.fromkeys(C, "")


def motors():
    m = {n: Motor(i + 1, "sts3215", MotorNormMode.RANGE_M100_100)
         for i, n in enumerate(JOINTS)}
    return m


def open_buses():
    buses = {}
    for side, port in PORTS.items():
        if not os.path.exists(port):
            print(f"  {C['w']}{port} 가 없습니다. 건너뜁니다.{C['r']}")
            continue
        b = FeetechMotorsBus(port=port, motors=motors())
        try:
            b.connect(handshake=False)
            buses[side] = b
        except Exception as e:
            print(f"  {C['no']}{port} 열기 실패: {e}{C['r']}")
    return buses


def read_pose(buses):
    """각 팔의 관절 위치를 원시값으로 읽는다."""
    out = {}
    for side, bus in buses.items():
        pkt = bus.packet_handler
        vals = {}
        for i, name in enumerate(JOINTS, start=1):
            d, c, e = pkt.readTxRx(bus.port_handler, i, *ADDR_POS)
            vals[name] = int.from_bytes(bytes(d), "little") if c == 0 and d else None
        out[side] = vals
    return out


def diff(now, target):
    """엔코더가 한 바퀴(4096)를 돌므로 가까운 쪽으로 차이를 잰다."""
    if now is None or target is None:
        return None
    d = (now - target) % FULL
    return d - FULL if d > FULL // 2 else d


def bar(d, tol, width=21):
    """가운데가 0. 왼쪽/오른쪽으로 치우친 정도를 보여준다."""
    if d is None:
        return " " * width
    half = width // 2
    span = max(tol * 6, 60)
    pos = int(round(half + max(-half, min(half, d / span * half))))
    cells = ["─"] * width
    cells[half] = "│"
    cells[pos] = "●"
    return "".join(cells)


def close(buses):
    for b in buses.values():
        try:
            b.port_handler.closePort()
        except Exception:
            pass


def cmd_save(buses):
    pose = read_pose(buses)
    bad = [f"{s}/{j}" for s, v in pose.items() for j, p in v.items() if p is None]
    if bad:
        print(f"  {C['no']}읽지 못한 관절: {', '.join(bad)}{C['r']}")
        return 1
    os.makedirs(os.path.dirname(TARGET_FILE), exist_ok=True)
    json.dump(pose, open(TARGET_FILE, "w"), indent=2)
    print(f"  {C['ok']}지금 자세를 목표로 저장했습니다.{C['r']}  {C['dim']}{TARGET_FILE}{C['r']}\n")
    for side, v in pose.items():
        print(f"  [{side}]  " + "  ".join(f"{j[:5]}={p}" for j, p in v.items()))
    return 0


def cmd_guide(buses, tol):
    if not os.path.exists(TARGET_FILE):
        print(f"  {C['no']}목표 자세가 없습니다.{C['r']}")
        print(f"  {C['dim']}원하는 자세로 리더를 두고 먼저 저장하세요:  python {sys.argv[0]} --save{C['r']}")
        return 1
    target = json.load(open(TARGET_FILE))
    sides = [s for s in PORTS if s in buses and s in target]

    print(f"\n{C['b']}자세 맞추기{C['r']}   허용 오차 ±{tol}   {C['dim']}Ctrl+C 로 종료{C['r']}")
    print(f"  {C['dim']}리더암을 움직여 모든 줄이 초록이 되게 하세요.{C['r']}\n")

    lines = 0
    try:
        while True:
            now = read_pose(buses)
            rows, all_ok = [], True
            for side in sides:
                rows.append(f"  {C['b']}[{side}]{C['r']}")
                for j in JOINTS:
                    d = diff(now[side].get(j), target[side].get(j))
                    if d is None:
                        rows.append(f"    {j:<15s} {C['no']}읽기 실패{C['r']}")
                        all_ok = False
                        continue
                    ok = abs(d) <= tol
                    all_ok &= ok
                    col = C["ok"] if ok else (C["w"] if abs(d) <= tol * 3 else C["no"])
                    arrow = "맞음" if ok else ("◀ 줄이기" if d > 0 else "늘리기 ▶")
                    rows.append(f"    {j:<15s} {col}{bar(d, tol)}{C['r']} "
                                f"{col}{d:+6d}{C['r']}  {arrow}")
            rows.append("")
            rows.append(f"  {C['ok'] + '✔ 모두 맞았습니다. 녹화를 시작하세요.' if all_ok else C['w'] + '… 맞추는 중'}{C['r']}")

            if lines:
                sys.stdout.write(f"\033[{lines}A")
            for r in rows:
                sys.stdout.write("\033[2K" + r + "\n")
            lines = len(rows)
            sys.stdout.flush()
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n종료")
    return 0


def main():
    p = argparse.ArgumentParser(description="리더암 자세 맞추기 도우미")
    p.add_argument("--save", action="store_true", help="지금 자세를 목표로 저장")
    p.add_argument("--tol", type=int, default=25, help="허용 오차(엔코더 값, 기본 25 ≈ 2도)")
    a = p.parse_args()

    buses = open_buses()
    if not buses:
        print(f"  {C['no']}리더암을 하나도 열지 못했습니다.{C['r']}")
        print(f"  {C['dim']}USB 연결과 전원을 확인하세요.{C['r']}")
        return 1
    try:
        return cmd_save(buses) if a.save else cmd_guide(buses, a.tol)
    finally:
        close(buses)


if __name__ == "__main__":
    sys.exit(main())
