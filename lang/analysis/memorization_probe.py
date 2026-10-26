"""학습 장면에서 99.7% 맞힌 이유 — 장면 암기(A)인가, 움직임 시작 흔적(B)인가. 로봇 없이 GPU 로만.

배경: 지시문을 바꿔도 예측 팔은 거의 안 바뀌는데(1.3%), 학습 데이터에서는 정답 팔을 99.7% 맞혔다.
      짝 에피소드는 배치가 같고 지시만 다르므로, 지시문을 안 보면 50% 근처여야 한다.

(A) 장면 암기   : 짝끼리의 미세한 장면 차이로 에피소드를 알아보고 외운 팔을 고른다
(B) 움직임 흔적 : 분기 시점(관절 10° 이상) 직전에 정답 팔이 이미 조금 움직이기 시작했고, 그걸 보고 이어간다

실험 1. 시점별로 나누기 — 분기 3·2·1·0.5·0.17초 전
        멀리 떨어진 시점(팔이 확실히 안 움직일 때)에도 정답률이 높으면 (A), 분기에 가까울수록 올라가면 (B).
        시점마다 사용 팔이 출발 자세에서 이미 얼마나 움직였는지(°)도 데이터에서 같이 낸다.
실험 2. 같은 배치 짝으로 교체
        "배치는 같고 지시·팔만 반대" 인 에피소드(red-L ↔ yellow-R, red-R ↔ yellow-L)의
        같은 상대 시점 영상 또는 관절 상태를 넣는다. 영상만 바꿨는데 뒤집히면 장면 차이에 반응 → (A).
        비교용으로 표 2 와 같은 "반대 배치 짝"(같은 색·반대 팔) 교체도 같이 낸다.

    python lang/analysis/memorization_probe.py --smolvla <경로> [--nolang <경로>] 2>&1 | tee results/memorization_probe.log
결과: results/memorization_probe_<시각>.csv (장면별) + results/memorization_probe_<시각>_요약.txt (표만)
"""
import argparse, csv, math, os, random, time
import numpy as np, torch
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.configs.policies import PreTrainedConfig
from lerobot.policies import get_policy_class, make_pre_post_processors

DS = "bilimili/xlerobot-dice-4cam-v2"
RED = "Pick up the red dice and put it in the basket"
YELLOW = "Pick up the yellow dice and put it in the basket"
OFFSETS = [-90, -60, -30, -15, -5]   # 분기 3·2·1·0.5·0.17초 전 (30 fps)
THR = 10.0                           # 분기 시점: 사용 팔 관절이 출발 값에서 10° 이상

ap = argparse.ArgumentParser()
ap.add_argument("--smolvla", required=True)
ap.add_argument("--nolang", default=None, help="언어 없이 학습한 SmolVLA (대조군, 선택)")
ap.add_argument("--out", default=time.strftime("results/memorization_probe_%Y%m%d_%H%M%S.csv"))
args = ap.parse_args()
dev = torch.device("cuda")
SUMMARY = args.out.replace(".csv", "_요약.txt")
os.makedirs(os.path.dirname(SUMMARY) or ".", exist_ok=True)
_sf = open(SUMMARY, "w", encoding="utf-8")


def say(*a):
    """화면에 찍고 요약 파일에도 바로 남긴다 (터미널을 위로 올려 볼 필요 없게)."""
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    _sf.write(line + "\n"); _sf.flush()


# ── 데이터: 사용 팔, 색, 분기 시점 ──
ds = LeRobotDataset(DS)
fps = ds.fps
names = ds.meta.features["action"]["names"]
L = [i for i, n in enumerate(names) if n.startswith("left_")]
R = [i for i, n in enumerate(names) if n.startswith("right_")]
epcol = np.asarray(ds.hf_dataset["episode_index"])
acts = np.asarray(ds.hf_dataset["action"], dtype=np.float32)
states = np.asarray(ds.hf_dataset["observation.state"], dtype=np.float32)

info = {}
for e in np.unique(epcol):
    idx = np.where(epcol == e)[0]
    a = acts[idx]
    dl = np.abs(a[:, L] - a[0, L]).max(1)
    dr = np.abs(a[:, R] - a[0, R]).max(1)
    arm = "L" if dl.max() > dr.max() else "R"
    over = np.where((dl if arm == "L" else dr) > THR)[0]
    if len(over) == 0:
        continue
    color = "red" if " red " in ds[int(idx[0])]["task"] else "yellow"
    # 배치: 빨강이 어느 쪽에 있나 (red 지시면 사용 팔 쪽, yellow 지시면 반대쪽)
    red_side = arm if color == "red" else ("R" if arm == "L" else "L")
    info[int(e)] = dict(idx=idx, arm=arm, color=color, red_side=red_side, td=int(over[0]))
eps = sorted(info)

rng = random.Random(0)
same_layout, opp_layout = {}, {}
for e in eps:
    me = info[e]
    c1 = [p for p in eps if info[p]["red_side"] == me["red_side"] and info[p]["arm"] != me["arm"]]   # 같은 배치, 지시·팔 반대
    c2 = [p for p in eps if info[p]["color"] == me["color"] and info[p]["arm"] != me["arm"]]         # 반대 배치 (표 2 와 같은 짝)
    same_layout[e], opp_layout[e] = rng.choice(c1), rng.choice(c2)


def gidx(e, off):
    idx = info[e]["idx"]
    t = info[e]["td"] + off
    return int(idx[t]) if 0 <= t < len(idx) else None


def chunk_arm(P):
    dl = np.abs(P[:, L] - P[0, L]).max(); dr = np.abs(P[:, R] - P[0, R]).max()
    return "L" if dl > dr else "R"


def wilson(k, n):
    if n == 0:
        return float("nan"), float("nan")
    z = 1.96; p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * (c - h), 100 * (c + h)


cells = {}
for e in eps:
    k = (info[e]["color"], info[e]["arm"]); cells[k] = cells.get(k, 0) + 1
say(f"에피소드 {len(eps)} (" + ", ".join(f"{c}-{a} {n}" for (c, a), n in sorted(cells.items())) + ")")

# ── 실험 1 의 데이터 부분: 시점마다 사용 팔이 이미 얼마나 움직였나 (모델 없이) ──
say("\n[데이터] 분기 전 시점별 사용 팔의 출발 자세 대비 변화 (관절 상태, 최대 관절 기준 °)")
say(f"  {'시점':>8s}{'사용 팔 중앙값':>14s}{'사용 팔 90%':>12s}{'반대 팔 중앙값':>14s}{'사람 청크로 본 정답 팔':>22s}")
for off in OFFSETS:
    used, other, ok, n = [], [], 0, 0
    for e in eps:
        gi = gidx(e, off)
        if gi is None:
            continue
        s0 = states[info[e]["idx"][0]]; s = states[gi]
        u, o = (L, R) if info[e]["arm"] == "L" else (R, L)
        used.append(np.abs(s[u] - s0[u]).max()); other.append(np.abs(s[o] - s0[o]).max())
        n += 1; ok += chunk_arm(acts[gi: gi + 50]) == info[e]["arm"]
    say(f"  {off / fps:+7.2f}초{np.median(used):13.1f}°{np.percentile(used, 90):11.1f}°{np.median(other):13.1f}°{ok:>15d}/{n}")


# ── 모델 ──
def load(path):
    cfg = PreTrainedConfig.from_pretrained(path)
    m = get_policy_class(cfg.type).from_pretrained(path).to(dev).eval()
    pre, post = make_pre_post_processors(m.config, path, preprocessor_overrides={"device_processor": {"device": str(dev)}})
    return m, pre, post


def predict(model, pre, post, img, state, task, seed):
    fr = {k: v.unsqueeze(0).to(dev) for k, v in img.items()}
    fr["observation.state"] = torch.as_tensor(state).unsqueeze(0).to(dev)
    fr["task"] = task; fr["robot_type"] = "bi_so_base_client"
    torch.manual_seed(seed); model.reset()
    with torch.no_grad():
        a = model.predict_action_chunk(pre(fr))
        try:
            P = post(a)
        except Exception:
            P = torch.stack([post(a[:, k]) for k in range(a.shape[1])], 1)
    if isinstance(P, dict):
        P = P["action"]
    return P.squeeze(0).float().cpu().numpy()


def images(i):
    return {k: v for k, v in ds[i].items() if k.startswith("observation.images")}


CONDS = ["원본", "잡음(시드)", "지시문 교체", "영상(같은 배치)", "상태(같은 배치)", "영상(반대 배치)", "상태(반대 배치)"]
models = [("smolvla", args.smolvla)] + ([("smolvla-nolang", args.nolang)] if args.nolang else [])
os.makedirs(os.path.dirname(args.out), exist_ok=True)
w = csv.writer(open(args.out, "w", newline=""))
w.writerow(["model", "episode", "color", "arm", "offset", "cond", "pred_arm"])

for tag, path in models:
    model, pre, post = load(path)
    say(f"\n{'=' * 70}\n{tag}  ({path})\n{'=' * 70}")
    res = {}   # (off, cond) -> list of (arm, pred)
    for n, e in enumerate(eps):
        me = info[e]
        task = RED if me["color"] == "red" else YELLOW
        other_task = YELLOW if task == RED else RED
        for off in OFFSETS:
            gi, gs, go = gidx(e, off), gidx(same_layout[e], off), gidx(opp_layout[e], off)
            if gi is None or gs is None or go is None:
                continue
            img, s = images(gi), states[gi]
            seed = 1000 * e + off
            inputs = {
                "원본": (img, s, task, seed),
                "잡음(시드)": (img, s, task, seed + 7),
                "지시문 교체": (img, s, other_task, seed),
                "영상(같은 배치)": (images(gs), s, task, seed),
                "상태(같은 배치)": (img, states[gs], task, seed),
                "영상(반대 배치)": (images(go), s, task, seed),
                "상태(반대 배치)": (img, states[go], task, seed),
            }
            for c, (im, st, tk, sd) in inputs.items():
                p = chunk_arm(predict(model, pre, post, im, st, tk, sd))
                res.setdefault((off, c), []).append((e, me["arm"], p))
                w.writerow([tag, e, me["color"], me["arm"], off, c, p])
        if (n + 1) % 10 == 0:
            print(f"  {n + 1}/{len(eps)} 에피소드", flush=True)

    say(f"\n  [{tag}] 시점별 결과 — 첫 줄은 원본의 정답 팔 비율, 나머지는 원본 대비 예측 팔이 뒤집힌 비율")
    head = "  " + f"{'':16s}" + "".join(f"{o / fps:+9.2f}초" for o in OFFSETS)
    say(head)
    for c in CONDS:
        row = f"  {c:<16s}"
        for off in OFFSETS:
            base = {e: p for e, a, p in res.get((off, "원본"), [])}
            r = res.get((off, c), [])
            if not r:
                row += f"{'-':>11s}"; continue
            if c == "원본":
                k = sum(a == p for _, a, p in r)
            else:
                k = sum(p != base[e] for e, a, p in r)
            row += f"{100 * k / len(r):10.1f}%"
        say(row)
    n0 = len(res.get((OFFSETS[0], "원본"), []))
    say(f"  (시점당 장면 수 {n0}개. 95% 신뢰구간은 csv 로 계산하거나 wilson() 참고)")
    del model; torch.cuda.empty_cache()

say(f"\n기록: {args.out}")
say(f"요약: {SUMMARY}")
say("""읽는 법
  · 데이터 표: 3·2초 전의 '사용 팔' 변화가 0° 근처면 그 시점엔 팔이 아직 안 움직였다.
  · 원본 정답률이 3·2초 전에도 ~100% → 팔이 움직이기 전부터 맞힌다 → (A) 장면 암기 쪽.
    멀수록 50% 에 가깝고 분기에 가까울수록 오르면 → (B) 움직임 흔적 쪽.
  · 영상(같은 배치) 뒤집힘이 크면 → 배치가 같은데도 답이 바뀐다 → 장면 차이에 반응 → (A).
    영상(같은 배치)는 작고 상태(같은 배치)가 크면 → (B).""")
_sf.close()
