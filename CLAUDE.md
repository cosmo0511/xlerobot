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

## 로봇 클래스 — 바퀴를 녹화에 넣으려면

상류 [XLeRobot](https://github.com/Vector-Wangel/XLeRobot) 소스에서 확인한 사실입니다
(`software/src/robots/xlerobot/`).

우리 하드웨어는 `--robot.type=xlerobot` 과 정확히 일치합니다:

| 버스 | 모터 |
|---|---|
| `port1` | 왼팔 ID 1–6 + 머리 `head_motor_1`(7), `head_motor_2`(8) |
| `port2` | **오른팔 ID 1–6 + 바퀴 `base_left_wheel`(7), `base_back_wheel`(8), `base_right_wheel`(9)** |

`port2` 가 우리가 "바퀴 789 를 오른팔에 연결" 한 그 버스입니다.

**액션 공간 17차원** (`xlerobot_client.py` 의 `_state_ft`):

```
왼팔  6   left_arm_shoulder_pan.pos  ...  left_arm_gripper.pos
오른팔 6  right_arm_shoulder_pan.pos ...  right_arm_gripper.pos
머리  2   head_motor_1.pos  head_motor_2.pos
베이스 3  x.vel  y.vel  theta.vel        ← 바퀴는 속도 제어. 개별 바퀴가 아닙니다
```

키보드 베이스 조작 기본 키: `i`/`k` 전후, `j`/`l` 좌우, `u`/`o` 회전,
`n`/`m` 속도, `b` 종료 (`XLerobotConfig.teleop_keys`).

쓰려면 플러그인을 설치해야 `--robot.type=xlerobot` 이 CLI 에 뜹니다:

```bash
pip install -e software/plugins/xlerobot_model
pip install -e software/plugins/lerobot_robot_xlerobot
```

### ⚠️ 지금 record.sh 는 바퀴를 못 찍습니다

`scripts/record.sh` 는 `--robot.type=bi_so_follower` 입니다 — **팔 12축만** 저장하고
바퀴는 안 들어갑니다. 상류 XLeRobot 문서의 녹화 예시도 `bi_so101_follower`(팔만)
라서, 그걸 따라가면 바퀴가 빠집니다.

바퀴를 넣으려면 `xlerobot` 으로 바꿔야 하고, 그러면 같이 바뀌는 것들:

| 항목 | `bi_so_follower` (현재) | `xlerobot` |
|---|---|---|
| 포트 플래그 | `--robot.left_arm_config.port` / `right_arm_config.port` | `--robot.port1` / `--robot.port2` |
| 카메라 | 팔별로 나눠 넘기고 `left_`/`right_` 접두사 자동 | `--robot.cameras` 하나, 접두사 **자동 안 붙음** |
| 관절 이름 | `left_shoulder_pan.pos` | `left_arm_shoulder_pan.pos` |
| 그리퍼 이름 | `right_gripper.pos` | `right_arm_gripper.pos` |

관절 이름이 바뀌므로 `config/robot.yaml` 의 `travel_pose` 와
`grasp_check.joint` 도 같이 고쳐야 합니다.

**카메라 쪽은 이미 양쪽을 지원합니다.** `camera_config.py` 가 로봇 타입에 맞는
형태로 인자를 만들어 주고, **최종 관측 키는 두 경우에 똑같습니다**
(`observation.images.top` / `.base` / `.left_wrist` / `.right_wrist`).
그래서 로봇 클래스를 바꿔도 정책의 카메라 키는 안 바뀝니다.

```bash
python src/camera_config.py 4cam --record-args                        # per_arm
python src/camera_config.py 4cam --record-args --robot-type=xlerobot  # flat
```

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
