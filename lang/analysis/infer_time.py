"""SmolVLA / ACT 의 한 번 추론 시간과 큐 꺼내기 시간을 잰다."""
import time, torch
from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
from lerobot.utils.feature_utils import dataset_to_policy_features
from lerobot.configs.types import FeatureType
from lerobot.utils.constants import OBS_LANGUAGE_ATTENTION_MASK, OBS_LANGUAGE_TOKENS

meta = LeRobotDatasetMetadata("bilimili/xlerobot-dice-4cam-v2")
feats = dataset_to_policy_features(meta.features)
out_f = {k: v for k, v in feats.items() if v.type is FeatureType.ACTION}
in_f = {k: v for k, v in feats.items() if v.type is not FeatureType.ACTION}
dev = torch.device("cuda")

def batch_for(cfg, smol):
    b = {k: torch.rand(1, *f.shape, device=dev) for k, f in in_f.items()}
    if smol:
        L = cfg.tokenizer_max_length
        b[OBS_LANGUAGE_TOKENS] = torch.ones(1, L, dtype=torch.long, device=dev)
        b[OBS_LANGUAGE_ATTENTION_MASK] = torch.ones(1, L, dtype=torch.bool, device=dev)
    return b

def run(name, policy, cfg, smol, chunk):
    policy.to(dev).eval()
    b = batch_for(cfg, smol)
    with torch.no_grad():
        for _ in range(3): policy.select_action(b)     # 예열
        policy.reset()
        torch.cuda.synchronize()
        times = []
        for _ in range(chunk + 5):
            t = time.perf_counter()
            policy.select_action(b)
            torch.cuda.synchronize()
            times.append((time.perf_counter() - t) * 1000)
    slow = max(times); fast = sorted(times)[len(times)//2]
    cycle = (slow + (chunk - 1) * fast) / chunk
    print(f"\n{name}  (chunk={chunk})")
    print(f"  추론 1회   {slow:7.1f} ms")
    print(f"  큐 꺼내기  {fast:7.1f} ms")
    print(f"  평균 1스텝 {cycle:7.1f} ms   → 이론 상한 {1000/cycle:5.1f} Hz")
    print(f"  33.3 ms(30Hz) 대비: {'여유 있음' if cycle < 33.3 else f'★ {33.3/cycle*100:.0f}% 속도'}")

from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig
p = SmolVLAPolicy.from_pretrained("bilimili/xlerobot-dice-4cam-v2-smolvla")
run("SmolVLA", p, p.config, True, p.config.chunk_size)
del p; torch.cuda.empty_cache()

from lerobot.policies.act.modeling_act import ACTPolicy
p = ACTPolicy.from_pretrained("bilimili/xlerobot-dice-4cam-v2-act")
run("ACT", p, p.config, False, p.config.chunk_size)
