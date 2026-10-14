import numpy as np, torch
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
from lerobot.policies import make_pre_post_processors
from lerobot.policies.utils import make_robot_action

DS="bilimili/xlerobot-dice-4cam-v2"
RED="Pick up the red dice and put it in the basket"
YELLOW="Pick up the yellow dice and put it in the basket"
EPS=[0,1,13,14,26,27,39,40]
dev=torch.device("cuda")

ds=LeRobotDataset(DS, episodes=EPS)
epcol=np.asarray(ds.hf_dataset["episode_index"])
groups={int(e): np.where(epcol==e)[0] for e in np.unique(epcol)}
print(f"에피소드 {sorted(groups)} · 프레임 {len(ds)}", flush=True)

def to_vec(x):
    if torch.is_tensor(x): return x.squeeze(0).float().cpu().numpy()
    if isinstance(x, dict):
        for k in ("action", "ACTION"):
            if k in x: return to_vec(x[k])
    return np.asarray(x).squeeze()

for MODEL, tag in [("bilimili/xlerobot-dice-4cam-v2-smolvla","언어 학습"),
                   ("bilimili/xlerobot-dice-4cam-v2-smolvla-nolang","언어 없이 학습")]:
    model=SmolVLAPolicy.from_pretrained(MODEL).to(dev).eval()
    pre,post=make_pre_post_processors(model.config, MODEL,
               preprocessor_overrides={"device_processor":{"device":str(dev)}})
    print(f"\n{'='*62}\n{tag}   {MODEL.split('/')[-1]}\n{'='*62}", flush=True)
    res={}
    for e,ids in groups.items():
        sel=ids[::25][:24]
        true_task=ds[int(sel[0])]["task"]
        other=YELLOW if " red " in true_task else RED
        out={}
        for which,task in (("맞는",true_task),("반대",other)):
            model.reset(); errs=[]
            for i in sel:
                item=ds[int(i)]
                fr={k:(v.unsqueeze(0).to(dev) if torch.is_tensor(v) else v) for k,v in item.items()
                    if k=="observation.state" or k.startswith("observation.images")}
                fr["task"]=task; fr["robot_type"]="bi_so_base_client"
                with torch.no_grad(): a=model.select_action(pre(fr))
                errs.append(np.abs(to_vec(post(a))-item["action"].float().numpy()).mean())
            out[which]=float(np.mean(errs))
        res[e]=(true_task.split()[3], out["맞는"], out["반대"])
        c,m,o=res[e]
        print(f"  ep{e:>3d} ({c:<6s})  맞는 {m:7.3f}   반대 {o:7.3f}   "
              f"{'언어 반응 ✅' if o>m*1.1 else '★ 차이 없음'}", flush=True)
    M=np.mean([v[1] for v in res.values()]); O=np.mean([v[2] for v in res.values()])
    print(f"\n  평균   맞는 {M:.3f}   반대 {O:.3f}   비율 {O/M:.2f}배")
    del model; torch.cuda.empty_cache()
