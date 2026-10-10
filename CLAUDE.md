# XLeRobot — 작업 메모 (팀 공용)

**지금 실제 하드웨어가 어떻게 생겼는지**를 적어두는 곳입니다. 코드를 읽기 전에 보세요.

## 하드웨어 구성 (2026-10 현재)

```
💻 PC (GPU)                🍓 라즈베리파이              🤖 로봇
   랜선으로 네트워크   ←무선(WiFi)→   중간에서 통신     ←USB→   팔 2개 + 바퀴 3개
   학습 / 추론 서버
```

- **PC** — 랜선으로 네트워크에 붙어 있습니다. SmolVLA 학습·추론.
- **라즈베리파이** — **로봇과 무선으로 통신**합니다.
- **로봇** — SO-101 양팔 + 아래 옴니휠 모터 3개.
  **바퀴 모터 3개는 로봇 오른쪽 팔에 연결돼 있습니다.**

무선 구간이 있어서 **이미지를 매 프레임 보내는 설계는 못 씁니다.** SmolVLA 의
action chunk 방식(한 번에 50스텝 받아오기)이 여기서 필수입니다 —
이유는 `src/arm_node.py` 상단 주석에 있습니다.

## 지금까지 정해진 것

| 항목 | 현재 상태 |
|---|---|
| **주행** | 원래 Nav2 를 쓰려고 했지만, 바퀴 모터 3개를 오른팔에 연결해서 **전체 텔레옵**으로 진행했습니다. 주행은 됩니다. (Nav2 코드는 `src/` 에 그대로 있음) |
| **태스크** | 주사위 3색 pick & place. 예전 "화분에 물 주기" 는 폐기했고 문서에서 정리했습니다 |
| **데이터** | 아직 **한 에피소드도 안 찍었습니다.** 그래서 카메라 구성을 지금 바꿀 수 있습니다 |
| **하드웨어** | 다 있습니다 (베이스캠 포함) |
| **카메라** | 3cam / 4cam 둘 다 지원. `CAMERA_SET` 으로 전환. 4cam 은 **아직 미검증** |
| **마감** | **2주** |

## 로봇 클래스 — 우리가 직접 확장했습니다

⚠️ **상류 XLeRobot 의 `--robot.type=xlerobot` 을 쓰는 게 아닙니다.**
`lerobot 0.6` 소스를 직접 고쳐서 `bi_so_follower` 에 호스트/클라이언트와
베이스(바퀴)를 붙였습니다. 상류 문서(`port1`/`port2`, `x.vel`, lekiwi 게이트)를
그대로 따라가면 **우리 코드와 안 맞습니다.**

### 어디에 있나

```
/home/user/lerobot_0.6/          ← lerobot 소스 (editable 설치)
    src/lerobot/
/home/user/lerobot-venv-0.6/     ← 가상환경
```

### 무엇을 고쳤나 (15 files, +249 / -21)

새로 만든 파일:

```
src/lerobot/robots/bi_so_follower/bi_so_host.py        라즈베리파이 쪽 호스트
src/lerobot/robots/bi_so_follower/bi_so_client.py      PC 쪽 클라이언트
src/lerobot/robots/bi_so_follower/bi_so_base_host.py   베이스(바퀴) 호스트
src/lerobot/teleoperators/bi_so_leader/bi_so_base_leader.py
src/lerobot/robots/so102_follower/                     SO-102 팔
src/lerobot/teleoperators/so102_leader/
src/lerobot/teleoperators/bi_so102_leader/
```

고친 파일 중 큰 것:

```
robots/bi_so_follower/config_bi_so_follower.py   +123   ← 바퀴·설정이 여기
teleoperators/bi_so_leader/config_bi_so_leader.py +34
robots/bi_so_follower/__init__.py                 +25
robots/utils.py                                   +24
robots/__init__.py                                +20
teleoperators/utils.py                            +12
scripts/lerobot_record.py                          +4   ← 아주 작음(등록/임포트 수준)
scripts/lerobot_teleoperate.py, lerobot_calibrate.py,
lerobot_rollout.py, lerobot_replay.py,
lerobot_setup_motors.py, lerobot_find_joint_limits.py   각 +2~4
```

### 🔴 이 수정분이 그 PC 한 대에만 있습니다

레포에 없습니다. 팀원이 clone 해도 안 따라오고, `pip install -U` 한 번에
날아갑니다. **지금 프로젝트에서 제일 큰 단일 리스크입니다.**

패치로 묶어서 레포에 넣는 방법 (새 파일까지 포함):

```bash
cd /home/user/lerobot_0.6
git add -N .                               # 새 파일도 diff 에 포함
git diff > /tmp/lerobot-0.6-xlerobot.patch
git reset                                  # 스테이징만 되돌림
```

### 아직 모르는 것 (코드를 봐야 정해짐)

- `config_bi_so_follower.py` 에 **등록된 로봇 타입 이름**
  (`@RobotConfig.register_subclass("...")`) — `record.sh` 의 `--robot.type` 값
- 바퀴 모터 정의와 **액션 키 이름** — 녹화에 바퀴가 들어가는지가 여기서 갈립니다
- 리더암 + 키보드를 녹화에서 어떻게 합치는지
  (`lerobot_record.py` 가 4줄만 바뀐 걸 보면 이미 다른 데서 처리된 듯)

### 카메라는 어느 쪽이든 준비돼 있습니다

`bi_so_follower` 계열이면 현재 기본값인 `per_arm` 레이아웃이 맞습니다.
다른 형태가 필요하면 `--robot-type=` 으로 전환됩니다. 최종 관측 키는
두 레이아웃에서 똑같습니다.

## 아직 안 정해진 것 / 확인 필요

- **4cam 이 실제로 돌아가는지** — 카메라 4개를 동시에 열 수 있는지 확인 필요.
- **지금 돌아가는 녹화 설정이 레포에 없습니다.** 가상환경(site-packages) 안의
  파일을 고쳐서 쓰고 있습니다 (카메라 3개 버전). 아래 "가장 급한 것" 참고.
- **`record.sh` 를 `xlerobot_client` 로 바꾸는 작업** — 위 표의 항목들을 같이 고쳐야 합니다.

## 텔레옵 구성 (확인됨)

- **방식 (B)**: 리더암으로 양팔 + **키보드로 바퀴**.
- 라즈베리파이에서 `xlerobot_host` 를 띄우고 PC 가 붙습니다.
  → 녹화 쪽 로봇 타입은 `xlerobot` 이 아니라 **`xlerobot_client`** 이고
    `remote_ip` (파이의 IP) 가 필요합니다. ZMQ 포트 5555(명령) / 5556(관측).

## 🔴 가장 급한 것 — 녹화 설정이 레포 밖에 있습니다

지금 돌아가는 3카메라 녹화 설정은 **가상환경 안의 파일을 직접 고친 것**입니다.
이건 두 가지로 위험합니다:

1. **팀원이 볼 수 없습니다.** 레포를 clone 해도 그 수정은 안 따라옵니다.
2. **`pip install -U` 한 번에 날아갑니다.** 재현도 안 됩니다.

마감 2주에 이게 제일 큰 리스크입니다. 그 파일을 레포 안으로 옮기는 게
다음 작업입니다.

### 왜 단순 복사가 아닌가 — 상류 `record.py` 의 멀티 텔레옵 제약 3개

리더암 + 키보드를 같이 쓰는 경로(`record_loop` 의 `isinstance(teleop, list)` 분기)에
`xlerobot` 과 안 맞는 데가 세 군데 있습니다:

```python
# 1. 로봇 이름 게이트 — xlerobot_client 는 통과 못 함
if not (... and robot.name == "lekiwi_client"):
    raise ValueError("... Currently only supported for LeKiwi robot.")

# 2. 리더암 클래스 목록 — 양팔 리더는 여기 없음
teleop_arm = next((t for t in teleop if isinstance(
    t, (so100_leader.SO100Leader, so101_leader.SO101Leader,
        koch_leader.KochLeader))), None)

# 3. 액션 키 접두사 — LeKiwi(팔 1개) 기준
arm_action = {f"arm_{k}": v for k, v in arm_action.items()}
#   LeKiwi    : arm_shoulder_pan.pos
#   xlerobot  : left_arm_shoulder_pan.pos / right_arm_shoulder_pan.pos
#   -> 그냥 쓰면 키가 안 맞습니다
```

지금 설정이 3카메라로 **돌아가고 있다**는 건 이 세 개를 이미 어떤 식으로든
해결했다는 뜻입니다. 그래서 새로 쓰지 말고 **그 파일을 가져와서 레포에 넣어야**
합니다.

### 환경: lerobot 0.6 (venv)

돌아가는 설정은 **lerobot 0.6** 가상환경 안에 있습니다. 임포트 경로와 CLI 플래그가
버전마다 바뀌므로, 코드를 맞출 때는 이 버전 기준으로 맞춰야 합니다.

### 참고: 상류는 포크된 lerobot 을 전제합니다

`software/src/record.py` 가 `from lerobot.robots import xlerobot` 로 임포트합니다.
플러그인 설치 방식(`register_third_party_plugins`)과 섞여 있어서, 어느 쪽으로
설치돼 있는지에 따라 임포트 경로가 다릅니다. 실제 환경 기준으로 맞춰야 합니다.

## 팀 작업 규칙

- **카메라 장치 경로를 `scripts/record.sh` 에 다시 적지 마세요.**
  `config/cameras.*.yaml` 에만 있고, 녹화(`record.sh`)와 추론(`arm_node.py`)이
  같은 파일을 읽습니다. 어긋나면 팔이 아예 안 움직입니다. `tests_smoke.py` 가 막습니다.
- 카메라 구성이 다르면 데이터셋도 분리됩니다 (`xlerobot-dice-3cam` / `-4cam`).
  관측 키가 다른 데이터를 한 데이터셋에 섞으면 깨집니다.
- 코드를 고쳤으면 `python tests_smoke.py` 를 먼저 돌리세요 (하드웨어 없이 돕니다).
- 지금 뭐가 돌아가고 뭐가 아직인지는 `README.md` 의 상태 표를 보세요.
