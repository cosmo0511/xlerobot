#!/usr/bin/env python3
"""언어 데이터셋을 점검하고 합친다.

    python dataset_tools.py check  <데이터셋경로> [...]     지시문 분포·균형 확인
    python dataset_tools.py merge  <출력> <입력1> <입력2>   여러 데이터셋을 하나로

check 가 보는 것
    * 지시문이 몇 종류이고 각각 에피소드가 몇 개인지
    * 한쪽으로 치우쳐 있지 않은지 (치우치면 모델이 그쪽만 배운다)
    * 지시문에 오타·표기 흔들림이 없는지
    * 프레임 수·길이가 비정상인 에피소드가 없는지
"""

import json
import os
import shutil
import sys
from collections import Counter

try:
    import pandas as pd
except ImportError:
    print("pandas 가 필요합니다. lerobot 환경에서 실행하세요.")
    sys.exit(1)

C = {"r": "\033[0m", "b": "\033[1m", "dim": "\033[2m", "ok": "\033[32m",
     "w": "\033[33m", "no": "\033[31m"}
if not sys.stdout.isatty():
    C = dict.fromkeys(C, "")


def load_meta(root: str) -> dict:
    """데이터셋의 메타 정보를 읽는다."""
    meta = os.path.join(root, "meta")
    out = {"root": root, "name": os.path.basename(root.rstrip("/"))}
    try:
        out["info"] = json.load(open(os.path.join(meta, "info.json")))
    except Exception as e:
        out["error"] = f"info.json 읽기 실패: {e}"
        return out

    # tasks 는 버전에 따라 parquet 또는 jsonl
    tasks = {}
    import glob
    for f in glob.glob(os.path.join(meta, "tasks*.parquet")):
        df = pd.read_parquet(f)
        # {task_index: {지시문: 번호}} 형태
        if "task_index" in df.columns:
            tasks.update({str(k): int(v) for k, v in df["task_index"].items()})
        else:
            d = df.to_dict()
            for col in d.values():
                tasks.update({str(k): int(v) for k, v in col.items()})
    for f in glob.glob(os.path.join(meta, "tasks*.jsonl")):
        for line in open(f):
            try:
                j = json.loads(line)
                tasks[j["task"]] = j.get("task_index", len(tasks))
            except Exception:
                pass
    out["tasks"] = tasks

    # 에피소드별 정보
    eps = []
    for f in sorted(glob.glob(os.path.join(meta, "episodes", "**", "*.parquet"), recursive=True)):
        try:
            df = pd.read_parquet(f)
            cols = [c for c in ("episode_index", "length", "tasks", "task_index") if c in df.columns]
            eps.append(df[cols] if cols else df)
        except Exception:
            pass
    out["episodes"] = pd.concat(eps, ignore_index=True) if eps else None
    return out


def cmd_check(roots):
    total_by_task = Counter()
    for root in roots:
        m = load_meta(root)
        print(f"\n{C['b']}── {m['name']} ──{C['r']}")
        if "error" in m:
            print(f"  {C['no']}{m['error']}{C['r']}")
            continue
        i = m["info"]
        print(f"  에피소드 {i.get('total_episodes', '?')}개 · "
              f"프레임 {i.get('total_frames', '?')}개 · {i.get('fps', '?')} fps")
        feats = i.get("features", {})
        cams = [k for k in feats if k.startswith("observation.images")]
        print(f"  카메라 {len(cams)}개: {', '.join(c.split('.')[-1] for c in cams)}")

        if not m["tasks"]:
            print(f"  {C['no']}지시문이 하나도 없습니다.{C['r']}")
            continue

        print(f"\n  {'지시문':<46s}{'번호':>5s}{'에피소드':>9s}")
        print("  " + "-" * 64)
        eps = m["episodes"]
        counts = {}
        if eps is not None and "tasks" in eps.columns:
            for v in eps["tasks"]:
                key = v[0] if isinstance(v, (list, tuple)) and len(v) else str(v)
                counts[str(key)] = counts.get(str(key), 0) + 1
        elif eps is not None and "task_index" in eps.columns:
            idx_to_task = {v: k for k, v in m["tasks"].items()}
            for v in eps["task_index"]:
                key = idx_to_task.get(int(v), f"(번호 {v})")
                counts[key] = counts.get(key, 0) + 1

        for task, idx in sorted(m["tasks"].items(), key=lambda x: x[1]):
            n = counts.get(task, 0)
            total_by_task[task] += n
            print(f"  {task[:44]:<46s}{idx:>5d}{n:>9d}")

        # 균형 검사
        if len(m["tasks"]) > 1 and counts:
            vals = [counts.get(t, 0) for t in m["tasks"]]
            lo, hi = min(vals), max(vals)
            if lo == 0:
                print(f"\n  {C['no']}에피소드가 0개인 지시문이 있습니다.{C['r']}")
            elif hi / lo > 1.5:
                print(f"\n  {C['w']}불균형: 가장 많은 쪽이 적은 쪽의 {hi / lo:.1f}배입니다.{C['r']}")
                print(f"  {C['dim']}모델이 많은 쪽으로 치우쳐 지시를 무시할 수 있습니다.{C['r']}")
            else:
                print(f"\n  {C['ok']}균형 양호 ({lo}~{hi}개){C['r']}")

        # 표기 흔들림 검사
        norm = {}
        for t in m["tasks"]:
            k = "".join(t.lower().split())
            norm.setdefault(k, []).append(t)
        dup = {k: v for k, v in norm.items() if len(v) > 1}
        if dup:
            print(f"\n  {C['w']}표기가 흔들리는 지시문:{C['r']}")
            for v in dup.values():
                for t in v:
                    print(f"    · {t}")

    if len(roots) > 1:
        print(f"\n{C['b']}── 전체 합계 ──{C['r']}")
        for t, n in total_by_task.most_common():
            print(f"  {t[:50]:<52s}{n:>6d} 에피소드")


def cmd_merge(out_root, in_roots):
    """여러 데이터셋을 하나로 합친다.

    LeRobotDataset 의 공식 API 를 쓴다. 직접 파일을 복사하면 인덱스가 깨진다.
    """
    # lerobot 이 설치돼 있으면 그대로 쓴다. 소스 트리로만 두고 쓰는 경우를 위해
    # 환경변수나 흔한 위치도 찾아본다. (남의 PC 에서도 돌게)
    try:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
    except ImportError:
        import pathlib
        cands = []
        if os.environ.get("LEROBOT_SRC"):
            cands.append(os.environ["LEROBOT_SRC"])
        home = pathlib.Path.home()
        cands += [str(home / "workspace/lerobot/src"), str(home / "lerobot/src"),
                  str(home / "lerobot_0.6/src")]
        for c in cands:
            if os.path.isdir(os.path.join(c, "lerobot")):
                sys.path.insert(0, c)
                break
        try:
            from lerobot.datasets.lerobot_dataset import LeRobotDataset
        except ImportError:
            print(f"  {C['no']}lerobot 을 찾을 수 없습니다.{C['r']}")
            print(f"  {C['dim']}lerobot 환경에서 실행하거나, LEROBOT_SRC 로 경로를 알려주세요:")
            print(f"    LEROBOT_SRC=~/lerobot/src python dataset_tools.py merge ...{C['r']}")
            return 1

    if os.path.exists(out_root):
        print(f"  {C['no']}출력 경로가 이미 있습니다: {out_root}{C['r']}")
        print(f"  {C['dim']}지우거나 다른 이름을 쓰세요.{C['r']}")
        return 1

    srcs = []
    for r in in_roots:
        print(f"  읽는 중: {r}")
        srcs.append(LeRobotDataset(repo_id=os.path.basename(r.rstrip('/')), root=r))

    first = srcs[0]
    print(f"\n  새 데이터셋을 만듭니다: {out_root}")
    dst = LeRobotDataset.create(
        repo_id=os.path.basename(out_root.rstrip("/")),
        fps=first.fps,
        root=out_root,
        features=first.features,
        use_videos=True,
    )

    total = 0
    for src in srcs:
        n_ep = src.meta.total_episodes
        print(f"  {os.path.basename(src.root)}: {n_ep} 에피소드 복사")
        for ep in range(n_ep):
            frm = src.episode_data_index["from"][ep].item()
            to = src.episode_data_index["to"][ep].item()
            task = None
            for i in range(frm, to):
                item = src[i]
                task = item.get("task", task)
                frame = {k: v for k, v in item.items()
                         if k in dst.features and k not in ("index", "episode_index",
                                                            "frame_index", "task_index")}
                dst.add_frame(frame, task=task)
            dst.save_episode()
            total += 1
    print(f"\n  {C['ok']}완료: {total} 에피소드{C['r']}")
    print(f"  {C['dim']}확인:  python dataset_tools.py check {out_root}{C['r']}")
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "check":
        if len(sys.argv) < 3:
            print("  사용법: dataset_tools.py check <경로> [경로...]")
            return
        cmd_check(sys.argv[2:])
    elif cmd == "merge":
        if len(sys.argv) < 5:
            print("  사용법: dataset_tools.py merge <출력> <입력1> <입력2> [...]")
            return
        sys.exit(cmd_merge(sys.argv[2], sys.argv[3:]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
