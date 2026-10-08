"""
tests_smoke.py — 하드웨어 없이 돌리는 스모크 테스트.

    python tests_smoke.py

로봇·ROS2·GPU 없이 에이전트 로직과 설정 검증만 확인합니다.
코드를 고친 뒤 이게 통과하는지 먼저 보세요.
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "src"))

from agent import Agent, KeywordParser  # noqa: E402
from base_teleop import KeyState, body_to_wheel_raw, load_base_cfg  # noqa: E402
from task_registry import TaskConfigError, load_registry  # noqa: E402


def ok(msg):
    print(f"PASS: {msg}")


GOOD_LOCS = "locations:\n  - {id: a, name: A, pose: {x: 0, y: 0, yaw: 0}}\n"


def write(text):
    p = pathlib.Path(tempfile.mktemp(suffix=".yaml"))
    p.write_text(text)
    return p


# --- 1. 설정 검증 -------------------------------------------------------------
cases = [
    (GOOD_LOCS + 'tasks:\n  - {id: t, name: T, steps: [{location: nope, prompt: "P"}]}\n',
     "정의되지 않은 location"),
    (GOOD_LOCS + 'tasks:\n  - {id: t, name: T, steps: [{location: a, prompt: " P "}]}\n',
     "prompt 앞뒤 공백"),
    (GOOD_LOCS + 'tasks:\n  - {id: t, name: T, steps: []}\n',
     "steps 가 빈 태스크"),
    (GOOD_LOCS + 'tasks:\n  - {id: t, name: T, steps: [{location: a}]}\n',
     "prompt 없는 단계"),
]
for text, what in cases:
    try:
        load_registry(write(text))
        raise AssertionError(f"{what} 를 통과시킴")
    except TaskConfigError:
        ok(f"거부 — {what}")

reg = load_registry()
ok(f"기본 설정 로드 — 위치 {len(reg.locations)}개, 태스크 {len(reg.tasks)}개, "
   f"학습 라벨 {len(reg.all_prompts())}종")


# --- 2. 다단계 태스크 실행 순서 -------------------------------------------------
order = []
seen_holding = []


def make_agent(nav_status="arrived", policy_status="done", fail_on_step=None):
    order.clear()
    seen_holding.clear()
    calls = {"n": 0}

    def policy(prompt, max_seconds, expect_holding=False):
        seen_holding.append(expect_holding)
        calls["n"] += 1
        order.append(f"policy:{prompt}")
        bad = fail_on_step is not None and calls["n"] == fail_on_step
        return {"status": "failed" if bad else policy_status, "message": "테스트"}

    return Agent(
        reg,
        KeywordParser(reg),
        navigate_to=lambda loc: (order.append(f"nav:{loc}"),
                                 {"status": nav_status, "location_id": loc, "message": ""})[1],
        run_policy=policy,
        park_arms=lambda hold_gripper=False: (
            order.append(f"park:{'hold' if hold_gripper else 'free'}"),
            {"status": "done", "message": ""})[1],
    )


r = make_agent().handle_command("빨간 거 가져와")
assert r["status"] == "done", r
expected = [
    "park:free", "nav:desk_1", "policy:Pick up the red dice",
    "park:hold", "nav:desk_2", "policy:Place the dice on the red spot",
    "park:free",
]
assert order == expected, order
ok("2단계 태스크 순서 — " + " → ".join(order))


# --- 3. 단계 사이 파킹은 그리퍼를 유지해야 한다 ----------------------------------
# 이걸 안 지키면 1단계에서 집은 물건을 이동 직전에 떨어뜨립니다.
between = order[3]
assert between == "park:hold", f"단계 사이 파킹이 그리퍼를 열었습니다: {between}"
ok("단계 사이 파킹이 그리퍼를 유지함 (물건 안 떨어뜨림)")

assert order[0] == "park:free" and order[-1] == "park:free"
ok("시작·종료 파킹은 그리퍼를 자유롭게 둠")


# --- 4. 중간 단계 실패 시 다음 단계로 안 넘어간다 --------------------------------
r = make_agent(fail_on_step=1).handle_command("빨간 거 가져와")
assert r["status"] == "policy_failed", r
assert r["failed_at_step"] == 1 and r["total_steps"] == 2, r
assert "nav:desk_2" not in order, "1단계 실패인데 2단계로 이동함"
ok(f"1단계 실패 시 중단 — {r['message'][:40]}…")

r = make_agent(nav_status="blocked").handle_command("파란 거 가져와")
assert r["status"] == "nav_failed" and r["steps_done"] == [], r
ok("이동 실패 시 조작 차단")


# --- 5. 모르는 명령엔 아무것도 안 한다 ------------------------------------------
r = make_agent().handle_command("샌드위치 만들어줘")
assert r["status"] == "unknown", r
assert order == [], "모르는 명령에 로봇이 움직임"
ok("모르는 명령에 로봇 정지 유지")


# --- 6. 학습 라벨 목록이 단계에서 정확히 나온다 ----------------------------------
prompts = reg.all_prompts()
assert len(prompts) == len(set(prompts)), "학습 라벨이 중복됩니다"
assert len(prompts) == 2 * len(reg.tasks), prompts
ok(f"학습 라벨 {len(prompts)}종 추출 — 데이터셋도 {len(prompts)}종 찍어야 함")


# --- 7. 집기 단계에만 잡았는지 확인이 켜진다 -------------------------------------
# 이게 없으면 못 집고도 2번 책상까지 가서 빈 손으로 놓는 시늉을 합니다.
make_agent().handle_command("빨간 거 가져와")
assert seen_holding == [True, False], seen_holding
ok("집기 단계만 expect_holding=True (놓기는 False)")


# --- 8. 색이 다르면 다른 지시문으로 간다 ----------------------------------------
# 색 구분이 지시문으로만 이뤄지므로, 라우팅이 색을 틀리면 정책도 틀립니다.
for cmd, want in [("빨간 거 가져와", "red"), ("파란 거 가져와", "blue"),
                  ("노란 거 가져와", "yellow")]:
    make_agent().handle_command(cmd)
    picks = [o for o in order if o.startswith("policy:Pick")]
    assert picks and want in picks[0], f"{cmd} -> {picks}"
ok("색깔별 라우팅 — 빨강/파랑/노랑이 각각 다른 지시문으로")


# --- 9. 베이스 운동학 — 바퀴가 엉뚱하게 돌면 로봇이 벽으로 갑니다 ------------------
# 바퀴 3개는 오른팔과 같은 시리얼 버스에 붙어 있고(ID 7·8·9), 속도 명령만 받습니다.
# 식은 lerobot LeKiwi 와 동일. 부호가 뒤집히면 전진 명령에 로봇이 후진합니다.
BASE = load_base_cfg(pathlib.Path(__file__).resolve().parent / "config" / "robot.yaml")
assert BASE["port"], "베이스 포트를 못 찾음 (arms.right_port 또는 base.port)"
ok(f"베이스 설정 로드 — 포트 {BASE['port']}, 바퀴 ID {BASE['wheel_ids']}")


def wheels(x, y, theta):
    return body_to_wheel_raw(x, y, theta,
                             wheel_radius=float(BASE["wheel_radius"]),
                             base_radius=float(BASE["base_radius"]),
                             max_raw=int(BASE["max_raw"]))


assert wheels(0, 0, 0) == {"left": 0, "back": 0, "right": 0}
ok("정지 명령 -> 세 바퀴 모두 0")

fwd = wheels(0.2, 0, 0)
assert fwd["back"] == 0, fwd                      # 뒷바퀴는 전진축에 기여하지 않습니다
assert fwd["left"] == -fwd["right"] != 0, fwd     # 좌우는 반대로 돕니다
assert wheels(-0.2, 0, 0) == {k: -v for k, v in fwd.items()}
ok(f"전진 -> L{fwd['left']} B{fwd['back']} R{fwd['right']}, 후진은 정확히 반대")

spin = wheels(0, 0, 60)
assert spin["left"] == spin["back"] == spin["right"] > 0, spin
ok("제자리 회전 -> 세 바퀴 같은 방향·같은 크기")

side = wheels(0, 0.2, 0)
assert side["left"] == side["right"] > 0 > side["back"], side
ok("좌 평행이동 -> 뒷바퀴만 반대 방향")

capped = wheels(5.0, 0, 0)
assert max(abs(v) for v in capped.values()) == int(BASE["max_raw"]), capped
assert capped["left"] < 0 < capped["right"], capped   # 줄여도 방향은 유지
ok(f"속도 상한 — 과도한 명령을 max_raw({BASE['max_raw']}) 로 비례 축소, 방향 유지")


# --- 10. 베이스 텔레옵 키 처리 — 손 떼면 서야 합니다 ------------------------------
K = BASE["keys"]


def state(latch=False):
    return KeyState(K, BASE["speed_levels"], hold_s=float(BASE["hold_s"]), latch=latch)


s = state()
s.feed([K["forward"]], now=0.0)
assert s.velocity(0.0)[0] > 0
assert s.velocity(float(BASE["hold_s"]) + 0.01) == (0.0, 0.0, 0.0), "손을 떼도 계속 감"
ok(f"hold 모드 — 마지막 입력 후 {BASE['hold_s']}초면 정지")

s = state(latch=True)
s.feed([K["forward"]], now=0.0)
assert s.velocity(100.0)[0] > 0, "latch 모드인데 멈춤"
s.feed([K["backward"]], now=100.0)
assert s.velocity(100.0)[0] < 0, "반대키가 기존 방향을 못 덮음"
s.feed([K["stop"]], now=100.0)
assert s.velocity(100.0) == (0.0, 0.0, 0.0), "정지키가 안 먹음"
ok("latch 모드 — 속도 유지, 반대키로 전환, 정지키로 멈춤")

s = state()
s.feed([K["forward"], K["backward"]], now=0.0)
assert s.velocity(0.0) == (0.0, 0.0, 0.0), "앞뒤 동시 입력이 0 이 아님"
ok("앞뒤 동시 입력 -> 0 (서로 상쇄)")

s = state()
levels = BASE["speed_levels"]
s.feed([K["speed_down"]], now=0.0)
assert s.speed_index == 0, "최저 단계 아래로 내려감"
s.feed([K["speed_up"]] * (len(levels) + 3), now=0.0)
assert s.speed_index == len(levels) - 1, "최고 단계 위로 올라감"
s.feed([K["forward"]], now=0.0)
assert s.velocity(0.0)[0] == float(levels[-1]["xy"])
ok(f"속도 단계 {len(levels)}개 경계 유지 — 최고 단계 {levels[-1]['xy']} m/s")

s = state()
s.feed([K["quit"]], now=0.0)
assert s.quit, "종료키가 안 먹음"
for esc in ("\x1b", "\x03"):
    s = state()
    s.feed([esc], now=0.0)
    assert s.quit, f"{esc!r} 로 안 빠져나옴"
ok("종료 — x / ESC / Ctrl-C")


print("\n전부 통과.")
