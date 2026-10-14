"""영상을 살짝 흔들었을 때 오차가 얼마나 커지는지 본다.
외운 것이면 작은 변화에도 와르르 무너진다."""
import numpy as np, torch
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
from lerobot.policies import make_pre_post_processors

DS="bilimili/xlerobot-dice-4cam-v2"; MODEL="bilimili/xlerobot-dice-4cam-v2-smolvla"
EPS=[0,13,26,39]; dev=torch.device("cuda")
ds=LeRobotDataset(DS, episodes=EPS)
epcol=np.asarray(ds.hf_dataset["episode_index"])
groups={int(e): np.where(epcol==e)[0] for e in np.unique(epcol)}

model=SmolVLAPolicy.from_pretrained(MODEL).to(dev).eval()
pre,post=make_pre_post_processors(model.config, MODEL,
          preprocessor_overrides={"device_processor":{"device":str(dev)}})

def vec(x):
    if torch.is_tensor(x): return x.squeeze(0).float().cpu().numpy()
    if isinstance(x,dict) and "action" in x: return vec(x["action"])
    return np.asarray(x).squeeze()

def perturb(img, kind):
    if kind=="원본": return img
    if kind=="밝기 ±10%":  return (img*1.10).clamp(0,1)
    if kind=="잡음 2%":    return (img+torch.randn_like(img)*0.02).clamp(0,1)
    if kind=="이동 8픽셀": return torch.roll(img, shifts=8, dims=-1)
    return img

KINDS=["원본","밝기 ±10%","잡음 2%","이동 8픽셀"]
print(f"  {'변형':<14s}{'평균 오차':>10s}{'원본 대비':>10s}")
res={}
for kind in KINDS:
    errs=[]
    torch.manual_seed(0)
    for e,ids in groups.items():
        sel=ids[::40][:12]
        task=ds[int(sel[0])]["task"]
        model.reset()
        for i in sel:
            item=ds[int(i)]
            fr={}
            for k,v in item.items():
                if k=="observation.state": fr[k]=v.unsqueeze(0).to(dev)
                elif k.startswith("observation.images"):
                    fr[k]=perturb(v.unsqueeze(0).to(dev), kind)
            fr["task"]=task; fr["robot_type"]="bi_so_base_client"
            with torch.no_grad(): a=model.select_action(pre(fr))
            errs.append(np.abs(vec(post(a))-item["action"].float().numpy()).mean())
    m=float(np.mean(errs)); res[kind]=m
    print(f"  {kind:<14s}{m:10.3f}{m/res['원본']:9.1f}배", flush=True)
print(f"\n  액션 표준편차 13.55 · 평균만 내놓는 모델의 오차 8.09")
