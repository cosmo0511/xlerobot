"""
tests_smoke.py — 하드웨어 없이 돌리는 스모크 테스트.

    python tests_smoke.py

로봇·ROS2·GPU 없이 에이전트 로직과 설정 검증만 확인합니다.
코드를 고친 뒤 이게 통과하는지 먼저 보세요.
"""

import pathlib
import re
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "src"))

from agent import Agent, KeywordParser  # noqa: E402
from camera_config import (  # noqa: E402
    CameraConfigError,
    camera_names,
    dataset_fps,
    layout_for_robot,
    list_camera_sets,
    load_camera_set,
    observation_keys,
    record_args,
    resolve_cameras,
)
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


# --- 2. 태스크 실행 순서 -------------------------------------------------------
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


RED = "Pick up the red dice and put it in the basket"
BLUE = "Pick up the blue dice and put it in the basket"

r = make_agent().handle_command("빨간 거 넣어줘")
assert r["status"] == "done", r
expected = ["park:free", "nav:table", f"policy:{RED}", "park:free"]
assert order == expected, order
ok("1단계 태스크 순서 — " + " → ".join(order))


# --- 3. 실패하면 거기서 멈춘다 --------------------------------------------------
r = make_agent(fail_on_step=1).handle_command("빨간 거 넣어줘")
assert r["status"] == "policy_failed", r
assert order[-1] == f"policy:{RED}", "정책 실패 뒤에 뭔가 더 실행됨"
ok(f"정책 실패 시 중단 — {r['message'][:40]}…")

r = make_agent(nav_status="blocked").handle_command("파란 거 넣어줘")
assert r["status"] == "nav_failed" and r["steps_done"] == [], r
ok("이동 실패 시 조작 차단")


# --- 4. 자율주행을 안 쓰면 이동 단계는 그냥 통과 ---------------------------------
from navigation import make_navigator  # noqa: E402

nav = make_navigator(reg, {"enabled": False})
assert nav.navigate_to("table")["status"] == "arrived"
assert nav.navigate_to("없는곳")["status"] == "failed"
robot_cfg = __import__("yaml").safe_load(
    (pathlib.Path(__file__).resolve().parent / "config" / "robot.yaml").read_text(encoding="utf-8"))
assert robot_cfg["navigation"].get("enabled") is False, "robot.yaml 에서 자율주행이 켜져 있습니다"
ok("자율주행 꺼짐 — 이동 단계 통과, Nav2 노드에 안 붙음")


# --- 5. 모르는 명령엔 아무것도 안 한다 ------------------------------------------
r = make_agent().handle_command("샌드위치 만들어줘")
assert r["status"] == "unknown", r
assert order == [], "모르는 명령에 로봇이 움직임"
ok("모르는 명령에 로봇 정지 유지")


# --- 6. 실험 지시문은 red / blue 두 개, 색 단어만 다르다 --------------------------
# 언어 효과를 분리하는 실험이라 두 지시문은 색 단어 하나만 달라야 합니다.
prompts = reg.all_prompts()
assert prompts == [RED, BLUE], prompts
assert RED.replace("red", "blue") == BLUE, "두 지시문이 색 말고도 다릅니다"
assert all(len(t.steps) == 1 for t in reg.tasks.values()), "실험 태스크는 1단계입니다"
assert all(t.steps[0].max_seconds == 90 for t in reg.tasks.values()), "평가 제한은 90초"
ok("지시문 2종, 색 단어만 다름, 1단계, 90초 제한")


# --- 7. 끝났을 때 주사위는 바구니에 — 쥐고 있는지 확인은 끈다 ---------------------
make_agent().handle_command("빨간 거 넣어줘")
assert seen_holding == [False], seen_holding
ok("expect_holding=False (넣고 나면 그리퍼는 비어 있어야 함)")


# --- 8. 색이 다르면 다른 지시문으로 간다 ----------------------------------------
# 색 구분이 지시문으로만 이뤄지므로, 라우팅이 색을 틀리면 정책도 틀립니다.
for cmd, want in [("빨간 거 넣어줘", RED), ("파란 거 넣어줘", BLUE),
                  ("red", RED), ("blue", BLUE)]:
    make_agent().handle_command(cmd)
    assert f"policy:{want}" in order, f"{cmd} -> {order}"
ok("색깔별 라우팅 — 빨강/파랑이 각각 다른 지시문으로")


# --- 9. 카메라 구성 ------------------------------------------------------------
# 카메라 이름이 녹화 때와 추론 때 다르면 정책이 행동을 하나도 못 냅니다.
# 그래서 녹화·추론이 같은 파일을 읽는지, 키가 기대한 그대로인지 봅니다.
sets = list_camera_sets()
assert "3cam" in sets and "4cam" in sets, sets
ok(f"카메라 구성 발견 — {', '.join(sets)}")

cam3 = load_camera_set("3cam")
assert observation_keys(cam3) == [
    "observation.images.top",
    "observation.images.left_wrist",
    "observation.images.right_wrist",
], observation_keys(cam3)
ok("3cam 관측 키 — " + ", ".join(camera_names(cam3)))

cam4 = load_camera_set("4cam")
assert observation_keys(cam4) == [
    "observation.images.top",
    "observation.images.base",
    "observation.images.left_wrist",
    "observation.images.right_wrist",
], observation_keys(cam4)
ok("4cam 관측 키 — " + ", ".join(camera_names(cam4)))

# 4cam 은 3cam 의 상위집합이어야 합니다. 그래야 4cam 데이터 하나로
# 3cam 조건까지 학습해서 비교할 수 있습니다 (재녹화 없이).
assert set(camera_names(cam3)) <= set(camera_names(cam4)), "4cam 이 3cam 을 안 포함함"
ok("4cam 이 3cam 의 상위집합 — 한 데이터셋으로 두 조건 비교 가능")

# robot.yaml 의 camera_set 이 실제로 풀리는지 (추론 경로)
robot_yaml = __import__("yaml").safe_load(
    (pathlib.Path(__file__).resolve().parent / "config" / "robot.yaml").read_text(encoding="utf-8")
)
resolved = resolve_cameras(robot_yaml["arms"])
assert observation_keys(resolved) == observation_keys(
    load_camera_set(robot_yaml["arms"]["camera_set"])
)
ok(f"robot.yaml camera_set={robot_yaml['arms']['camera_set']} 가 같은 파일로 풀림 "
   f"(녹화 = 추론)")

# 장치를 두 카메라가 같이 쓰면 한쪽이 검은 화면으로 녹화됩니다.
try:
    import camera_config
    orig = camera_config.CONFIG_DIR
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    (tmpdir / "cameras.dup.yaml").write_text(
        "top_cameras:\n  top: {index_or_path: /dev/video0}\n"
        "left_cameras:\n  wrist: {index_or_path: /dev/video0}\n")
    camera_config.CONFIG_DIR = tmpdir
    try:
        load_camera_set("dup")
        raise AssertionError("같은 장치를 쓰는 구성을 통과시킴")
    except CameraConfigError as e:
        ok(f"거부 — 장치 중복 ({str(e).splitlines()[0][-40:]})")

    # fps 가 섞이면 데이터셋 fps 를 하나로 못 정합니다.
    (tmpdir / "cameras.mixfps.yaml").write_text(
        "top_cameras:\n  top: {index_or_path: 0, fps: 30}\n"
        "left_cameras:\n  wrist: {index_or_path: 2, fps: 15}\n")
    try:
        dataset_fps(load_camera_set("mixfps"))
        raise AssertionError("fps 가 다른 구성을 통과시킴")
    except CameraConfigError:
        ok("거부 — 카메라 fps 불일치")

    try:
        load_camera_set("없는구성")
        raise AssertionError("없는 구성을 통과시킴")
    except CameraConfigError:
        ok("거부 — 없는 카메라 구성")
finally:
    camera_config.CONFIG_DIR = orig

assert dataset_fps(cam3) == 30 and dataset_fps(cam4) == 30
ok("데이터셋 fps 30 (전 카메라 동일)")

# lerobot-record 인자: 비어 있지 않은 블록마다 하나씩
args4 = record_args(cam4)
assert len(args4) == 3, args4
assert args4[0].startswith("--robot.cameras={"), args4[0]
assert "base" in args4[0] and "top" in args4[0], args4[0]
assert args4[1].startswith("--robot.left_arm_config.cameras={"), args4[1]
ok(f"lerobot-record 인자 {len(args4)}개 생성")


# --- 10. 로봇 클래스가 달라도 최종 관측 키는 같다 --------------------------------
# bi_so_follower 계열은 카메라를 팔별로 받고 left_/right_ 접두사를 자동으로 붙입니다.
# xlerobot 계열은 카메라가 평평하게 달려서 접두사를 안 붙입니다.
# 두 경우에 **최종 키가 같아야** 로봇 클래스를 바꿔도 정책이 그대로 돕니다.
assert layout_for_robot("bi_so_follower") == "per_arm"
assert layout_for_robot("xlerobot") == "flat"
assert layout_for_robot("xlerobot_client") == "flat"
assert layout_for_robot("처음보는타입") == "per_arm", "모르는 타입은 기본값이어야 함"
ok("로봇 타입 -> 카메라 레이아웃 매핑")

flat = record_args(cam4, "flat")
assert len(flat) == 1, flat
assert flat[0].startswith("--robot.cameras={"), flat[0]
# flat 에서는 우리가 최종 이름을 직접 적어야 합니다 (접두사 자동 적용 없음)
for name in ("top", "base", "left_wrist", "right_wrist"):
    assert f"{name}: " in flat[0], f"flat 레이아웃에 {name} 이 없음: {flat[0]}"
ok("flat 레이아웃 — --robot.cameras 하나에 최종 이름 4개")

per_arm = record_args(cam4, "per_arm")
assert len(per_arm) == 3, per_arm
# per_arm 에서는 접두사를 lerobot 이 붙이므로 우리는 wrist 로만 적습니다
assert "left_wrist" not in per_arm[1], "per_arm 에 접두사를 중복으로 붙였습니다"
assert "wrist: " in per_arm[1], per_arm[1]
ok("per_arm 레이아웃 — 접두사는 lerobot 이 붙이도록 wrist 로만 넘김")

try:
    record_args(cam4, "없는레이아웃")
    raise AssertionError("없는 레이아웃을 통과시킴")
except CameraConfigError:
    ok("거부 — 없는 레이아웃")


# --- 11. record.sh 가 카메라를 하드코딩하지 않는다 ------------------------------
# 이 테스트가 이 변경의 핵심입니다. record.sh 에 장치 경로가 다시 들어오면
# 추론 설정과 조용히 어긋나기 시작합니다.
record_sh = (pathlib.Path(__file__).resolve().parent / "scripts" / "record.sh").read_text(
    encoding="utf-8")
code = "\n".join(l for l in record_sh.splitlines()
                  if not l.lstrip().startswith("#"))
assert "/dev/video" not in code, "record.sh 에 카메라 장치 경로가 하드코딩됐습니다"
assert "camera_config.py" in code, "record.sh 가 camera_config.py 를 안 씁니다"
assert "CAMERA_SET" in code, "record.sh 에 CAMERA_SET 이 없습니다"
ok("record.sh 가 카메라를 하드코딩하지 않고 구성 파일을 읽음")


# --- 11b. 중간에 끊었다가 이어 찍는 게 된다 -------------------------------------
# lerobot 0.6 은 데이터셋을 새로 만들 때 repo_id 에 타임스탬프를 붙입니다
# (configs/dataset.py stamp_repo_id). 그래서 --dataset.root 를 고정하지 않으면
# 1회차는 .../xlerobot-dice-4cam_20261010_145603/ 에 들어가고, 2회차의
# resume("xlerobot-dice-4cam") 은 그 폴더를 못 찾아 Hub 로 가서 401 로 죽습니다.
# **--root 가 빠지면 2회차부터 녹화가 아예 안 됩니다.** 그래서 여기서 못 빠지게 막습니다.
dspath_sh = (pathlib.Path(__file__).resolve().parent / "scripts" / "dataset_path.sh").read_text(
    encoding="utf-8")
dscode = "\n".join(l for l in dspath_sh.splitlines()
                    if not l.lstrip().startswith("#"))
assert "xlerobot-dice-$CAMERA_SET" in dscode, "데이터셋 이름에 카메라 구성이 안 붙습니다"
assert "DATASET_ROOT=" in dscode, "dataset_path.sh 가 DATASET_ROOT 를 안 정합니다"
assert "dataset_path.sh" in code, "record.sh 가 dataset_path.sh 를 안 씁니다"
assert '--dataset.root="$DATASET_ROOT"' in code, \
    "record.sh 에 --dataset.root 가 없습니다 — 2회차부터 이어찍기가 안 됩니다"
# 이어찍기 판정은 폴더가 있는지로 합니다 (--first 를 기억하지 않아도 되게).
assert "RESUME=" in code and "meta/info.json" in dscode, \
    "이어찍기 판정이 없습니다"
# Hub 업로드는 꺼져 있어야 합니다. lerobot 기본값이 true 라서, 그냥 두면
# 블록마다 데이터셋이 외부로 올라갑니다.
assert '--dataset.push_to_hub="$PUSH"' in code, "record.sh 가 push_to_hub 를 안 정합니다"
assert 'PUSH_TO_HUB:-0' in dscode, "Hub 업로드가 기본으로 켜져 있습니다"
ok("이어찍기 — --dataset.root 고정 + 폴더로 resume 판정, Hub 업로드는 기본 꺼짐")


# --- 11c. 4cam 진입점이 구성을 한 곳에서 박는다 ---------------------------------
# 파이(host.sh)와 PC(record.sh)의 CAMERA_SET 이 어긋나면, 파이가 안 보낸 카메라가
# bi_so_base_client 에서 np.zeros 로 채워져 **검은 화면이 조용히 녹화됩니다.**
run4_sh = (pathlib.Path(__file__).resolve().parent / "scripts" / "run_4cam.sh").read_text(
    encoding="utf-8")
r4code = "\n".join(l for l in run4_sh.splitlines()
                    if not l.lstrip().startswith("#"))
assert "export CAMERA_SET=4cam" in r4code, "run_4cam.sh 가 CAMERA_SET 을 내보내지 않습니다"
assert "/dev/video" not in r4code, "run_4cam.sh 에 장치 경로가 하드코딩됐습니다"
assert "preflight_cameras.py" in r4code, "run_4cam.sh 가 검증을 안 돌립니다"
# record 는 검증을 통과해야 녹화를 시작해야 합니다.
assert "SKIP_CHECK" in r4code, "record 앞에 카메라 검증이 없습니다"
ok("run_4cam.sh 가 CAMERA_SET=4cam 을 한 곳에서 박고, 녹화 전에 검증을 돌림")


# --- 12. 녹화에 바퀴가 들어간다 -------------------------------------------------
# bi_so_follower + bi_so_leader 로 찍으면 액션이 팔 12차원뿐이라 정책이 주행을
# 못 배웁니다. 바퀴(x.vel/y.vel/theta.vel)는 bi_so_base_leader 가 키보드에서
# 만들어 액션에 넣고, bi_so_base_client 가 파이로 보냅니다.
assert "--robot.type=\"$ROBOT_TYPE\"" in code and 'ROBOT_TYPE="bi_so_base_client"' in code, \
    "record.sh 가 bi_so_base_client 로 녹화하지 않습니다 — 바퀴가 액션에 안 들어갑니다"
assert "--teleop.type=bi_so_base_leader" in code, \
    "record.sh 가 bi_so_base_leader 를 안 씁니다 — 키보드 주행이 녹화되지 않습니다"
assert "--robot-type=\"$ROBOT_TYPE\"" in code, \
    "record.sh 카메라 인자가 클라이언트(flat) 레이아웃이 아닙니다"
assert layout_for_robot("bi_so_base_client") == "flat"
assert layout_for_robot("bi_so_base_follower") == "per_arm"
ok("record.sh 가 bi_so_base_client + bi_so_base_leader 로 녹화 (액션에 바퀴 포함)")

# record.sh 의 라벨이 tasks.yaml 과 글자까지 같아야 추론 때 정책이 알아듣습니다.
sh_labels = re.findall(r'^\s*\w+\)\s+echo "([^"]+)" ;;', record_sh, re.M)
assert sorted(sh_labels) == sorted(reg.all_prompts()), (sh_labels, reg.all_prompts())
assert re.search(r"^EPISODE_TIME_S=60\b", record_sh, re.M), "데모 제한 60초와 녹화 길이가 다릅니다"
ok("record.sh 라벨 = tasks.yaml 지시문, 에피소드 60초")

# 파이(host.sh)와 PC(record.sh)의 카메라 이름이 같아야 프레임이 들어옵니다.
host_sh = (pathlib.Path(__file__).resolve().parent / "scripts" / "host.sh").read_text(
    encoding="utf-8")
host_code = "\n".join(l for l in host_sh.splitlines() if not l.lstrip().startswith("#"))
assert "/dev/video" not in host_code, "host.sh 에 카메라 장치 경로가 하드코딩됐습니다"
assert "camera_config.py" in host_code and "CAMERA_SET" in host_code
for cams in (cam3, cam4):
    host_names = set(camera_names(cams))  # per_arm: 접두사는 lerobot 이 붙임
    flat_arg = record_args(cams, "flat")[0]
    for name in host_names:
        assert f"{name}: " in flat_arg, f"클라이언트 카메라 인자에 {name} 이 없음"
ok("host.sh(파이)와 record.sh(PC)가 같은 yaml 의 같은 카메라 이름을 씀")


# --- 13. 추론은 녹화와 같은 로봇으로 ---------------------------------------------
# 정책은 녹화 때 본 키·순서(15차원)로만 행동을 냅니다. 추론 쪽 로봇 클래스나
# 접속 정보가 녹화와 다르면 팔이 엉뚱하게 움직이거나 바퀴가 안 움직입니다.
arm_src = (pathlib.Path(__file__).resolve().parent / "src" / "arm_node.py").read_text(
    encoding="utf-8")
assert "BiSOBaseClientConfig" in arm_src, "arm_node.py 가 bi_so_base_client 를 안 씁니다"
assert "BiSOFollowerConfig(" not in arm_src, "arm_node.py 가 바퀴 없는 bi_so_follower 를 씁니다"
assert "stop_base()" in arm_src, "에피소드가 끝나도 바퀴를 안 세웁니다"


def sh_default(name):
    m = re.search(rf'^{name}="\$\{{{name}:-([^}}]*)\}}"|^{name}="([^"$]*)"', record_sh, re.M)
    assert m, f"record.sh 에서 {name} 을 못 찾음"
    return m.group(1) or m.group(2)


assert robot_yaml["arms"]["remote_ip"] == sh_default("PI_HOST"), \
    "robot.yaml arms.remote_ip 와 record.sh PI_HOST 가 다릅니다"
assert robot_yaml["arms"]["id"] == sh_default("ROBOT_ID"), \
    "robot.yaml arms.id 와 record.sh ROBOT_ID 가 다릅니다"
assert set(robot_yaml["host"]) == {"left_port", "right_port", "id"}, robot_yaml["host"]
ok("추론(arm_node)이 녹화와 같은 bi_so_base_client·같은 파이로 붙고, 끝나면 바퀴 정지")


print("\n전부 통과.")
