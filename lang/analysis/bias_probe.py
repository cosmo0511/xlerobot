"""왜 한쪽 팔(오른팔)만 쓰나 — 로봇 없이 GPU 로 확인합니다.

shortcut_probe.py 는 "학습 장면에서 무엇을 보고 팔을 고르나" 를 봤습니다 (지시문 X, 영상·관절 O).
여기서는 실기처럼 **그 단서가 맞지 않거나 없을 때 정책이 어느 팔로 가는지** 를 봅니다.

A. 데이터 (GPU 없이, 행동 기록만)
   왼팔·오른팔 에피소드가 같은 비중인지 — 개수, 길이, 분기 시점, 팔이 움직이는 프레임 수,
   반대쪽 팔이 얼마나 움직이는지. 한쪽 팔 동작이 학습 손실에서 더 큰 비중이면 기본값이 그쪽으로 쏠릴 수 있다.

B. 단서를 지웠을 때 정책의 기본 팔 (분기 직전 프레임, 104 에피소드 × 3)
   원본          : 그대로 (정답 팔을 고르는지 — shortcut_probe 와 같은 조건)
   영상 회색      : 카메라 4대를 회색(0.5)으로
   영상 출발 장면  : 같은 에피소드의 첫 프레임 영상 (주사위가 멀리 있을 때)
   상태 평균      : 관절 상태를 모든 결정 프레임의 평균으로 (왼팔·오른팔 에피소드의 중간)
   둘 다 지움     : 영상 회색 + 상태 평균
   지운 조건에서 오른팔 예측이 50% 를 크게 넘으면 "단서가 없으면 오른팔" 이 정책의 기본값이다.

    python lang/analysis/bias_probe.py --smolvla <경로> [--act <경로>] [--nolang <경로>]
결과: results/bias_probe_<시각>.csv + 화면 요약 (tee 로 남기세요)
"""
import argparse, csv, math, os, time
import numpy as np, torch
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.configs.policies import PreTrainedConfig
from lerobot.policies import get_policy_class, make_pre_post_processors

DS = "bilimili/xlerobot-dice-4cam-v2"
RED = "Pick up the red dice and put it in the basket"
YELLOW = "Pick up the yellow dice and put it in the basket"
PRE = [-30, -15, -5]
THR = 10.0

ap = argparse.ArgumentParser()
ap.add_argument("--smolvla", required=True)
ap.add_argument("--nolang", default=None)
ap.add_argument("--act", default=None)
ap.add_argument("--out", default=time.strftime("results/bias_probe_%Y%m%d_%H%M%S.csv"))
args = ap.parse_args()

ds = LeRobotDataset(DS)
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
    used, other = (dl, dr) if arm == "L" else (dr, dl)
    over = np.where(used > THR)[0]
    if len(over) == 0:
        continue
    td = int(over[0])
    info[int(e)] = dict(idx=idx, arm=arm, td=td, n=len(idx),
                        moving=int((used > THR).sum()),          # 쓰는 팔이 움직이는 프레임 수
                        used_max=float(used.max()), other_max=float(other.max()))
eps = sorted(info)
fps = ds.fps

# ── A. 데이터 ──
print("A. 데이터 (왼팔 에피소드 vs 오른팔 에피소드)")
print(f"  {'':10s}{'개수':>6s}{'길이(초)':>10s}{'분기(초)':>10s}{'분기후(초)':>11s}{'팔 움직임 프레임':>16s}{'쓰는팔 최대변위':>15s}{'반대팔 최대변위':>15s}")
for a in ("L", "R"):
    g = [info[e] for e in eps if info[e]["arm"] == a]
    print(f"  {('왼팔' if a=='L' else '오른팔'):10s}{len(g):6d}"
          f"{np.mean([x['n'] for x in g])/fps:10.1f}{np.mean([x['td'] for x in g])/fps:10.1f}"
          f"{np.mean([x['n']-x['td'] for x in g])/fps:11.1f}{np.sum([x['moving'] for x in g]):16d}"
          f"{np.mean([x['used_max'] for x in g]):15.1f}{np.mean([x['other_max'] for x in g]):15.1f}")
s0 = {a: np.mean([states[info[e]["idx"][max(info[e]["td"] - 5, 0)]] for e in eps if info[e]["arm"] == a], 0) for a in ("L", "R")}
diff = np.abs(s0["L"] - s0["R"])
top = np.argsort(-diff)[:4]
print("  분기 0.17초 전 관절 상태 평균 차이가 큰 관절: " + ", ".join(f"{names[i]} {diff[i]:.1f}" for i in top))

# ── B. 단서 지우기 ──
dev = torch.device("cuda")
dec_frames = [(e, off) for e in eps for off in PRE]
def gidx(e, off):
    idx = info[e]["idx"]; return int(idx[min(max(info[e]["td"] + off, 0), len(idx) - 1)])
mean_state = np.mean([states[gidx(e, o)] for e, o in dec_frames], 0)


def chunk_arm(P):
    dl = np.abs(P[:, L] - P[0, L]).max(); dr = np.abs(P[:, R] - P[0, R]).max()
    return ("L" if dl > dr else "R"), float(dl), float(dr)


def wilson(k, n):
    z = 1.96; p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * (c - h), 100 * (c + h)


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


models = [("smolvla", args.smolvla)] + ([("smolvla-nolang", args.nolang)] if args.nolang else []) \
         + ([("act", args.act)] if args.act else [])
CONDS = ["원본", "영상 회색", "영상 출발 장면", "상태 평균", "둘 다 지움"]
os.makedirs(os.path.dirname(args.out), exist_ok=True)
w = csv.writer(open(args.out, "w", newline=""))
w.writerow(["model", "episode", "arm", "offset", "cond", "pred_arm", "dL", "dR"])

print(f"\nB. 단서를 지웠을 때 예측 팔 (분기 직전 {len(dec_frames)}프레임)")
for tag, path in models:
    model, pre, post = load(path)
    res = {c: [] for c in CONDS}
    first_img = {}
    for n, (e, off) in enumerate(dec_frames):
        item = ds[gidx(e, off)]
        img = {k: v for k, v in item.items() if k.startswith("observation.images")}
        if e not in first_img:
            it0 = ds[int(info[e]["idx"][0])]
            first_img[e] = {k: v for k, v in it0.items() if k.startswith("observation.images")}
        gray = {k: torch.full_like(v, 0.5) for k, v in img.items()}
        s = states[gidx(e, off)]
        task = item["task"] if isinstance(item.get("task"), str) else RED
        seed = 1000 * e + off
        inputs = {"원본": (img, s), "영상 회색": (gray, s), "영상 출발 장면": (first_img[e], s),
                  "상태 평균": (img, mean_state), "둘 다 지움": (gray, mean_state)}
        for c, (im, st) in inputs.items():
            arm, dl, dr = chunk_arm(predict(model, pre, post, im, st, task, seed))
            res[c].append((info[e]["arm"], arm, dl, dr))
            w.writerow([tag, e, info[e]["arm"], off, c, arm, dl, dr])
        if (n + 1) % 60 == 0:
            print(f"  [{tag}] {n + 1}/{len(dec_frames)}", flush=True)
    print(f"\n  === {tag}")
    print(f"  {'조건':<12s}{'정답 팔':>14s}{'오른팔 예측':>14s}{'95% CI':>16s}")
    for c in CONDS:
        r = res[c]; k = len(r)
        ok = sum(a == p for a, p, *_ in r); right = sum(p == "R" for _, p, *_ in r)
        lo, hi = wilson(right, k)
        print(f"  {c:<12s}{100*ok/k:13.1f}%{100*right/k:13.1f}%   [{lo:5.1f}, {hi:5.1f}]")
    del model; torch.cuda.empty_cache()

print(f"\n기록: {args.out}")
print("읽는 법: '원본' 은 정답 팔을 거의 다 맞혀야 정상. 지운 조건에서 오른팔 예측이 50% 를 크게 넘으면\n"
      "        단서가 없을 때 정책의 기본값이 오른팔이다 (실기에서 오른팔만 쓴 것과 같은 현상).")
