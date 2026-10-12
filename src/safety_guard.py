"""
safety_guard.py — 추론 중 양팔 급동작(충돌 위험) 감지 후 정지

규칙:
  이번에 보내려는 관절 명령이 '직전에 보낸 명령'(에피소드 첫 스텝은 현재 자세)과
  비교해서, 왼팔에서 threshold 이상 튀는 관절이 하나라도 있고 AND
  오른팔에서도 하나라도 있으면
  -> 그 명령은 보내지 않고, 팔은 직전 명령 위치에 고정 + 바퀴 정지
  -> 이 회차는 실패(safety_stop)로 기록 (safety_stops.csv)

  * 그리퍼는 원래 크게 열고 닫으므로 검사에서 뺍니다.
  * 바퀴(x/y/theta.vel)는 검사하지 않고, 멈출 때 0으로 보냅니다.
"""

import csv
import os
import time

LEFT_JOINTS = ["left_shoulder_pan.pos", "left_shoulder_lift.pos", "left_elbow_flex.pos",
               "left_wrist_flex.pos", "left_wrist_roll.pos"]
RIGHT_JOINTS = ["right_shoulder_pan.pos", "right_shoulder_lift.pos", "right_elbow_flex.pos",
                "right_wrist_flex.pos", "right_wrist_roll.pos"]
GRIPPERS = ["left_gripper.pos", "right_gripper.pos"]
ARM_KEYS = LEFT_JOINTS + RIGHT_JOINTS + GRIPPERS
BASE_STOP = {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}


class SafetyStop(Exception):
    """안전 규칙 위반으로 정지. 이 회차는 실패로 처리."""


class SafetyGuard:
    def __init__(self, threshold_deg: float = 15.0, require_both: bool = True,
                 log_path: str = "safety_stops.csv"):
        self.threshold = threshold_deg
        self.require_both = require_both  # False 면 한 팔만 넘어도 정지
        self.log_path = log_path
        self.ref: dict = {}
        self.tripped = False
        self.message = ""
        self.task = ""

    def reset(self, obs: dict, task: str = "") -> None:
        """에피소드 시작 때 현재 자세를 기준으로 잡습니다."""
        self.ref = {k: float(obs[k]) for k in ARM_KEYS if k in obs}
        self.tripped = False
        self.message = ""
        self.task = task

    def _max_jump(self, action, joints):
        jumps = {j: abs(float(action[j]) - self.ref[j])
                 for j in joints if j in action and j in self.ref}
        if not jumps:
            return 0.0, None
        j = max(jumps, key=jumps.get)
        return jumps[j], j

    def check(self, action: dict) -> dict:
        """통과하면 action 그대로 반환, 위반이면 SafetyStop."""
        if self.tripped:
            raise SafetyStop(self.message)

        l_jump, l_joint = self._max_jump(action, LEFT_JOINTS)
        r_jump, r_joint = self._max_jump(action, RIGHT_JOINTS)
        l_bad, r_bad = l_jump >= self.threshold, r_jump >= self.threshold
        bad = (l_bad and r_bad) if self.require_both else (l_bad or r_bad)

        if not bad:
            self.ref.update({k: float(action[k]) for k in ARM_KEYS if k in action})
            return action

        self.tripped = True
        self.message = (f"양팔 급동작 감지 — 왼팔 {l_joint} {l_jump:.1f}, "
                        f"오른팔 {r_joint} {r_jump:.1f} (기준 {self.threshold})")
        print(f"[안전정지] {self.message}")
        print(f"  {'관절':<24}{'현재':>9}{'정책목표':>10}{'차이':>9}")
        for k in ARM_KEYS:
            if k in action and k in self.ref:
                d = float(action[k]) - self.ref[k]
                mark = "  <==" if k not in GRIPPERS and abs(d) >= self.threshold else ""
                print(f"  {k:<24}{self.ref[k]:>9.1f}{float(action[k]):>10.1f}{d:>9.1f}{mark}")
        self._log(l_joint, l_jump, r_joint, r_jump)
        raise SafetyStop(self.message)

    def hold_action(self) -> dict:
        """팔은 직전 명령 위치 유지, 바퀴는 정지."""
        return {**self.ref, **BASE_STOP}

    def _log(self, l_joint, l_jump, r_joint, r_jump):
        new = not os.path.exists(self.log_path)
        with open(self.log_path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time", "task", "left_joint", "left_jump",
                            "right_joint", "right_jump", "result"])
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), self.task, l_joint,
                        f"{l_jump:.1f}", r_joint, f"{r_jump:.1f}", "FAIL(safety_stop)"])
