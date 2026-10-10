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
- **텔레옵을 `xlerobot` 으로 돌렸는지, `xlerobot_client` 로 돌렸는지.**
  전자는 라즈베리파이에서 다 돌리는 것, 후자는 파이에서 `xlerobot_host` 를 띄우고
  PC 가 ZMQ(5555/5556)로 붙는 것입니다. 우리 구성(PC ←무선→ 파이)은 후자처럼
  보이지만 확인이 필요합니다. 액션 공간은 둘이 같고 포트/IP 플래그만 다릅니다.
- **`record.sh` 를 `xlerobot` 으로 바꾸는 작업** — 위 표의 항목들을 같이 고쳐야 합니다.

## 팀 작업 규칙

- **카메라 장치 경로를 `scripts/record.sh` 에 다시 적지 마세요.**
  `config/cameras.*.yaml` 에만 있고, 녹화(`record.sh`)와 추론(`arm_node.py`)이
  같은 파일을 읽습니다. 어긋나면 팔이 아예 안 움직입니다. `tests_smoke.py` 가 막습니다.
- 카메라 구성이 다르면 데이터셋도 분리됩니다 (`xlerobot-dice-3cam` / `-4cam`).
  관측 키가 다른 데이터를 한 데이터셋에 섞으면 깨집니다.
- 코드를 고쳤으면 `python tests_smoke.py` 를 먼저 돌리세요 (하드웨어 없이 돕니다).
- 지금 뭐가 돌아가고 뭐가 아직인지는 `README.md` 의 상태 표를 보세요.
