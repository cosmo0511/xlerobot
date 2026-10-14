"""지시문이 모델까지 가는지, 그리고 모델이 그걸 실제로 쓰는지 확인한다."""
import torch, numpy as np
from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
from lerobot.utils.feature_utils import dataset_to_policy_features
from lerobot.configs.types import FeatureType
from lerobot.utils.constants import OBS_LANGUAGE_TOKENS
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
from lerobot.policies import make_pre_post_processors

PATH = "bilimili/xlerobot-dice-4cam-v2-smolvla"
RED    = "Pick up the red dice and put it in the basket"
YELLOW = "Pick up the yellow dice and put it in the basket"

meta = LeRobotDatasetMetadata("bilimili/xlerobot-dice-4cam-v2")
feats = dataset_to_policy_features(meta.features)
in_f = {k: v for k, v in feats.items() if v.type is not FeatureType.ACTION}

dev = torch.device("cuda")
model = SmolVLAPolicy.from_pretrained(PATH).to(dev).eval()
pre, post = make_pre_post_processors(model.config, PATH,
              preprocessor_overrides={"device_processor": {"device": str(dev)}})

# 똑같은 관측(고정 난수)을 두 지시문에 각각 넣는다
g = torch.Generator().manual_seed(0)
obs = {k: torch.rand(1, *f.shape, generator=g) for k, f in in_f.items()}

def run(task):
    frame = {k: v.clone().to(dev) for k, v in obs.items()}
    frame["task"] = task
    frame["robot_type"] = "bi_so_base_client"
    b = pre(frame)
    toks = b.get(OBS_LANGUAGE_TOKENS)
    model.reset()
    with torch.no_grad():
        act = model.select_action({k: (v.clone() if torch.is_tensor(v) else v) for k, v in b.items()})
    return toks, act.squeeze(0).float().cpu().numpy()

t_r, a_r = run(RED)
t_y, a_y = run(YELLOW)

print("\n" + "="*60)
print("1) 지시문이 토큰으로 변환됐는가")
if t_r is None:
    print("   ★ observation.language.tokens 가 없습니다 — 언어가 모델에 안 들어갑니다")
else:
    same = torch.equal(t_r, t_y)
    nz_r = int((t_r != 0).sum()); nz_y = int((t_y != 0).sum())
    print(f"   토큰 모양 {tuple(t_r.shape)}   빨강 {nz_r}개 / 노랑 {nz_y}개 비영")
    print(f"   두 지시문의 토큰이 {'★같음 (언어가 안 바뀜)' if same else '다름 ✅'}")
    d = (t_r != t_y).nonzero()
    if len(d): print(f"   다른 위치: {d[:,1].tolist()[:8]}")

print("\n2) 모델 출력이 지시문에 따라 달라지는가")
names = meta.features["action"]["names"]
diff = np.abs(a_r - a_y)
print(f"   액션 평균 절대차 {diff.mean():.4f}   최대 {diff.max():.4f}")
print(f"   {'관절':<24s}{'빨강':>9s}{'노랑':>9s}{'차이':>9s}")
for i, n in enumerate(names):
    mark = "  ←" if diff[i] > 0.5 else ""
    print(f"   {n:<24s}{a_r[i]:9.3f}{a_y[i]:9.3f}{diff[i]:9.3f}{mark}")
print("\n   판정:", "언어가 출력에 영향 있음 ✅" if diff.max() > 0.05
      else "★ 출력이 거의 동일 — 모델이 언어를 무시하고 있음")
