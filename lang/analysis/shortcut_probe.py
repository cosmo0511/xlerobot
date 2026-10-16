"""지름길 학습 점검 — 로봇 없이 GPU 로만 돕니다.

질문: 정책이 "어느 팔을 움직일지"를 무엇을 보고 정하는가?
      지시문인가, 영상인가, 지금 관절 상태인가?

방법 (학습 데이터 104 에피소드, 오프라인)
  1. 에피소드마다 실제로 쓴 팔과 두 팔이 갈라지는 프레임 t_d 를 행동 기록에서 찾는다.
  2. t_d 앞뒤 프레임에서 정책에 청크(50스텝)를 한 번씩 예측시키고,
     청크 안에서 왼팔·오른팔 중 어느 쪽이 더 크게 움직이려 하는지로 "예측 팔"을 정한다.
  3. 입력을 하나씩 바꿔서 예측 팔이 뒤집히는지 본다.
       지시문  → 반대 색 지시문
       영상    → 같은 색·반대 팔 에피소드의 같은 시점 영상 4장 (주사위 좌우가 반대인 장면)
       상태    → 위와 같은 짝 에피소드의 같은 시점 관절 상태 (영상·지시문은 원래 것)
       잡음    → 다른 난수 시드 (뒤집힘의 바닥값)
     정책이 지시문을 보고 팔을 고른다면 "지시문" 에서 많이 뒤집혀야 한다.
     지름길(관절 상태)에 기대면 "상태" 에서만 뒤집힌다.
  4. 같은 프레임에서 관절값 복사·평균 출력 기준선 MAE 도 같이 낸다.

예전 lang_strength.py / robustness.py 와 다른 점
  - select_action 은 행동 큐 때문에 에피소드당 한 번만 추론한다 → 매 프레임 predict_action_chunk 로 따로 추론
  - 비교 구간이 0–19초(주행)뿐이었다 → 팔이 갈라지는 시점 앞뒤만 본다
  - 난수 시드를 프레임마다 고정해 조건끼리는 같은 잡음으로 비교한다

    python lang/analysis/shortcut_probe.py                                  # SmolVLA + no-lang
    python lang/analysis/shortcut_probe.py --act bilimili/<v2-ACT 모델>      # ACT 도 (지시문 조건 제외)
    python lang/analysis/shortcut_probe.py --episodes 20                    # 빠르게 확인만
결과: results/offline_shortcut.csv (프레임·조건별 한 줄) + 화면 요약
"""
import argparse, csv, math, os, random
import numpy as np, torch
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.configs.policies import PreTrainedConfig
from lerobot.policies import get_policy_class, make_pre_post_processors

DS = "bilimili/xlerobot-dice-4cam-v2"
RED = "Pick up the red dice and put it in the basket"
YELLOW = "Pick up the yellow dice and put it in the basket"
PRE = [-30, -15, -5]     # t_d 기준 프레임 오프셋 — 아직 어느 팔도 안 움직임 (결정 시점)
POST = [15, 45]          # 이미 정답 팔이 움직이는 중
THR = 10.0               # 팔이 "움직였다" 고 볼 관절 변화량 (행동 단위)

ap = argparse.ArgumentParser()
ap.add_argument("--smolvla", default="bilimili/xlerobot-dice-4cam-v2-smolvla")
ap.add_argument("--nolang", default="bilimili/xlerobot-dice-4cam-v2-smolvla-nolang")
ap.add_argument("--act", default=None, help="v2 데이터로 학습한 ACT 모델 (없으면 건너뜀)")
ap.add_argument("--episodes", type=int, default=0, help="0 = 전부")
ap.add_argument("--out", default="results/offline_shortcut.csv")
args = ap.parse_args()
dev = torch.device("cuda")

# ── 1. 행동 기록에서 사용 팔과 분기 시점 찾기 (영상 디코딩 없음) ──
ds = LeRobotDataset(DS)
names = ds.meta.features["action"]["names"]
L = [i for i, n in enumerate(names) if n.startswith("left_")]
R = [i for i, n in enumerate(names) if n.startswith("right_")]
assert len(L) == 6 and len(R) == 6, names
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
    d = dl if arm == "L" else dr
    over = np.where(d > THR)[0]
    if len(over) == 0:
        continue
    td = int(over[0])
    color = "red" if " red " in ds[int(idx[0])]["task"] else "yellow"
    info[int(e)] = dict(idx=idx, arm=arm, td=td, color=color, fps=ds.fps)

eps = sorted(info)
if args.episodes:
    eps = eps[: args.episodes]
tds = np.array([info[e]["td"] / ds.fps for e in eps])
lens = np.array([len(info[e]["idx"]) / ds.fps for e in eps])
print(f"에피소드 {len(eps)} · 분기 시점 중앙값 {np.median(tds):.1f}초 (범위 {tds.min():.1f}–{tds.max():.1f}) "
      f"· 길이 평균 {lens.mean():.1f}초", flush=True)
for c in ("red", "yellow"):
    for a in ("L", "R"):
        print(f"  {c:<6s} {a}: {sum(1 for e in eps if info[e]['color']==c and info[e]['arm']==a)}")

# 짝: 같은 색·반대 팔 에피소드 (주사위 좌우가 반대인 장면)
rng = random.Random(0)
partner = {}
for e in eps:
    cands = [p for p in info if info[p]["color"] == info[e]["color"] and info[p]["arm"] != info[e]["arm"]]
    partner[e] = rng.choice(cands)


def frame_index(e, off):
    idx = info[e]["idx"]
    t = min(max(info[e]["td"] + off, 0), len(idx) - 1)
    return int(idx[t]), t


def chunk_arm(P):
    """청크 안에서 더 크게 움직이려는 팔. P: (T, 15)"""
    dl = np.abs(P[:, L] - P[0, L]).max()
    dr = np.abs(P[:, R] - P[0, R]).max()
    return ("L" if dl > dr else "R"), float(dl), float(dr)


# GT 로 측정 방법 자체가 맞는지 확인: 사람 행동 청크로 같은 판정을 하면 정답 팔이 나와야 함
ok = tot = 0
for e in eps:
    for off in PRE + POST:
        gi, t = frame_index(e, off)
        P = acts[gi: gi + 50]
        if len(P) < 2:
            continue
        tot += 1
        ok += chunk_arm(P)[0] == info[e]["arm"]
print(f"측정 방법 확인 (사람 행동 청크): 정답 팔 {ok}/{tot}", flush=True)


def wilson(k, n):
    if n == 0:
        return (float("nan"),) * 2
    z = 1.96; p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def load(path):
    cfg = PreTrainedConfig.from_pretrained(path)
    m = get_policy_class(cfg.type).from_pretrained(path).to(dev).eval()
    pre, post = make_pre_post_processors(m.config, path,
                                         preprocessor_overrides={"device_processor": {"device": str(dev)}})
    return cfg.type, m, pre, post


def predict(model, pre, post, item_img, state, task, seed):
    fr = {k: v.unsqueeze(0).to(dev) for k, v in item_img.items()}
    fr["observation.state"] = torch.as_tensor(state).unsqueeze(0).to(dev)
    fr["task"] = task
    fr["robot_type"] = "bi_so_base_client"
    torch.manual_seed(seed)
    model.reset()
    with torch.no_grad():
        a = model.predict_action_chunk(pre(fr))
        try:
            P = post(a)
        except Exception:
            P = torch.stack([post(a[:, k]) for k in range(a.shape[1])], 1)
    if isinstance(P, dict):
        P = P["action"]
    return P.squeeze(0).float().cpu().numpy()


models = [("smolvla", args.smolvla, True), ("smolvla-nolang", args.nolang, True)]
if args.act:
    models.append(("act", args.act, False))

os.makedirs(os.path.dirname(args.out), exist_ok=True)
fout = open(args.out, "w", newline="")
w = csv.writer(fout)
w.writerow(["model", "episode", "color", "arm", "phase", "offset", "cond", "pred_arm", "dL", "dR",
            "mae_first", "mae_copy", "mae_mean"])
abar = acts.mean(0)

for tag, path, has_lang in models:
    try:
        mtype, model, pre, post = load(path)
    except Exception as ex:
        print(f"\n[{tag}] 불러오기 실패, 건너뜀: {ex}")
        continue
    print(f"\n{'=' * 64}\n{tag}  ({path})\n{'=' * 64}", flush=True)
    conds = ["원본", "잡음(시드)", "영상 교체", "상태 교체"] + (["지시문 교체"] if has_lang else [])
    rows = []
    for n, e in enumerate(eps):
        task = RED if info[e]["color"] == "red" else YELLOW
        other_task = YELLOW if task == RED else RED
        for phase, offs in (("결정 전", PRE), ("분기 후", POST)):
            for off in offs:
                gi, t = frame_index(e, off)
                pi, _ = frame_index(partner[e], off)
                item = ds[gi]
                img = {k: v for k, v in item.items() if k.startswith("observation.images")}
                pimg = {k: v for k, v in ds[pi].items() if k.startswith("observation.images")}
                s, ps = states[gi], states[pi]
                seed = 1000 * e + off
                for cond in conds:
                    if cond == "원본":       P = predict(model, pre, post, img, s, task, seed)
                    elif cond == "잡음(시드)": P = predict(model, pre, post, img, s, task, seed + 7)
                    elif cond == "영상 교체":  P = predict(model, pre, post, pimg, s, task, seed)
                    elif cond == "상태 교체":  P = predict(model, pre, post, img, ps, task, seed)
                    else:                     P = predict(model, pre, post, img, s, other_task, seed)
                    arm, dl, dr = chunk_arm(P)
                    r = [tag, e, info[e]["color"], info[e]["arm"], phase, off, cond, arm, dl, dr,
                         float(np.abs(P[0] - acts[gi]).mean()),
                         float(np.abs(states[gi] - acts[gi]).mean()),
                         float(np.abs(abar - acts[gi]).mean())]
                    w.writerow(r); rows.append(r)
        if (n + 1) % 10 == 0:
            print(f"  {n + 1}/{len(eps)} 에피소드", flush=True)
    fout.flush()

    # ── 요약 ──
    def sel(phase, cond):
        return {(r[1], r[5]): r for r in rows if r[4] == phase and r[6] == cond}
    for phase in ("결정 전", "분기 후"):
        base = sel(phase, "원본")
        n = len(base)
        k_ok = sum(r[7] == r[3] for r in base.values())
        k_R = sum(r[7] == "R" for r in base.values())
        lo, hi = wilson(k_ok, n)
        print(f"\n  [{phase}] 프레임 {n}")
        print(f"    원본: 정답 팔 {k_ok}/{n} ({100 * k_ok / n:.1f}%, CI {100 * lo:.1f}–{100 * hi:.1f}) · 오른팔 예측 {k_R}/{n}")
        for cond in conds[1:]:
            c = sel(phase, cond)
            flip = sum(c[key][7] != base[key][7] for key in base if key in c)
            lo, hi = wilson(flip, n)
            print(f"    {cond:<8s} → 예측 팔 뒤집힘 {flip:>3d}/{n} ({100 * flip / n:5.1f}%, CI {100 * lo:.1f}–{100 * hi:.1f})")
    b = [r for r in rows if r[6] == "원본"]
    print(f"\n  MAE (같은 프레임, 청크 첫 스텝): 정책 {np.mean([r[10] for r in b]):.3f} · "
          f"관절값 복사 {np.mean([r[11] for r in b]):.3f} · 평균 출력 {np.mean([r[12] for r in b]):.3f}")
    del model; torch.cuda.empty_cache()

fout.close()
print(f"\n기록: {args.out}")
print("읽는 법: '지시문 교체' 뒤집힘이 '잡음' 수준이면 정책은 지시문으로 팔을 고르지 않는다.\n"
      "        '상태 교체' 에서만 크게 뒤집히면 관절 상태(지름길)에 기대고 있다.")
