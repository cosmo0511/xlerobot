#!/usr/bin/env python3
"""말로 지시하며 로봇을 돌린다. (PC 에서 실행)

SmolVLA 같은 언어 지원 정책에 매 스텝 지시문을 넣어 준다. 돌아가는 중에
지시를 바꾸면 다음 동작부터 반영된다.

    R / B      빨강 / 파랑 으로 전환
    T          문장을 직접 입력 ("파란거 말고 빨간거" 처럼 아무렇게나)
    SPACE      일시 정지 / 재개
    Q          종료

연습 (로봇·모델 없이 지시 전환만 확인):
    python lang_infer.py --dry-run

실제 실행:
    python lang_infer.py \\
      --policy-path=outputs/smolvla_color/checkpoints/last/pretrained_model \\
      --remote-ip=192.168.200.114 \\
      --robot-id=bi_so101 \\
      --cameras='{"cam_wrist_left": {"type":"opencv","index_or_path":"/dev/cam_left","width":640,"height":480,"fps":30},
                  "cam_wrist_right":{"type":"opencv","index_or_path":"/dev/cam_right","width":640,"height":480,"fps":30},
                  "cam_top":       {"type":"opencv","index_or_path":"/dev/cam_top","width":640,"height":480,"fps":30}}'

주의
    * 카메라 이름·해상도는 "학습할 때와 똑같아야" 한다. 다르면 모델이 못 알아본다.
    * 파이에서 host 가 먼저 떠 있어야 한다.
"""

import argparse
import json
import select
import sys
import termios
import time
import tty

from lang_parser import TASKS, parse

try:
    from llm_parser import interpret as llm_interpret
except Exception:
    llm_interpret = None

C = {"r": "\033[0m", "b": "\033[1m", "dim": "\033[2m", "ok": "\033[32m",
     "w": "\033[33m", "no": "\033[31m", "hi": "\033[36m", "mag": "\033[35m"}
if not sys.stdout.isatty():
    C = dict.fromkeys(C, "")


def read_keys() -> list[str]:
    """블로킹하지 않고 눌린 키를 전부 읽는다."""
    out = []
    while select.select([sys.stdin], [], [], 0)[0]:
        ch = sys.stdin.read(1)
        if not ch:
            break
        out.append(ch)
    return out


def ask_line(prompt: str, old_attrs) -> str:
    """잠시 정상 터미널로 돌아가 한 줄을 입력받는다."""
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_attrs)
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return ""
    finally:
        tty.setcbreak(sys.stdin.fileno())


class Display:
    """같은 자리에 겹쳐 그려서 화면이 흐르지 않게 한다."""

    def __init__(self):
        self.lines = 0

    def draw(self, rows):
        if self.lines:
            sys.stdout.write(f"\033[{self.lines}A")
        for r in rows:
            sys.stdout.write("\033[2K" + r + "\n")
        self.lines = len(rows)
        sys.stdout.flush()

    def end(self):
        if self.lines:
            print()
        self.lines = 0


def key_map():
    """TASKS 의 key 첫 글자를 단축키로 쓴다. red -> r, blue -> b."""
    return {spec["key"][0]: spec for spec in TASKS}


def banner(dry: bool):
    km = key_map()
    print(f"\n{C['b']}언어 지시 추론{C['r']}"
          + (f"   {C['w']}[연습 모드 — 로봇 안 움직임]{C['r']}" if dry else ""))
    hint = "   ".join(f"{C['b']}{k.upper()}{C['r']} {s['label']}" for k, s in km.items())
    print(f"  {hint}   {C['b']}T{C['r']} 문장입력   {C['b']}N{C['r']} 다음단계   "
          f"{C['b']}SPACE{C['r']} 일시정지   {C['b']}Q{C['r']} 종료")
    print(f"  {C['dim']}T 를 누르면 아무렇게나 말해도 됩니다. 예: 파란거 말고 빨간거{C['r']}\n")


# ── 로봇·정책 연결 ──────────────────────────────────────────────────────

def setup(args):
    """정책과 로봇을 올리고, 추론에 필요한 것들을 돌려준다."""
    import torch
    from lerobot.policies import make_pre_post_processors
    from lerobot.policies.smolvla import SmolVLAPolicy
    from lerobot.robots import make_robot_from_config
    from lerobot.cameras.opencv import OpenCVCameraConfig
    from lerobot.robots.bi_so_follower.config_bi_so_follower import BiSOBaseClientConfig
    from lerobot.utils.feature_utils import hw_to_dataset_features

    # 드라이버 업데이트 후 재부팅을 안 하면 cuda 가 "있는 척" 하다가 터진다.
    # 실제로 써 보고 안 되면 조용히 cpu 로 내린다.
    want = args.device
    if want == "cuda":
        try:
            if not torch.cuda.is_available():
                raise RuntimeError("torch.cuda.is_available() == False")
            torch.zeros(1).cuda()          # 진짜 되는지 한 번 써 본다
        except Exception as exc:
            print(f"  {C['w']}GPU 를 쓸 수 없어 CPU 로 돕니다.{C['r']}")
            print(f"  {C['dim']}{str(exc).splitlines()[0][:110]}{C['r']}")
            print(f"  {C['dim']}드라이버를 갱신하셨다면 재부팅하면 GPU 가 돌아옵니다.{C['r']}")
            want = "cpu"
    device = torch.device(want)
    if want == "cpu":
        print(f"  {C['w']}CPU 추론은 느립니다 (몇 초에 한 스텝). 동작 확인용으로만 쓰세요.{C['r']}")
    print(f"  정책을 불러오는 중: {args.policy_path}")
    model = SmolVLAPolicy.from_pretrained(args.policy_path)
    model.to(device)
    model.eval()

    preprocess, postprocess = make_pre_post_processors(
        model.config, args.policy_path,
        preprocessor_overrides={"device_processor": {"device": str(device)}},
    )

    print(f"  로봇에 연결하는 중: {args.remote_ip}")
    # JSON 은 그냥 dict 라서 CameraConfig 객체로 바꿔 줘야 한다.
    # (명령줄로 넘길 때는 draccus 가 해 주지만, 여기선 직접 만든다)
    cameras = {}
    for name, c in (json.loads(args.cameras) if args.cameras else {}).items():
        c = dict(c)
        kind = c.pop("type", "opencv")
        if kind != "opencv":
            raise ValueError(f"지원하지 않는 카메라 종류: {kind}")
        cameras[name] = OpenCVCameraConfig(**c)
    robot_cfg = BiSOBaseClientConfig(
        remote_ip=args.remote_ip, id=args.robot_id, cameras=cameras)
    robot = make_robot_from_config(robot_cfg)
    robot.connect()

    # 관측·동작 키를 정책이 기대하는 형식으로 맞추는 표
    ds_features = {
        **hw_to_dataset_features(robot.action_features, "action"),
        **hw_to_dataset_features(robot.observation_features, "observation"),
    }
    if args.display:
        from lerobot.utils.rerun_visualization import init_rerun
        init_rerun(session_name="lang_infer")
        print(f"  {C['dim']}카메라 화면: rerun 창이 열립니다{C['r']}")

    print(f"  {C['ok']}준비 완료{C['r']}  (관측 키 {len(ds_features)}개)")
    return model, preprocess, postprocess, robot, ds_features, device


def step(model, preprocess, postprocess, robot, ds_features, device, task, robot_type,
         display=False):
    """한 스텝: 관측 → 지시문 붙이기 → 추론 → 로봇에 전송."""
    from lerobot.policies.utils import build_inference_frame, make_robot_action

    obs = robot.get_observation()
    frame = build_inference_frame(
        observation=obs, ds_features=ds_features, device=device,
        task=task,                    # ← 여기가 언어 통로
        robot_type=robot_type,
    )
    action = model.select_action(preprocess(frame))
    action = make_robot_action(postprocess(action), ds_features)
    robot.send_action(action)
    if display:
        # 모델이 실제로 받은 영상과 내놓은 동작을 그대로 보여 준다
        from lerobot.utils.rerun_visualization import log_rerun_data
        log_rerun_data(observation=obs, action=action)


# ── 메인 루프 ───────────────────────────────────────────────────────────

def run(args):
    dry = args.dry_run
    km = key_map()
    ctx = None

    if not dry:
        try:
            ctx = setup(args)
        except Exception as exc:
            print(f"\n  {C['no']}연결 실패: {exc}{C['r']}")
            print(f"  {C['dim']}파이에서 host 가 떠 있는지, 카메라 설정이 학습 때와 같은지 확인하세요.{C['r']}")
            return

    current = TASKS[0]
    queue: list[str] = []      # 여러 동작 명령일 때 남은 단계
    paused = False
    disp = Display()
    sent = 0
    changed_at = time.time()
    reason = "시작 지시"
    t_last = time.time()
    hz = 0.0
    period = 1.0 / args.fps if args.fps > 0 else 0.0
    next_t = time.time()

    banner(dry)
    old_attrs = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())
        while True:
            for ch in read_keys():
                low = ch.lower()
                if low == "q":
                    raise KeyboardInterrupt
                if ch == " ":
                    paused = not paused
                    continue
                if low == "t":
                    disp.end()
                    line = ask_line("  말씀하세요 > ", old_attrs)
                    # LLM 해석기가 있으면 그쪽을 먼저 쓴다. 여러 동작이
                    # 섞인 명령을 순서대로 처리할 수 있다.
                    if llm_interpret is not None and args.use_llm:
                        r = llm_interpret(line, use_llm=True, device=args.device)
                        if r.get("stop"):
                            paused, reason = True, f"'{line}' → 정지"
                        elif r["plan"]:
                            queue[:] = r["plan"][1:]
                            current = next(s for s in TASKS if s["key"] == r["plan"][0])
                            changed_at = time.time()
                            reason = f"{r['say']}  [{r['source']}]"
                        else:
                            reason = r["say"] or f"'{line}' 를 못 알아들음"
                    else:
                        r = parse(line)
                        if r["key"] == "stop":
                            paused, reason = True, f"'{line}' → 정지"
                        elif r["task"]:
                            queue.clear()
                            current = next(s for s in TASKS if s["key"] == r["key"])
                            changed_at = time.time()
                            reason = f"'{line}' → {r['reason']}"
                        else:
                            reason = f"'{line}' 를 못 알아들음"
                    banner(dry)
                    continue
                if low == "n" and queue:          # 다음 단계로 수동 전환
                    current = next(s for s in TASKS if s["key"] == queue.pop(0))
                    changed_at = time.time()
                    reason = f"다음 단계 (남은 {len(queue)}개)"
                    continue
                if low in km and km[low] is not current:
                    queue.clear()
                    current = km[low]
                    changed_at = time.time()
                    reason = f"{low.upper()} 키"

            if not paused:
                if dry:
                    time.sleep(1 / 30)
                else:
                    step(*ctx, task=current["task"], robot_type=args.robot_type,
                         display=args.display)
                sent += 1
                now = time.time()
                dt = now - t_last
                if dt > 0:
                    hz = 0.9 * hz + 0.1 * (1 / dt)   # 부드럽게 평균
                t_last = now

            # 학습 속도에 맞춰 묶는다
            if period and not dry:
                next_t += period
                now = time.time()
                if next_t > now:
                    time.sleep(next_t - now)
                else:
                    # 밀린 시간은 버린다. 몰아서 내보내면 그 순간 관절이 튄다.
                    next_t = now

            since = time.time() - changed_at
            disp.draw([
                f"  상태   {C['w']}일시정지{C['r']}" if paused else
                f"  상태   {C['ok']}동작 중{C['r']}    {hz:5.1f} Hz    스텝 {sent}",
                f"  지시   {C['b']}{current['label']}{C['r']}  "
                f"\"{C['hi']}{current['task']}{C['r']}\""
                + (f"  {C['mag']}← 방금 바뀜{C['r']}" if since < 1.5 else ""),
                f"  근거   {C['dim']}{reason}{C['r']}",
            ] + ([f"  남은   {C['w']}{len(queue)}단계{C['r']}  "
                  f"{C['dim']}→ {' → '.join(queue)}   (N 키로 다음){C['r']}"]
                 if queue else []))

    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_attrs)
        disp.end()
        if ctx is not None:
            try:
                ctx[3].disconnect()
            except Exception:
                pass
        print("종료")


def main():
    p = argparse.ArgumentParser(description="언어 지시로 로봇 추론")
    p.add_argument("--dry-run", action="store_true",
                   help="로봇·모델 없이 지시 전환만 연습")
    p.add_argument("--policy-path", default=None, help="학습된 모델 경로")
    p.add_argument("--remote-ip", default="192.168.200.114")
    p.add_argument("--robot-id", default="bi_so101")
    p.add_argument("--robot-type", default="bi_so_base_client")
    p.add_argument("--cameras", default=None, help="JSON 문자열. 학습 때와 같아야 함")
    p.add_argument("--device", default="cuda", choices=["cuda", "cpu", "mps"])
    p.add_argument("--fps", type=float, default=30.0,
                   help="제어 주기. 학습 데이터의 fps 와 같아야 한다 (기본 30)")
    p.add_argument("--display", action="store_true",
                   help="카메라 4대와 동작을 rerun 창에 띄운다")
    p.add_argument("--no-llm", dest="use_llm", action="store_false",
                   help="LLM 해석기를 끄고 키워드만 쓴다")
    args = p.parse_args()

    if not args.dry_run and not args.policy_path:
        print(f"  {C['w']}--policy-path 가 없어 연습 모드로 돕니다.{C['r']}")
        args.dry_run = True
    run(args)


if __name__ == "__main__":
    main()
