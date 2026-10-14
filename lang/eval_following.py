#!/usr/bin/env python3
"""지시를 얼마나 잘 따르는지 측정한다.

로봇이 지시대로 움직였는지는 사람이 봐야 안다. 이 도구는 시행을 무작위로
섞어 내주고, 결과를 받아 적어, 끝나면 혼동 행렬과 따름률을 계산한다.

    python eval_following.py                  기본 20회
    python eval_following.py --trials 40
    python eval_following.py --report 결과.json   저장한 결과만 다시 보기

진행 방식
    1. 화면에 "이번 지시: 파랑" 이 뜬다
    2. 추론 스크립트에서 그 지시를 주고 로봇을 돌린다
    3. 로봇이 실제로 무엇을 집었는지 키로 입력한다
    4. 20회 반복 후 집계
"""

import argparse
import json
import random
import sys
from collections import Counter, defaultdict

from lang_parser import TASKS

C = {"r": "\033[0m", "b": "\033[1m", "dim": "\033[2m", "ok": "\033[32m",
     "w": "\033[33m", "no": "\033[31m", "hi": "\033[36m"}
if not sys.stdout.isatty():
    C = dict.fromkeys(C, "")


def report(trials):
    """혼동 행렬과 지표를 출력한다."""
    keys = [s["key"] for s in TASKS]
    label = {s["key"]: s["label"] for s in TASKS}
    label["none"] = "아무것도"
    label["other"] = "엉뚱한 것"

    cm = defaultdict(Counter)
    for t in trials:
        cm[t["given"]][t["observed"]] += 1

    cols = keys + ["none", "other"]
    print(f"\n{C['b']}혼동 행렬{C['r']}   {C['dim']}행=지시한 것, 열=실제로 집은 것{C['r']}")
    print("  " + " " * 10 + "".join(f"{label[c]:>10s}" for c in cols) + f"{'합계':>8s}")
    print("  " + "-" * (10 + 10 * len(cols) + 8))
    for g in keys:
        row = cm[g]
        tot = sum(row.values())
        cells = ""
        for c in cols:
            v = row.get(c, 0)
            mark = C["ok"] if (c == g and v) else (C["no"] if v and c != g else C["dim"])
            cells += f"{mark}{v:>10d}{C['r']}"
        print(f"  {label[g]:<10s}{cells}{tot:>8d}")

    print(f"\n{C['b']}지표{C['r']}")
    total = len(trials)
    correct = sum(cm[g].get(g, 0) for g in keys)
    print(f"  전체 따름률        {C['b']}{correct}/{total} = {correct / total * 100:5.1f}%{C['r']}"
          if total else "  시행 없음")
    for g in keys:
        tot = sum(cm[g].values())
        if not tot:
            continue
        ok = cm[g].get(g, 0)
        print(f"    {label[g]:<8s} 지시 시    {ok}/{tot} = {ok / tot * 100:5.1f}%")

    # 치우침 — 지시를 무시하고 한쪽만 집는지
    picked = Counter(t["observed"] for t in trials if t["observed"] in keys)
    if len(picked) == 1 and total >= 6:
        only = next(iter(picked))
        print(f"\n  {C['no']}지시와 무관하게 항상 '{label[only]}' 만 집었습니다.{C['r']}")
        print(f"  {C['dim']}언어가 전혀 반영되지 않는 상태입니다. 데이터 균형과 지시문 표기를 확인하세요.{C['r']}")
    elif total >= 6 and correct / total < 0.6:
        print(f"\n  {C['w']}따름률이 60% 미만입니다.{C['r']}")
        print(f"  {C['dim']}에피소드 수를 늘리거나, 지시문이 학습 때와 똑같은지 확인하세요.{C['r']}")
    elif total >= 6:
        print(f"\n  {C['ok']}지시를 구분하고 있습니다.{C['r']}")


def main():
    p = argparse.ArgumentParser(description="지시 따름 평가")
    p.add_argument("--trials", type=int, default=20, help="시행 횟수")
    p.add_argument("--save", default="following_result.json")
    p.add_argument("--report", default=None, help="저장된 결과만 다시 집계")
    args = p.parse_args()

    if args.report:
        trials = json.load(open(args.report))
        report(trials)
        return

    keys = [s["key"] for s in TASKS]
    label = {s["key"]: s["label"] for s in TASKS}
    # 지시를 균등하게 섞는다
    order = (keys * ((args.trials // len(keys)) + 1))[:args.trials]
    random.shuffle(order)

    opts = "".join(f"  {C['b']}{k[0].upper()}{C['r']}={label[k]}" for k in keys)
    print(f"\n{C['b']}지시 따름 평가{C['r']}  —  {args.trials}회")
    print(f"  각 시행마다 지시가 나옵니다. 그 지시로 로봇을 돌린 뒤,")
    print(f"  로봇이 실제로 집은 것을 입력하세요.")
    print(f"  입력:{opts}   {C['b']}N{C['r']}=아무것도   {C['b']}O{C['r']}=엉뚱한것   {C['b']}S{C['r']}=건너뛰기   {C['b']}Q{C['r']}=중단\n")

    trials = []
    try:
        for i, g in enumerate(order, 1):
            task = next(s["task"] for s in TASKS if s["key"] == g)
            print(f"  {C['b']}[{i}/{args.trials}]{C['r']}  지시: "
                  f"{C['hi']}{label[g]}{C['r']}   \"{task}\"")
            while True:
                a = input("     실제로 집은 것 > ").strip().lower()
                if a == "q":
                    raise KeyboardInterrupt
                if a == "s":
                    print(f"     {C['dim']}건너뜀{C['r']}\n")
                    break
                obs = None
                for k in keys:
                    if a == k[0] or a == k:
                        obs = k
                if a == "n":
                    obs = "none"
                if a == "o":
                    obs = "other"
                if obs is None:
                    print(f"     {C['w']}모르는 입력입니다.{C['r']}")
                    continue
                trials.append({"given": g, "observed": obs})
                mark = f"{C['ok']}맞음{C['r']}" if obs == g else f"{C['no']}틀림{C['r']}"
                print(f"     → {label.get(obs, obs)}  {mark}\n")
                break
    except (KeyboardInterrupt, EOFError):
        print("\n  중단")

    if not trials:
        print("  기록된 시행이 없습니다.")
        return
    json.dump(trials, open(args.save, "w"), ensure_ascii=False, indent=2)
    print(f"  {C['dim']}저장: {args.save}{C['r']}")
    report(trials)


if __name__ == "__main__":
    main()
