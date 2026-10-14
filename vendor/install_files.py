#!/usr/bin/env python3
"""lerobot-0.6.patch 에 든 "새 파일" 몇 개만 지금 깔린 lerobot 에 덮어씁니다.

패치 전체를 다시 적용하려면 깨끗한 v0.6.0 부터 다시 깔아야 합니다 (README.md).
호스트처럼 우리가 새로 만든 파일만 고쳤을 때는 이걸로 충분합니다.

    python vendor/install_files.py                       # 기본: 호스트 + 클라이언트
    python vendor/install_files.py robots/bi_so_follower/bi_so_base_host.py

덮어쓰기 전 파일은 <파일>.bak-<시각> 으로 남깁니다. 같으면 건드리지 않습니다.
venv 를 켠 상태에서 실행하세요 (그 venv 의 lerobot 에 깝니다).
"""

import importlib
import shutil
import sys
import time
from pathlib import Path

PATCH = Path(__file__).resolve().parent / "lerobot-0.6.patch"
DEFAULT = [
    "robots/bi_so_follower/bi_so_base_host.py",
    "robots/bi_so_follower/bi_so_base_client.py",
]


def new_file_from_patch(rel: str) -> str:
    """패치에서 `new file` 로 들어 있는 파일의 전체 내용을 꺼냅니다."""
    header = f"diff --git a/src/lerobot/{rel} b/src/lerobot/{rel}"
    lines = PATCH.read_text(encoding="utf-8").splitlines(keepends=True)
    try:
        i = next(n for n, line in enumerate(lines) if line.rstrip("\n") == header)
    except StopIteration:
        sys.exit(f"패치에 {rel} 가 없습니다.")
    if not lines[i + 1].startswith("new file"):
        sys.exit(f"{rel} 는 패치에서 기존 파일을 고친 것이라 이 도구로는 못 깝니다. README.md 의 설치 순서를 따르세요.")
    out = []
    for line in lines[i + 1:]:
        if line.startswith("diff --git "):
            break
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+"):
            out.append(line[1:])
        elif line.startswith("\\ No newline"):
            out[-1] = out[-1].rstrip("\n")
    return "".join(out)


def main() -> None:
    import lerobot

    root = Path(lerobot.__file__).resolve().parent
    print(f"lerobot 위치: {root}")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    changed = 0
    for rel in sys.argv[1:] or DEFAULT:
        new = new_file_from_patch(rel)
        dst = root / rel
        old = dst.read_text(encoding="utf-8") if dst.exists() else None
        if old == new:
            print(f"  같음     {rel}")
            continue
        if old is not None:
            shutil.copy2(dst, dst.with_name(dst.name + f".bak-{stamp}"))
        dst.write_text(new, encoding="utf-8")
        changed += 1
        print(f"  덮어씀   {rel}" + (f"  (이전 파일: {dst.name}.bak-{stamp})" if old is not None else ""))

    # 호스트가 쓰는 설정 필드가 이 lerobot 에 있는지 확인 (없으면 호스트가 시작하자마자 죽습니다)
    cfg = importlib.import_module("lerobot.robots.bi_so_follower.config_bi_so_follower").BiSOBaseHostConfig()
    missing = [f for f in ("watchdog_timeout_ms", "max_loop_freq_hz", "observation_freq_hz") if not hasattr(cfg, f)]
    if missing:
        sys.exit(f"⚠ 이 lerobot 의 BiSOBaseHostConfig 에 {missing} 가 없습니다. "
                 "lerobot 을 README.md 순서대로 다시 까세요 (.bak 파일로 되돌릴 수 있습니다).")
    importlib.import_module("lerobot.robots.bi_so_follower.bi_so_base_host")
    print(f"완료: {changed}개 바꿈, 호스트 import 확인됨.")


if __name__ == "__main__":
    main()
