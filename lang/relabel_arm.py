#!/usr/bin/env python3
"""지시문에 사용한 팔을 넣은 데이터셋 사본을 만든다. 영상은 다시 인코딩하지 않는다.

    "Pick up the red dice and put it in the basket"
 →  "Pick up the red dice with the left arm and put it in the basket"     (--mode color_arm, 기본)
 →  "Pick up the dice with the left arm and put it in the basket"         (--mode arm)

어느 팔을 썼는지는 블록 표가 아니라 **행동 데이터**에서 정한다 (v1 블록 8·9 사고 때문).
기준은 lang/analysis/shortcut_probe.py 와 같다: 에피소드 첫 프레임 대비 관절 변화량의
최댓값이 더 큰 팔. 보고서에서 이 기준은 520개 장면 모두 실제 사용 팔과 일치했다.

바꾸는 것: meta/tasks.parquet, meta/episodes/*.parquet 의 tasks, data/*.parquet 의 task_index,
          meta/info.json 의 total_tasks, task_index 통계.  영상·행동·관절은 그대로.
영상 폴더는 하드링크(안 되면 복사)라 디스크를 거의 안 쓴다. 원본은 건드리지 않는다.

    python lang/relabel_arm.py                                   # v2 → v2-armtext (표준 위치)
    python lang/relabel_arm.py --mode arm --suffix armonly       # 색 없이 팔만
    python lang/relabel_arm.py --src <폴더> --dst <폴더>           # 경로 직접
    python lang/relabel_arm.py --dry-run                         # 팔 판정 표만 보고 아무것도 안 씀

결과: <dst>/arm_labels.csv (에피소드별 원래 지시문·판정 팔·변화량) + 화면 요약
"""
import argparse
import csv
import glob
import json
import os
import shutil
import sys

import numpy as np
import pandas as pd

THR = 10.0   # 이 이상 움직여야 "그 팔을 썼다"  (shortcut_probe 와 같은 값)
ARM_WORD = {"L": "left", "R": "right"}


def lerobot_home():
    return os.environ.get("HF_LEROBOT_HOME") or os.path.join(
        os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface")), "lerobot")


def find_root(repo):
    for c in (os.path.join(lerobot_home(), repo),
              os.path.join(lerobot_home(), "cosmo0511", repo.split("/")[-1])):
        if os.path.isfile(os.path.join(c, "meta", "info.json")):
            return c
    return None


def read_tasks(root):
    """{task_index: 지시문}. lerobot 은 지시문을 인덱스로 둔 표로 저장한다."""
    df = pd.read_parquet(os.path.join(root, "meta", "tasks.parquet"))
    if "task" in df.columns:
        return {int(i): str(t) for t, i in zip(df["task"], df["task_index"])}, df
    return {int(i): str(t) for t, i in zip(df.index, df["task_index"])}, df


def write_tasks(root, new_tasks, like):
    """원본 tasks.parquet 과 같은 모양으로 쓴다 (지시문이 인덱스인지 열인지)."""
    names = sorted(new_tasks, key=new_tasks.get)
    idx = [new_tasks[n] for n in names]
    if "task" in like.columns:
        df = pd.DataFrame({"task": names, "task_index": idx})
    else:
        df = pd.DataFrame({"task_index": idx}, index=pd.Index(names, name=like.index.name))
    df["task_index"] = df["task_index"].astype(like["task_index"].dtype)
    df.to_parquet(os.path.join(root, "meta", "tasks.parquet"))


def new_task(old, arm, mode):
    word = ARM_WORD[arm]
    if " and put" not in old or "Pick up the " not in old:
        raise ValueError(f"예상한 지시문 형식이 아닙니다: {old!r}")
    head, tail = old.split(" and put", 1)
    if mode == "arm":
        return f"Pick up the dice with the {word} arm and put{tail}"
    return f"{head} with the {word} arm and put{tail}"


def judge_arms(root, info):
    names = info["features"]["action"]["names"]
    if isinstance(names, dict):                      # 버전에 따라 {"motors": [...]}
        names = next(iter(names.values()))
    L = [i for i, n in enumerate(names) if n.startswith("left_")]
    R = [i for i, n in enumerate(names) if n.startswith("right_")]
    if len(L) != 6 or len(R) != 6:
        sys.exit(f"행동 이름에서 left_/right_ 관절 6개씩을 못 찾았습니다: {names}")

    files = sorted(glob.glob(os.path.join(root, "data", "**", "*.parquet"), recursive=True))
    if not files:
        sys.exit(f"데이터 파일이 없습니다: {root}/data")
    df = pd.concat([pd.read_parquet(f, columns=["episode_index", "frame_index", "action", "task_index"])
                    for f in files], ignore_index=True)
    out = {}
    for e, g in df.groupby("episode_index"):
        g = g.sort_values("frame_index")
        a = np.stack(g["action"].to_numpy()).astype(np.float32)
        dl = float(np.abs(a[:, L] - a[0, L]).max())
        dr = float(np.abs(a[:, R] - a[0, R]).max())
        arm = "L" if dl > dr else "R"
        d = np.abs(a[:, L if arm == "L" else R] - a[0, L if arm == "L" else R]).max(1)
        over = np.where(d > THR)[0]
        tis = g["task_index"].unique()
        out[int(e)] = dict(arm=arm, dl=dl, dr=dr, td=int(over[0]) if len(over) else -1,
                           task_index=int(tis[0]), n_task=len(tis))
    return out


def copy_dataset(src, dst):
    """meta/data 는 진짜 복사 (나중에 덮어쓰므로), videos 는 하드링크."""
    os.makedirs(dst)
    for name in os.listdir(src):
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if name == "videos" and os.path.isdir(s):
            # HF 다운로드 캐시(snapshots/)의 파일은 blobs/ 를 가리키는 상대 심볼릭 링크다.
            # 리눅스 link() 는 링크를 따라가지 않아서 그대로 하드링크하면 깨진 링크가 된다
            # → 실제 파일(realpath)에 하드링크한다.
            def link_target(a, b):
                os.link(os.path.realpath(a), b)
            try:
                shutil.copytree(s, d, copy_function=link_target)
            except OSError:
                shutil.rmtree(d, ignore_errors=True)
                print("  (하드링크가 안 돼서 영상을 복사합니다 — 시간이 좀 걸립니다)")
                shutil.copytree(s, d)
        elif os.path.isdir(s):
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)


def task_index_stats(values):
    v = np.asarray(values, dtype=np.float64)
    return dict(min=[float(v.min())], max=[float(v.max())], mean=[float(v.mean())],
                std=[float(v.std())], count=[int(v.size)])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src-repo", default="bilimili/xlerobot-dice-4cam-v2")
    ap.add_argument("--src", default=None, help="원본 폴더 (기본: lerobot 캐시에서 --src-repo 를 찾음)")
    ap.add_argument("--mode", choices=["color_arm", "arm"], default="color_arm")
    ap.add_argument("--suffix", default=None, help="새 repo 이름 꼬리 (기본: armtext / armonly)")
    ap.add_argument("--dst", default=None, help="새 폴더 (기본: 캐시의 <src-repo>-<suffix>)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    suffix = args.suffix or ("armtext" if args.mode == "color_arm" else "armonly")
    src = args.src or find_root(args.src_repo)
    if not src:
        sys.exit(f"원본을 못 찾았습니다: {args.src_repo}\n"
                 f"  {lerobot_home()}/{args.src_repo} 에 받아 두거나 --src 로 폴더를 주세요.")
    dst_repo = f"{args.src_repo}-{suffix}"
    dst = args.dst or os.path.join(lerobot_home(), dst_repo)

    info = json.load(open(os.path.join(src, "meta", "info.json")))
    tasks, tasks_df = read_tasks(src)
    print(f"원본 : {src}  ({info.get('total_episodes')} 에피소드, 지시문 {len(tasks)}종)")

    eps = judge_arms(src, info)
    rows, bad = [], []
    for e in sorted(eps):
        r = eps[e]
        old = tasks[r["task_index"]]
        if r["n_task"] != 1:
            bad.append(f"ep{e}: 한 에피소드에 지시문이 {r['n_task']}개")
        if r["td"] < 0:
            bad.append(f"ep{e}: 어느 팔도 {THR}° 이상 안 움직임 (왼 {r['dl']:.1f} / 오 {r['dr']:.1f})")
        lo, hi = sorted((r["dl"], r["dr"]))
        if hi < 2 * lo:
            bad.append(f"ep{e}: 두 팔이 비슷하게 움직임 (왼 {r['dl']:.1f} / 오 {r['dr']:.1f}) — 영상으로 확인하세요")
        rows.append(dict(episode_index=e, old_task=old, arm=ARM_WORD[r["arm"]],
                         left_max_deg=round(r["dl"], 1), right_max_deg=round(r["dr"], 1),
                         branch_frame=r["td"], new_task=new_task(old, r["arm"], args.mode)))

    # 요약: 색 × 팔
    print("\n  색 × 사용 팔 (행동 데이터 기준)")
    for c in ("red", "yellow", "blue"):
        n = {a: sum(1 for x in rows if f" {c} " in x["old_task"] and x["arm"] == a) for a in ("left", "right")}
        if sum(n.values()):
            print(f"    {c:<7s} 왼팔 {n['left']:>3d}   오른팔 {n['right']:>3d}")
    print("\n  새 지시문")
    for t in sorted({x["new_task"] for x in rows}):
        print(f"    {sum(1 for x in rows if x['new_task'] == t):>3d}  {t}")
    if bad:
        print(f"\n  ⚠ 확인이 필요한 에피소드 {len(bad)}개")
        for b in bad:
            print(f"    {b}")

    if args.dry_run:
        print("\n--dry-run: 아무것도 쓰지 않았습니다.")
        return
    if os.path.exists(dst):
        sys.exit(f"\n출력 폴더가 이미 있습니다: {dst}\n  지우거나 --suffix / --dst 로 다른 이름을 쓰세요.")

    print(f"\n복사 : {dst}")
    copy_dataset(src, dst)

    new_tasks = {t: i for i, t in enumerate(sorted({x["new_task"] for x in rows}))}
    ep_task = {x["episode_index"]: new_tasks[x["new_task"]] for x in rows}
    write_tasks(dst, new_tasks, tasks_df)

    all_ti = []
    for f in sorted(glob.glob(os.path.join(dst, "data", "**", "*.parquet"), recursive=True)):
        df = pd.read_parquet(f)
        dtype = df["task_index"].dtype
        df["task_index"] = df["episode_index"].map(ep_task).astype(dtype)
        if df["task_index"].isna().any():
            sys.exit(f"{f}: 팔을 정하지 못한 에피소드가 있습니다")
        df.to_parquet(f, index=False)
        all_ti.append(df["task_index"].to_numpy())
    all_ti = np.concatenate(all_ti)

    rev = {i: t for t, i in new_tasks.items()}
    for f in sorted(glob.glob(os.path.join(dst, "meta", "episodes", "**", "*.parquet"), recursive=True)):
        df = pd.read_parquet(f)
        df["tasks"] = [[rev[ep_task[int(e)]]] for e in df["episode_index"]]
        for k, v in (("min", None), ("max", None), ("mean", None), ("std", None)):
            col = f"stats/task_index/{k}"
            if col in df.columns:
                df[col] = [[float(ep_task[int(e)])] for e in df["episode_index"]]
        if "stats/task_index/std" in df.columns:
            df["stats/task_index/std"] = [[0.0] for _ in df["episode_index"]]
        df.to_parquet(f, index=False)

    info["total_tasks"] = len(new_tasks)
    json.dump(info, open(os.path.join(dst, "meta", "info.json"), "w"), indent=4)
    sp = os.path.join(dst, "meta", "stats.json")
    if os.path.exists(sp):
        st = json.load(open(sp))
        if "task_index" in st:
            st["task_index"].update(task_index_stats(all_ti))
            json.dump(st, open(sp, "w"), indent=4)

    with open(os.path.join(dst, "arm_labels.csv"), "w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    print(f"완료 : {len(rows)} 에피소드, 지시문 {len(new_tasks)}종")
    print(f"       판정 기록 {dst}/arm_labels.csv")
    print(f"\n확인 : python lang/dataset_tools.py check {dst}")
    print(f"학습 : DATASET_REPO={dst_repo} OUTPUT_DIR=<볼륨>/train/smolvla_dice_{suffix} ./scripts/train.sh smolvla")


if __name__ == "__main__":
    main()
