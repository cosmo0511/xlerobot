"""
check_dataset.py — 녹화한 데이터셋에 프레임 손실이 없는지 검사합니다 (하드웨어 불필요).

    # 💻 PC 에서, 녹화가 끝난 뒤 아무 때나
    python src/check_dataset.py                          # CAMERA_SET·HF_USER 로 본 데이터셋
    python src/check_dataset.py cosmo0511/xlerobot-test-4cam
    python src/check_dataset.py ~/.cache/huggingface/lerobot/cosmo0511/xlerobot-dice-4cam
    python src/check_dataset.py <데이터셋> --episodes 5,6,7   # 일부만 (영상 디코딩이 제일 느림)

영상 4개를 끝까지 디코딩하므로 에피소드 1분에 카메라 4대면 수십 초 걸립니다.
메모리는 영상 길이와 상관없이 일정합니다 (프레임을 쌓아두지 않음).
문제가 있으면 종료 코드 1.

■ 무엇을 보나
---------------------------------------------------------------------------
1. 표(parquet)  — 에피소드마다 frame_index 가 0 부터 끊김 없는지, timestamp 간격이 1/fps 인지
2. 영상         — 카메라마다 디코딩한 프레임 수 = 표의 행 수인지, 에피소드 구간 길이가 맞는지,
                  검은 화면(파이에서 프레임이 안 와서 클라이언트가 0 으로 채운 것)이 있는지
3. stale 틱     — 카메라 4대 화면 **과** state 가 전부 직전 프레임과 똑같은 프레임.
                  그 순간 파이의 새 메시지가 아직 안 와서 직전 것을 한 번 더 쓴 것입니다.

■ stale 을 왜 "4대 + state 전부 같음" 으로 세나
---------------------------------------------------------------------------
카메라 하나만 보면 반복 프레임이 13~40% 로 훨씬 많이 나옵니다. 로봇이 가만히 있으면
AV1 압축(crf 30)이 거의 같은 화면을 **비트 단위로 똑같은** 프레임으로 복원하기 때문입니다
(바닥만 보는 base 가 제일 높음). 그건 손실이 아닙니다. 호스트는 카메라 4대와 관절 값을
**한 메시지**로 보내므로, 메시지가 안 온 틱은 전부가 동시에 같아집니다.

■ 기준 (2026-10-10 테스트 2에피소드 실측: stale 8.4%, 연속 최대 1)
---------------------------------------------------------------------------
파이 호스트와 PC 녹화 루프가 각자 30Hz 로 돌아서 박자가 가끔 어긋나는 건 정상입니다
(상류 LeKiwi 도 같은 구조). 문제는 **연속으로** 멈추는 것 — 무선이 끊긴 구간입니다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

MAX_STALE_RUN = 3        # 연속 stale 이 이 이상이면 (100ms 정지) 문제
MAX_STALE_RATIO = 0.20   # 에피소드의 stale 비율이 이 이상이면 문제
BLACK_MEAN = 5           # 화면 평균 밝기가 이 미만이면 검은 화면
SAME_EPS = 0.05          # 직전 프레임과의 평균 차이가 이 미만이면 "똑같음"
STEP = 2                 # 비교할 때 픽셀을 이만큼 솎음 (속도)


def resolve_root(arg: str | None) -> Path:
    home = Path(os.environ.get("HF_LEROBOT_HOME")
                or Path(os.environ.get("HF_HOME", Path.home() / ".cache/huggingface")) / "lerobot")
    if arg is None:
        user = os.environ.get("HF_USER")
        if not user:
            sys.exit("데이터셋을 주거나 HF_USER 를 설정하세요. 예: export HF_USER=cosmo0511")
        arg = f"{user}/xlerobot-dice-{os.environ.get('CAMERA_SET', '3cam')}"
    p = Path(arg).expanduser()
    return p if (p / "meta/info.json").exists() else home / arg


def decode(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """영상 하나 -> (pts 초, 프레임 평균 밝기, 직전 프레임과 똑같은지).

    프레임을 쌓아두지 않고 디코딩하면서 바로 비교합니다. 에피소드가 쌓이면 파일
    하나가 1만 프레임을 넘어서, 다 들고 있으면 메모리가 수 GB 씩 찹니다.
    """
    import av

    pts, mean, same = [], [], []
    prev = None
    with av.open(str(path)) as ct:
        s = ct.streams.video[0]
        s.thread_type = "AUTO"
        for f in ct.decode(s):
            x = f.to_ndarray(format="rgb24")[::STEP, ::STEP].astype(np.int16)
            pts.append(float(f.pts * s.time_base))
            mean.append(float(x.mean()))
            same.append(prev is not None and float(np.abs(x - prev).mean()) < SAME_EPS)
            prev = x
    return np.array(pts), np.array(mean), np.array(same, dtype=bool)


def longest_run(mask: np.ndarray) -> int:
    best = cur = 0
    for x in mask:
        cur = cur + 1 if x else 0
        best = max(best, cur)
    return best


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="데이터셋 프레임 손실 검사")
    ap.add_argument("dataset", nargs="?", help="폴더 경로 또는 repo_id (기본: HF_USER/xlerobot-dice-CAMERA_SET)")
    ap.add_argument("--episodes", help="쉼표로 구분한 에피소드 번호 (기본: 전부)")
    args = ap.parse_args(argv)

    root = resolve_root(args.dataset)
    if not (root / "meta/info.json").exists():
        print(f"데이터셋이 없습니다: {root}", file=sys.stderr)
        return 1
    info = json.loads((root / "meta/info.json").read_text())
    fps = info["fps"]
    cams = [k for k, v in info["features"].items() if v["dtype"] == "video"]
    eps = pd.concat(pd.read_parquet(p) for p in sorted((root / "meta/episodes").rglob("*.parquet")))
    eps = eps.sort_values("episode_index").reset_index(drop=True)
    if args.episodes:
        want = {int(x) for x in args.episodes.split(",")}
        eps = eps[eps.episode_index.isin(want)]

    print(f"데이터셋 {root}")
    print(f"에피소드 {info['total_episodes']}개, {info['total_frames']}프레임, {fps}fps, "
          f"카메라 {', '.join(c.rsplit('.', 1)[-1] for c in cams)}\n")

    problems: list[str] = []
    data_cache: dict[Path, pd.DataFrame] = {}
    video_cache: dict[Path, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    def data_file(r) -> pd.DataFrame:
        p = root / info["data_path"].format(chunk_index=int(r["data/chunk_index"]),
                                            file_index=int(r["data/file_index"]))
        if p not in data_cache:
            data_cache[p] = pd.read_parquet(p)
        return data_cache[p]

    def video_file(r, cam) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        p = root / info["video_path"].format(video_key=cam,
                                             chunk_index=int(r[f"videos/{cam}/chunk_index"]),
                                             file_index=int(r[f"videos/{cam}/file_index"]))
        if p not in video_cache:
            video_cache[p] = decode(p)
        return video_cache[p]

    # 카메라마다 파일을 한 번만 디코딩하도록 카메라 바깥 루프. 에피소드별 결과를 모읍니다.
    same: dict[int, dict[str, np.ndarray]] = {int(e): {} for e in eps.episode_index}
    for cam in cams:
        short = cam.rsplit(".", 1)[-1]
        print(f"  영상 디코딩: {short} ...", flush=True)
        for _, r in eps.iterrows():
            e, n = int(r.episode_index), int(r.length)
            pts, mean, same_prev = video_file(r, cam)
            t0, t1 = r[f"videos/{cam}/from_timestamp"], r[f"videos/{cam}/to_timestamp"]
            idx = np.where((pts >= t0 - 1e-3) & (pts < t1 - 1e-3))[0]
            if len(idx) != n:
                problems.append(f"ep{e} {short}: 영상 {len(idx)}프레임 / 표 {n}행 — 프레임이 빠졌습니다")
            black = int((mean[idx] < BLACK_MEAN).sum())
            if black:
                problems.append(f"ep{e} {short}: 검은 화면 {black}장 — 파이에서 이 카메라가 안 왔습니다")
            # 구간 첫 프레임의 비교 대상은 이전 에피소드라 뺍니다.
            same[e][short] = same_prev[idx[1:]]
            if len(idx) > 1 and len(np.unique(np.round(np.diff(pts[idx]), 4))) > 1:
                problems.append(f"ep{e} {short}: 영상 시간 간격이 일정하지 않습니다")
    print()

    print(f"{'ep':>4} {'길이':>7} {'표':>4} {'stale':>12} {'연속최대':>6}  지시문")
    for _, r in eps.iterrows():
        e, n = int(r.episode_index), int(r.length)
        df = data_file(r)
        g = df[df.episode_index == e]
        fi, ts = g["frame_index"].to_numpy(), g["timestamp"].to_numpy()
        table_ok = (len(g) == n and len(fi) and fi[0] == 0 and (np.diff(fi) == 1).all()
                    and np.allclose(np.diff(ts), 1 / fps, atol=1e-3))
        if not table_ok:
            problems.append(f"ep{e}: 표의 frame_index/timestamp 가 끊겼습니다")

        st = np.stack(g["observation.state"].to_numpy())
        st_same = np.abs(np.diff(st, axis=0)).max(axis=1) == 0
        masks = [m for m in same[e].values() if len(m) == len(st_same)]
        stale = np.logical_and.reduce(masks + [st_same]) if masks else np.zeros(0, bool)
        ratio = stale.mean() if len(stale) else 0.0
        run = longest_run(stale)
        flag = ""
        if run >= MAX_STALE_RUN:
            flag = " ✗"
            problems.append(f"ep{e}: {run}프레임 연속 정지 ({run / fps * 1000:.0f}ms) — 무선이 끊겼던 구간")
        elif ratio >= MAX_STALE_RATIO:
            flag = " ✗"
            problems.append(f"ep{e}: stale {ratio * 100:.0f}% — 새 데이터가 자주 늦게 옵니다")
        task = r["tasks"][0] if len(r["tasks"]) else ""
        print(f"{e:>4} {n / fps:>6.1f}s {'✓' if table_ok else '✗':>4} "
              f"{int(stale.sum()):>5} ({ratio * 100:4.1f}%) {run:>6}{flag}  {task}")

    print()
    if problems:
        print(f"✗ 문제 {len(problems)}개:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("✓ 빠진 프레임·검은 화면 없음. stale 은 기준 안 "
          f"(연속 {MAX_STALE_RUN} 미만, 비율 {MAX_STALE_RATIO * 100:.0f}% 미만).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
