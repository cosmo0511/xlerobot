#!/usr/bin/env python3
"""ACT 모델로 로봇을 돌린다. (PC 에서 실행)

ACT 는 언어 입력이 없다. 영상과 관절 상태만 보고 동작을 낸다.
그래서 지시를 바꾸는 키가 없고, 늘 같은 일만 한다.

    SPACE   일시 정지 / 재개
    Q       종료

사용 예:
    python act_infer.py \\
      --policy-path=bilimili/xlerobot-dice-4cam-act \\
      --remote-ip=xlerobot2.local \\
      --robot-id=bi_so101 \\
      --display \\
      --cameras='{...}'
"""

import argparse
import json
import select
import sys
import termios
import time
import tty

C = {"r": "\033[0m", "b": "\033[1m", "dim": "\033[2m", "ok": "\033[32m",
     "w": "\033[33m", "no": "\033[31m", "hi": "\033[36m"}
if not sys.stdout.isatty():
    C = dict.fromkeys(C, "")


def read_keys():
    out = []
    while select.select([sys.stdin], [], [], 0)[0]:
        ch = sys.stdin.read(1)
        if not ch:
            break
        out.append(ch)
    return out


class Display:
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


def setup(args):
    import torch
    from lerobot.cameras.opencv import OpenCVCameraConfig
    from lerobot.policies import make_pre_post_processors
    from lerobot.policies.act import ACTPolicy
    from lerobot.robots import make_robot_from_config
    from lerobot.robots.bi_so_follower.config_bi_so_follower import BiSOBaseClientConfig
    from lerobot.utils.feature_utils import hw_to_dataset_features

    want = args.device
    if want == "cuda":
        try:
            if not torch.cuda.is_available():
                raise RuntimeError("torch.cuda.is_available() == False")
            torch.zeros(1).cuda()
        except Exception as exc:
            print(f"  {C['w']}GPU 를 쓸 수 없어 CPU 로 돕니다.{C['r']}")
            print(f"  {C['dim']}{str(exc).splitlines()[0][:110]}{C['r']}")
            want = "cpu"
    device = torch.device(want)

    print(f"  정책을 불러오는 중: {args.policy_path}")
    model = ACTPolicy.from_pretrained(args.policy_path)
    model.to(device)
    model.eval()
    preprocess, postprocess = make_pre_post_processors(
        model.config, args.policy_path,
        preprocessor_overrides={"device_processor": {"device": str(device)}},
    )

    print(f"  로봇에 연결하는 중: {args.remote_ip}")
    cameras = {}
    for name, c in (json.loads(args.cameras) if args.cameras else {}).items():
        c = dict(c)
        c.pop("type", None)
        cameras[name] = OpenCVCameraConfig(**c)

    robot = make_robot_from_config(
        BiSOBaseClientConfig(remote_ip=args.remote_ip, id=args.robot_id, cameras=cameras))
    robot.connect()

    ds_features = {
        **hw_to_dataset_features(robot.action_features, "action"),
        **hw_to_dataset_features(robot.observation_features, "observation"),
    }
    if args.display:
        from lerobot.utils.rerun_visualization import init_rerun
        init_rerun(session_name="act_infer")
        print(f"  {C['dim']}카메라 화면: rerun 창이 열립니다{C['r']}")
    print(f"  {C['ok']}준비 완료{C['r']}  (관측 키 {len(ds_features)}개)")
    return model, preprocess, postprocess, robot, ds_features, device


def run(args):
    try:
        model, preprocess, postprocess, robot, ds_features, device = setup(args)
    except Exception as exc:
        print(f"\n  {C['no']}연결 실패: {exc}{C['r']}")
        print(f"  {C['dim']}파이에서 host 가 떠 있는지, 카메라 설정이 학습 때와 같은지 확인하세요.{C['r']}")
        return

    from lerobot.policies.utils import build_inference_frame, make_robot_action
    from lerobot.utils.rerun_visualization import log_rerun_data

    print(f"\n{C['b']}ACT 추론{C['r']}   {C['b']}SPACE{C['r']} 일시정지   {C['b']}Q{C['r']} 종료")
    print(f"  {C['dim']}ACT 는 언어 입력이 없습니다. 지시를 바꿀 수 없고 늘 같은 일을 합니다.{C['r']}\n")

    paused, sent, hz, t_last = False, 0, 0.0, time.time()
    period = 1.0 / args.fps if args.fps > 0 else 0.0
    next_t = time.time()
    disp = Display()
    old = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())
        while True:
            for ch in read_keys():
                if ch.lower() == "q":
                    raise KeyboardInterrupt
                if ch == " ":
                    paused = not paused

            if not paused:
                obs = robot.get_observation()
                frame = build_inference_frame(
                    observation=obs, ds_features=ds_features, device=device,
                    task=None, robot_type=args.robot_type)   # ACT 는 task 를 안 쓴다
                action = model.select_action(preprocess(frame))
                action = make_robot_action(postprocess(action), ds_features)
                robot.send_action(action)
                if args.display:
                    log_rerun_data(observation=obs, action=action)
                sent += 1
                now = time.time()
                dt = now - t_last
                if dt > 0:
                    hz = 0.9 * hz + 0.1 * (1 / dt)
                t_last = now

            # 학습 속도에 맞춰 묶는다
            if period:
                next_t += period
                now = time.time()
                if next_t > now:
                    time.sleep(next_t - now)
                else:
                    # 밀린 시간은 버린다. 몰아서 내보내면 그 순간 관절이 튄다.
                    next_t = now

            disp.draw([
                f"  상태   {C['w']}일시정지{C['r']}" if paused else
                f"  상태   {C['ok']}동작 중{C['r']}    {hz:5.1f} Hz"
                f"{'' if abs(hz-args.fps) < args.fps*0.2 else C['w']+' ★목표 '+str(args.fps)+C['r']}"
                f"    스텝 {sent}",
                f"  정책   ACT  {C['dim']}(언어 입력 없음){C['r']}",
            ])
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)
        disp.end()
        try:
            robot.disconnect()
        except Exception:
            pass
        print("종료")


def main():
    p = argparse.ArgumentParser(description="ACT 추론")
    p.add_argument("--policy-path", required=True)
    p.add_argument("--remote-ip", default="xlerobot2.local")
    p.add_argument("--robot-id", default="bi_so101")
    p.add_argument("--robot-type", default="bi_so_base_client")
    p.add_argument("--cameras", default=None)
    p.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    p.add_argument("--fps", type=float, default=30.0,
                   help="제어 주기. 학습 데이터의 fps 와 같아야 한다 (기본 30)")
    p.add_argument("--display", action="store_true")
    run(p.parse_args())


if __name__ == "__main__":
    main()
