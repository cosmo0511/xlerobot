"""
main.py — 💻 GPU PC 에서 실행하는 에이전트 진입점.

    # 하드웨어 없이 전체 흐름만 확인 (제일 먼저 이걸로 테스트하세요)
    python src/main.py --dry-run

    # 실제 로봇 — Pi-A 의 arm_node.py 와 Pi-B 의 Nav2 가 떠 있어야 합니다
    python src/main.py

    # 명령 하나만 실행하고 종료 (시연 스크립트용)
    python src/main.py --once "빨간 거 가져와"

기기 3대 중 이 파일은 PC 담당입니다.
    🦾 Pi-A   arm_node.py        (팔 + 카메라)
    🛞 Pi-B   nav2_bringup       (바퀴 + 라이다)
    💻 PC     lerobot-policy-server  +  main.py  ← 여기
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import Agent, CommandParser, KeywordParser  # noqa: E402
from navigation import make_navigator  # noqa: E402
from policy_client import make_policy_runner  # noqa: E402
from task_registry import load_registry  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def build(args):
    """설정을 읽고 모든 부품을 조립해서 (agent, registry, cleanup) 을 돌려줍니다."""
    robot_yaml = yaml.safe_load((PROJECT_ROOT / "config" / "robot.yaml").read_text(encoding="utf-8"))
    registry = load_registry()

    missing = registry.placeholder_locations()
    if missing and not args.dry_run:
        logging.warning("좌표가 아직 (0,0,0)인 위치: %s — tasks.yaml 을 채워주세요", missing)

    navigator = make_navigator(registry, robot_yaml["navigation"], dry_run=args.dry_run)
    arms = make_policy_runner(robot_yaml["arms"], dry_run=args.dry_run)

    # 파서 선택: 키가 있으면 LLM, 없으면 키워드 매칭으로 자동 폴백
    try:
        parser = CommandParser(registry, robot_yaml.get("agent"))
        logging.info("명령 해석: Gemini")
    except Exception as e:
        logging.warning("Gemini 를 못 씁니다(%s) — 키워드 매칭으로 대체합니다.", e)
        parser = KeywordParser(registry)

    agent = Agent(
        registry=registry,
        parser=parser,
        navigate_to=navigator.navigate_to,
        run_policy=arms.run,
        park_arms=arms.park,
    )

    def cleanup():
        arms.close()
        navigator.shutdown()

    return agent, registry, cleanup


def main():
    ap = argparse.ArgumentParser(description="XLeRobot 명령 에이전트 (PC)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Pi-A / Pi-B 없이 흐름만 확인")
    ap.add_argument("--once", metavar="COMMAND", help="명령 하나만 실행하고 종료")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-14s %(message)s",
        datefmt="%H:%M:%S",
    )

    agent, registry, cleanup = build(args)

    try:
        if args.once:
            print(f"결과: {agent.handle_command(args.once)}")
            return

        print("=" * 56)
        print(f"XLeRobot 명령 입력{'  [DRY-RUN]' if args.dry_run else ''} (종료: quit)")
        print("사용 가능한 태스크:")
        for prompt, task in registry.tasks.items():
            loc = registry.locations[task.location].name
            print(f"  · {prompt}  @ {loc}")
        print("=" * 56)

        while True:
            try:
                cmd = input("\n명령 > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n종료합니다.")
                break
            if cmd.lower() in ("quit", "exit", "q"):
                break
            if not cmd:
                continue
            print(f"결과: {agent.handle_command(cmd)}")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
