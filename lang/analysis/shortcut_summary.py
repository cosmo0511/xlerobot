"""shortcut_probe.py 결과(csv)를 모델별로 다시 요약합니다. 화면을 스크롤할 필요 없이 한 번에 보기용.

    python lang/analysis/shortcut_summary.py [results/offline_shortcut.csv]
"""
import csv, sys
from collections import defaultdict

path = sys.argv[1] if len(sys.argv) > 1 else "results/offline_shortcut.csv"
rows = list(csv.DictReader(open(path)))
by = defaultdict(dict)
for r in rows:
    by[(r["model"], r["phase"], r["cond"])][(r["episode"], r["offset"])] = r

models = list(dict.fromkeys(r["model"] for r in rows))
for m in models:
    eps = {r["episode"] for r in rows if r["model"] == m}
    cells = defaultdict(int)
    for r in rows:
        if r["model"] == m and r["cond"] == "원본" and r["offset"] == "-5":
            cells[(r["color"], r["arm"])] += 1
    print(f"\n=== {m}  (에피소드 {len(eps)}: " + ", ".join(f"{c}-{a} {n}" for (c, a), n in sorted(cells.items())) + ")")
    for phase in ("결정 전", "분기 후"):
        base = by[(m, phase, "원본")]
        n = len(base)
        if not n:
            continue
        ok = sum(r["pred_arm"] == r["arm"] for r in base.values())
        right = sum(r["pred_arm"] == "R" for r in base.values())
        print(f"  [{phase}] 프레임 {n} · 원본 정답 팔 {ok}/{n} ({100*ok/n:.1f}%) · 오른팔 예측 {right}/{n}")
        for cond in ("잡음(시드)", "지시문 교체", "영상 교체", "상태 교체"):
            c = by.get((m, phase, cond))
            if not c:
                continue
            flip = sum(c[k]["pred_arm"] != base[k]["pred_arm"] for k in base if k in c)
            print(f"    {cond:<8s} 뒤집힘 {flip}/{n} ({100*flip/n:.1f}%)")
