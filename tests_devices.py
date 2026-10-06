"""
tests_devices.py — host/client/텔레옵의 키가 서로 맞는지 검증합니다.

    python tests_devices.py

lerobot 이 깔린 기기(노트북 또는 Pi)에서 돌리세요. 로봇은 연결할 필요 없습니다.
깔려 있지 않으면 그냥 건너뜁니다.

■ 왜 이게 필요한가
---------------------------------------------------------------------------
host / client / 텔레옵이 쓰는 action 키는 **세 쪽이 글자까지 같아야** 합니다.
하나라도 어긋나면 증상이 이렇게 나옵니다.

  · 팔이 아예 안 움직인다 (키가 안 맞아서 send_action 이 빈 dict 를 쓴다)
  · 녹화는 되는데 action 컬럼이 전부 0 이다
  · 학습은 멀쩡히 끝나고 추론에서만 로봇이 가만히 있다

전부 로그에 아무 경고가 안 뜹니다. 그래서 수집 전에 이걸로 먼저 확인합니다.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "src"))

try:
    import xlerobot_devices  # noqa: F401
except ImportError as e:
    print(f"SKIP: lerobot 이 없어서 건너뜁니다 ({e})")
    print("      pip install -e 'lerobot[feetech]' 한 기기에서 돌리세요.")
    sys.exit(0)

from xlerobot_devices import (  # noqa: E402
    BiLeaderBase,
    BiLeaderBaseConfig,
    XLerobotClient,
    XLerobotClientConfig,
)


def ok(msg):
    print(f"PASS: {msg}")


# --- 1. client(노트북) 와 텔레옵의 action 키가 같은가 ---------------------------
# bi_so_leader 는 left_shoulder_pan.pos 를 내보내고 로봇은 left_arm_shoulder_pan.pos
# 를 기다립니다. BiLeaderBase 가 그 `arm_` 을 끼워주는 게 이 테스트의 핵심입니다.
for use_head in (False, True):
    client = XLerobotClient(XLerobotClientConfig(id="t", use_head=use_head))
    teleop = BiLeaderBase(BiLeaderBaseConfig(id="t", use_head=use_head))

    ck, tk = list(client.action_features), list(teleop.action_features)
    assert ck == tk, f"use_head={use_head}\nclient: {ck}\nteleop: {tk}"
    ok(f"client/텔레옵 action 키 일치 (use_head={use_head}, {len(ck)}개)")

# --- 2. 로봇(host) 까지 세 쪽이 같은가 -----------------------------------------
# XLerobot 은 feetech 드라이버를 당겨오므로 없는 환경에선 건너뜁니다.
try:
    from xlerobot_devices import XLerobot, XLerobotConfig

    for use_head in (False, True):
        robot = XLerobot(XLerobotConfig(id="t", use_head=use_head))
        client = XLerobotClient(XLerobotClientConfig(id="t", use_head=use_head))
        assert list(robot.action_features) == list(client.action_features)
        assert list(robot.observation_features) == list(client.observation_features)
        ok(f"host/client action·observation 키 일치 (use_head={use_head})")
except ImportError as e:
    print(f"SKIP: host 쪽 검증 생략 (feetech 드라이버 없음: {e})")

# --- 3. 카메라 이름이 수집/추론 양쪽에서 쓰는 그 이름인가 -------------------------
# 이름이 하나라도 바뀌면 그때까지 찍은 데이터가 못 쓰게 됩니다.
client = XLerobotClient(XLerobotClientConfig(id="t"))
cams = [k for k in client.observation_features if not k.endswith((".pos", ".vel"))]
assert sorted(cams) == ["left_wrist", "right_wrist", "top"], cams
ok(f"카메라 키 3개: {sorted(cams)}")

# --- 4. 베이스 기구학 왕복 ------------------------------------------------------
try:
    from xlerobot_devices import XLerobot, XLerobotConfig

    robot = XLerobot(XLerobotConfig(id="t"))
    # 한계에 안 걸리는 느린 속도로. 빠르면 3000 캡에 걸려 셋 다 같이 줄어듭니다.
    for cmd in [(0.1, 0.0, 0.0), (0.0, 0.1, 0.0), (0.0, 0.0, 20.0)]:
        w = robot._body_to_wheel_raw(*cmd)
        back = robot._wheel_raw_to_body(
            w["base_left_wheel"], w["base_back_wheel"], w["base_right_wheel"]
        )
        got = (back["x.vel"], back["y.vel"], back["theta.vel"])
        for want_v, got_v in zip(cmd, got):
            assert abs(want_v - got_v) < 0.05 * max(abs(want_v), 1.0) + 0.01, f"{cmd} -> {got}"
    ok("베이스 기구학 왕복 (전진/횡이동/회전)")
except ImportError:
    pass

print("\n전부 통과.")
