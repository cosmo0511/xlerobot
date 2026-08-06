"""
main.py — 터미널에서 명령을 입력받아 에이전트에 넘기는 진입점.

실행: python main.py
종료: quit / exit / q 입력, 또는 Ctrl+C
"""
from agent import handle_command


def main():
    print("=" * 40)
    print("XLeRobot 명령 입력 (종료: quit)")
    print("예시: 1번 책상 물 줘 / 분리수거 해줘")
    print("=" * 40)

    while True:
        try:
            cmd = input("\n명령 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료합니다.")
            break

        if cmd.lower() in ("quit", "exit", "q"):
            print("종료합니다.")
            break
        if not cmd:
            continue

        result = handle_command(cmd)
        print(f"결과: {result}")


if __name__ == "__main__":
    main()
