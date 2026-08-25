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

print("\n전부 통과.")
