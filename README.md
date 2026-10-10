# XLeRobot — 모방학습 기반 자율주행 양팔 로봇

로봇이 1 m 앞 테이블까지 주행해서, **지시한 색의 주사위를 그쪽 팔로 집어 바구니에** 넣습니다.
주행·집기·넣기를 정책(SmolVLA) 하나가 전부 냅니다. 자율주행은 안 씁니다.

```
"빨간 거 넣어줘"
   → 명령 해석 (Gemini, 태스크 하나로 분류)
   → [팔 접기] → "Pick up the red dice and put it in the basket"
```

장면은 그대로 두고 지시문만 red ↔ blue 로 바꿔서, 정책이 **언어를 보고** 팔을 고르는지
검증합니다 (ACT = 언어 없는 대조군). 실험·수집 절차는 [COLLECTING.md](COLLECTING.md).

## 기기 구성

| | 기기 | 담당 | 프로세스 |
|---|---|---|---|
| 🍓 | 라즈베리파이 | SO-101 양팔 + 바퀴 3개(오른팔 버스) + 카메라, USB | `./scripts/host.sh` |
| 💻 | PC | 녹화 / SmolVLA 추론 + 추론 노드 + 에이전트 | `./scripts/record.sh` 또는 `lerobot-policy-server` + `python src/arm_node.py` + `python src/main.py` |

PC 와 파이는 무선으로 붙습니다. 패치된 lerobot 0.6 이 둘 다 필요합니다 → [vendor/README.md](vendor/README.md).
(예전 Pi-A / Pi-B 두 대 구성은 폐기. Nav2 쪽 문서·코드는 아직 그 구성 기준입니다.)

## 지금 어디까지 돌아가나

코드가 다 있다고 다 쓰는 건 아닙니다. 순서대로 붙이는 중입니다.

| 파일 | 상태 | 언제 쓰나 |
|---|---|---|
| `scripts/record.sh`, `config/cameras.*.yaml` | ✅ **지금 쓰는 것** | 데모 데이터 수집 |
| `src/camera_config.py` | ✅ 지금 쓰는 것 | 녹화·추론이 공유하는 카메라 설정 |
| `src/view_cameras.py` | ✅ 지금 쓰는 것 | 카메라 화면 확인 (따로 실행) |
| `src/preflight_cameras.py`, `scripts/run_4cam.sh` | ✅ 지금 쓰는 것 | 4cam 검증 + 4cam 전용 진입점 |
| `src/arm_node.py`, `src/policy_client.py` | ⏳ 학습 끝나면 | SmolVLA 추론 |
| `src/nav_node.py`, `src/navigation.py` | ❌ 안 씀 | 자율주행 안 쓰기로 함 (`navigation.enabled: false`) |
| `src/agent.py`, `src/task_registry.py` | ⏸ 다단계 태스크 단계 | 말로 명령 → 태스크 라우팅 (LLM) |

⏸ 는 **아직** 안 쓰는 것이지 버린 코드가 아닙니다. `python src/main.py --dry-run`
으로는 지금도 전체 흐름이 돕니다 (하드웨어 없이).

## 문서

| 문서 | 언제 읽나 |
|---|---|
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | 코드 읽기 전에. 무엇이 어디서 도는지 |
| **[RUNNING.md](RUNNING.md)** | 실제로 돌릴 때. 0단계부터 순서대로 |
| **[COLLECTING.md](COLLECTING.md)** | 데모 데이터 모을 때. 태스크 하나부터 |
| **[NAV2_SETUP.md](NAV2_SETUP.md)** | 자율주행 붙일 때. 체크리스트 8단계 |
| [INTERFACE.md](INTERFACE.md) | 모듈 간 계약. 담당 나눠서 작업할 때 |

## 5분 안에 돌려보기

```bash
pip install pyyaml pyzmq
python src/main.py --dry-run
python tests_smoke.py
```

하드웨어 없이 에이전트 → 파킹 → 자율주행 → 조작 흐름이 전부 돕니다.

## 카메라 구성

카메라 목록은 `config/cameras.<이름>.yaml` **한 곳**에만 있습니다.
녹화(`scripts/record.sh`)와 추론(`src/arm_node.py`)이 같은 파일을 읽습니다.

```bash
python src/camera_config.py              # 쓸 수 있는 구성 목록
python src/camera_config.py 3cam --check # 장치가 실제로 있는지
```

| 구성 | 카메라 | 관측 키 |
|---|---|---|
| `3cam` | 탑 + 손목 x2 | `top`, `left_wrist`, `right_wrist` |
| `4cam` | 탑 + 베이스 + 손목 x2 | `top`, `base`, `left_wrist`, `right_wrist` |

**운용 구성은 `config/robot.yaml` 의 `arms.camera_set` 이 정합니다.**
녹화할 때만 바꾸려면 환경변수로:

```bash
CAMERA_SET=4cam ./scripts/record.sh red 12 --first
```

### ⚠️ 카메라 이름이 어긋나면 팔이 안 움직입니다

정책은 학습 때 본 이미지 키만 받습니다. 녹화 때와 추론 때 키가 다르면
행동을 하나도 못 내놓고 팔이 가만히 있습니다 — 원인을 찾기 어려운 고장입니다.
그래서 두 경로가 같은 파일을 읽게 묶어뒀습니다. `record.sh` 에 장치 경로를
다시 적지 마세요 (`tests_smoke.py` 가 막습니다).

### 왜 브랜치가 아니라 설정 파일인가

카메라 구성이 다르다고 브랜치를 나누면, 버그 하나를 양쪽에 각각 고쳐야 하고
몇 주 뒤엔 어느 쪽이 맞는지 알 수 없게 됩니다. 코드는 한 벌, 설정은 여러 벌로
둡니다. 브랜치는 비교가 끝나고 한쪽을 지울 때 쓰면 됩니다.

### 데이터셋은 구성별로 분리됩니다

`record.sh` 가 데이터셋 이름에 구성을 붙입니다 (`xlerobot-dice-3cam`,
`xlerobot-dice-4cam`). 카메라 구성이 다른 데이터를 한 데이터셋에
`--resume` 으로 이어붙이면 관측 키가 안 맞아 데이터셋이 깨집니다.

### 카메라를 몇 개로 찍어야 하나

**녹화는 되돌릴 수 없고 학습은 몇 번이든 되돌릴 수 있습니다.** 그래서 `4cam`
으로 다 찍어두고, 학습할 때 정책 입력 키만 골라서 비교하는 게 낫습니다:

| 실험 | 입력 키 | 묻는 것 |
|---|---|---|
| A | `top` + 손목 x2 | 기존 조건 (베이스라인) |
| B | `top` + `base` | 베이스캠이 손목캠을 대체하나 |
| C | 4개 전부 | 베이스캠이 보태는 게 있나 |

한 번 찍은 데이터셋으로 셋 다 돌릴 수 있습니다. 다만 lerobot 은 데이터셋
메타에서 입력 feature 를 자동으로 뽑으므로, 일부만 쓰려면 학습 config 에서
입력 이미지 키를 명시적으로 제한해야 합니다.

### 4cam 으로 돌리는 순서

`run_4cam.sh` 가 `CAMERA_SET=4cam` 을 한 곳에서 박습니다. 파이와 PC 의 구성이
어긋나면 **파이가 안 보낸 카메라 칸이 검은 화면으로 조용히 녹화됩니다**
(`bi_so_base_client` 가 못 받은 카메라를 `np.zeros` 로 채웁니다). 그래서
`record` 는 검증을 통과해야 녹화를 시작합니다.

```bash
# 🍓 파이 — 처음 한 번 (카메라 자리 정하기)
./scripts/run_4cam.sh scan        # 어느 /dev/video* 가 진짜 카메라인지 + 고정 경로
./scripts/run_4cam.sh identify    # 장치마다 한 장 찍어 저장 -> 보고 yaml 에 배정
./scripts/run_4cam.sh selftest    # 4대가 동시에 열리는지 + 실측 fps + 대역폭

# 🍓 파이 — 매번
./scripts/run_4cam.sh host

# 💻 PC — 매번
./scripts/run_4cam.sh check              # 녹화와 같은 경로로 검증
./scripts/run_4cam.sh record red 8 --first
./scripts/run_4cam.sh record red 8       # 이어찍기 (--first 없이)
./scripts/run_4cam.sh status             # 몇 개 찍었나
```

### 중간에 끊고 이어 찍기

같은 명령을 다시 치면 이어집니다. `--first` 는 **데이터셋 전체에 한 번만**이고
(색깔마다가 아닙니다), 데이터가 이미 있는데 주면 멈춥니다 (실수로 처음부터 다시
찍는 걸 막습니다).

```bash
./scripts/run_4cam.sh record red  8 --first   # 데이터셋 생성 (딱 한 번)
./scripts/run_4cam.sh record blue 8           # 같은 데이터셋에 이어짐
./scripts/run_4cam.sh record red  8           # 계속 이어짐
```

red/blue 가 한 데이터셋에 섞이는 게 **맞습니다.** 지시문은 에피소드마다 따로
기록되고(`task_index`), 정책이 언어를 보고 팔을 고르는지 보려면 한 데이터셋에
둘 다 있어야 합니다. 확인한 동작: 새 지시문으로 이어찍으면 추가되고(`task_index 1`),
이미 있는 지시문이면 중복 등록되지 않습니다. 데이터셋을 쪼개는 건 **카메라 구성**
뿐입니다 — 이어찍기 때 lerobot 이 features(카메라 키)와 fps 를 검사해 어긋나면 거부합니다.

깔끔하게 멈추는 법: `→`(또는 `n`)로 지금 에피소드를 끝내고, **리셋 시간에**
`ESC`(또는 `q`). 에피소드 **도중** `ESC` 는 그때까지 찍힌 토막을 저장해버립니다
(`lerobot_record.py` 가 `stop_recording` 이어도 `save_episode()` 를 부릅니다).
토막이 생겼으면 `./scripts/run_4cam.sh droplast` 로 지우세요.

> 데이터셋 폴더는 `scripts/dataset_path.sh` 가 고정합니다. lerobot 0.6 은 새로
> 만들 때 repo_id 에 타임스탬프를 붙이므로(`stamp_repo_id`), `--dataset.root` 를
> 고정하지 않으면 **2회차부터 이어찍기가 아예 안 됩니다** (폴더를 못 찾고 Hub 로
> 가서 401). Hub 업로드는 기본으로 꺼져 있습니다 — `PUSH_TO_HUB=1` 로 켜세요.

`4cam` 을 쓸 때 주의:

- **베이스캠 USB 는 Pi-A 에 꽂으세요.** `lerobot-record` 와 `arm_node.py` 는
  Pi-A 가 USB 로 직접 연 카메라만 관측에 넣습니다. Pi-B(르키위)에 꽂으면
  네트워크로 영상을 끌어와야 하고 그건 기본 지원이 없습니다.
- **USB 대역폭.** 640x480 30fps 4대는 MJPEG 이면 보통 버티지만 YUYV(raw) 로
  열리면 못 버팁니다. 프레임이 끊기면 fps 를 낮추거나 허브를 나눠 꽂으세요.

## 구조

```
config/
  tasks.yaml       태스크·위치 정의 (단일 진실 소스)
  robot.yaml       IP·포트·파킹 자세 + 쓸 카메라 구성 이름
  cameras.3cam.yaml  탑 + 손목 x2            (녹화·추론 공용)
  cameras.4cam.yaml  탑 + 베이스 + 손목 x2    (녹화·추론 공용)
src/
  camera_config.py 카메라 설정 로더 (녹화·추론의 단일 진실 소스)
  arm_node.py      🦾 Pi-A — 팔 소유, 30Hz 제어, ZMQ 명령 수신
  main.py          💻 PC  — 진입점 (조립 + 명령 루프)
  agent.py         💻 PC  — 명령 → 태스크 라우팅
  nav_node.py      🛞 Pi-B — Nav2 액션 호출, ZMQ 명령 수신
  navigation.py    💻 PC  — Pi-B 에 목표 보내는 클라이언트
  policy_client.py 💻 PC  — Pi-A 에 명령 보내는 클라이언트
  task_registry.py 💻 PC  — YAML 로더 + 검증
scripts/
  record.sh        🦾 Pi-A — 데모 녹화 (라벨 6종을 인자로, CAMERA_SET 으로 구성 선택)
tests_smoke.py     하드웨어 없이 도는 로직 검증
```

## 담당

| 담당 | 범위 | 단독 테스트 |
|---|---|---|
| 자율주행 | 🛞 Pi-B 의 ROS2 스택 + 좌표 측정 | `python src/main.py --dry-run` |
| SmolVLA | 데이터 수집·학습 + `arm_node.py` | `lerobot-rollout` |
| 에이전트 | `agent.py` + `tasks.yaml` aliases | `python src/main.py --dry-run --once "..."` |

## ⚠️ 보안

API 키를 소스에 쓰지 마세요. 환경변수로만 넘깁니다.

```bash
export GEMINI_API_KEY="..."
```

`config/*.yaml` 에도 키를 넣지 않습니다. 실수로 커밋되면 공개 저장소에서 즉시 수집됩니다.
