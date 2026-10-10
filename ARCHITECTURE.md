# 구조 — 기기 3대를 어떻게 나눌 것인가

코드를 읽기 전에 이것부터. 무엇이 어디서 도는지, 왜 그렇게 나눴는지.

---

## 기기 배치

```
🦾 Pi-A  양팔 라즈베리파이
         SO-101 팔로워 x2 (USB 직결)
         리더암 x2 (데모 수집용)
         카메라 — 구성은 config/cameras.<이름>.yaml
           3cam: 탑캠 + 손목캠 x2   /   4cam: + 베이스캠

🛞 Pi-B  르키위 라즈베리파이
         옴니휠 베이스 + 라이다
         ROS2 / SLAM / Nav2 스택

💻 PC    GPU 머신
         SmolVLA 추론 서버
         에이전트 (명령 해석 + 오케스트레이션)
```

**팔과 베이스가 물리적으로 분리돼 있습니다.** 같은 시리얼 버스를 공유하지 않으므로
동시에 움직여도 충돌하지 않습니다. 조율은 소프트웨어 정책으로만 하면 됩니다.

---

## 1. 데이터가 흐르는 방향

```
🦾 Pi-A ──── gRPC (lerobot async inference) ────► 💻 PC
             관측(이미지 3장 + 관절 12개)              SmolVLA 추론
        ◄─── 행동 청크 50개 ──────────────────────
             30Hz 제어 루프는 Pi-A 안에서 로컬

💻 PC ────── ROS2 DDS (NavigateToPose) ─────────► 🛞 Pi-B
             목표 pose 하나                          Nav2 스택 전부
        ◄─── 도착/실패 ────────────────────────────

💻 PC ────── ZMQ REQ/REP ───────────────────────► 🦾 Pi-A
             {"cmd":"run","task":"Water the plant"}
        ◄─── {"status":"done"} ────────────────────
```

### 이미지를 매 프레임 보내지 않습니다

SmolVLA 는 추론 한 번에 행동을 **50개 묶음(action chunk)** 으로 돌려줍니다.
Pi-A 는 그 큐가 절반 이하로 줄 때만 새 관측을 보냅니다 — **약 0.8초에 한 번**.

| 방식 | 대역폭 | WiFi |
|---|---|---|
| 매 프레임 전송 (30fps × 3장) | 약 80MB/s | 불가 |
| 청크 방식 (0.8초당 3장) | 약 2MB/s | 여유 |

제어 루프(30Hz)는 Pi-A 로컬에서 돌기 때문에 네트워크가 잠깐 끊겨도 큐에 남은 행동을
계속 수행합니다. 이게 lerobot async inference 의 설계 의도입니다.

### 왜 팔 노드를 따로 두나

PC 가 팔을 직접 잡으면 30Hz 제어 루프에 네트워크 지터가 섞여 동작이 끊깁니다.
그래서 Pi-A 가 `arm_node.py` 로 팔을 소유하고, PC 는 "이 태스크 해라 / 다 되면 알려줘"만
보냅니다. 태스크 문자열은 관측마다 같이 실려 가므로 **태스크를 바꿔도 정책을 다시 로드하지
않습니다** (재로딩은 10~30초 걸립니다).

---

## 2. 순차 실행과 파킹

주행과 조작을 순차로만 씁니다: **이동 → 정지 → 조작**.

하드웨어가 분리돼 있어 동시 실행도 가능하지만, 순차로 두는 이유가 있습니다.

- 데모 수집을 정지 상태로 하므로, 정책은 "베이스가 멈춘 장면"만 학습합니다.
- 트롤리 결합 상태에서 이동 중 팔을 쓰면 무게중심 때문에 크게 흔들립니다.

대신 **파킹**이 새로 필요합니다. Pi 가 하나였다면 이동 중 팔은 마지막 자세로 홀드되지만,
지금은 팔이 벌어진 채로 베이스가 출발할 수 있습니다. 그래서 에이전트가 이동 전에 항상
팔을 접습니다.

```
명령 → 파킹 → 이동 → 안정화 대기 → 조작
        │
        └─ 실패하면 이동하지 않습니다 (문틀·가구 충돌 방지)
```

파킹 자세는 `config/robot.yaml` 의 `travel_pose`. 실제 값은
`lerobot-find-joint-limits` 로 로봇에서 확인해 채우세요.

---

## 3. 태스크 목록이 세 군데에 있었습니다

기존에는 태스크 문자열이 `agent.py` 의 `DESK_OF_TASK`, `INTERFACE.md` 표,
`policy_client.py` docstring 세 곳에 따로 있었습니다. 하나를 바꾸면 세 곳을 다 고쳐야
하고, 한 곳을 빠뜨리면 학습 라벨과 글자가 다른 지시문이 정책에 들어갑니다.

**그런데 이건 에러가 안 납니다.** 그냥 조용히 성능만 떨어집니다. 디버깅할 때 제일 늦게
의심하게 되는 종류의 버그입니다.

### 해결: `config/tasks.yaml` 하나로

```yaml
locations:
  - id: bedroom
    name: 안방
    pose: {x: 2.41, y: -1.08, yaw: 92.5}   # Nav2 map 프레임, yaw 는 도

tasks:
  - prompt: "Water the plant"              # 학습 라벨과 글자까지 동일
    location: bedroom
    max_seconds: 150
```

- `task_registry.py` 가 **프로그램 시작 시점에 검증**합니다. 잘못된 설정이면 로봇이
  움직이기 전에 죽습니다. 앞뒤 공백까지 거부합니다.
- `agent.py` 는 이 목록으로 LLM 응답 스키마를 런타임에 생성합니다. 모델이 학습 라벨
  아닌 문자열을 물리적으로 뱉을 수 없습니다.
- 장소를 늘리고 줄이는 건 YAML 몇 줄. `desk_1/2/3` 처럼 개수가 코드에 박혀 있지 않습니다.

---

## 4. 카메라 이름 규칙 — 여기서 자주 틀립니다

`bi_so_follower` 는 카메라 이름에 접두사를 자동으로 붙입니다.

| 구성 파일에 적는 곳 | 적는 이름 | 최종 관측 키 |
|---|---|---|
| `top_cameras` | `top` | `observation.images.top` |
| `top_cameras` | `base` | `observation.images.base` |
| `left_cameras` | `wrist` | `observation.images.left_wrist` |
| `right_cameras` | `wrist` | `observation.images.right_wrist` |

팔에 묶인 카메라는 `left_` / `right_` 가 붙고, 팔에 안 묶인 건(탑캠·베이스캠)
그대로입니다. `top_cameras` 라는 이름이 혼동스럽지만 "로봇 몸체에 달린 카메라"
라는 뜻이라, 베이스캠도 여기 들어갑니다.

**이 최종 키가 데모 수집 때와 같아야** SmolVLA 가 이미지를 찾습니다.
다르면 정책이 행동을 하나도 못 내놓고 팔이 가만히 있습니다.

### 그래서 카메라 설정은 한 곳에만 둡니다

전에는 같은 이름을 두 곳에 손으로 적어뒀습니다 — `scripts/record.sh`(녹화)와
`config/robot.yaml`(추론). 한쪽만 고치면 그때부터 조용히 어긋납니다.

지금은 둘 다 `config/cameras.<이름>.yaml` 하나를 읽습니다:

```
config/cameras.3cam.yaml ──┬── scripts/record.sh   (녹화)
                           └── src/arm_node.py     (추론)
                                 ↑ 둘 다 src/camera_config.py 경유
```

운용 구성은 `robot.yaml` 의 `arms.camera_set` 이, 녹화 구성은 환경변수
`CAMERA_SET` 이 정합니다. 구성을 늘리려면 yaml 파일을 하나 더 만들면 됩니다 —
**브랜치를 나누지 마세요.** 코드는 한 벌이고 설정만 여러 벌입니다.

---

## 전체 흐름

```
사용자: "화분에 물 좀 줘"
    │
    ├─ agent.CommandParser        Gemini 로 라벨 중 하나로 분류
    │                             → "Water the plant"
    │                             (스키마 enum 이라 다른 문자열 불가)
    │
    ├─ registry.location_of(...)  위치는 코드가 결정. LLM 출력 안 씀
    │                             → "bedroom"
    │
    ├─ arms.park()                🦾 Pi-A: 팔을 주행 자세로
    │                             → 실패하면 여기서 중단
    │
    ├─ navigator.navigate_to(...) 🛞 Pi-B: Nav2 목표 전송, 도착 대기
    │                             도착 후 settle_s 만큼 정지
    │                             → arrived 아니면 여기서 중단
    │
    └─ arms.run("Water the plant", max_seconds=150)
                                  🦾 Pi-A: 30Hz 루프
                                  💻 PC:   SmolVLA 청크 계산
                                  → {"status": "done"}
```

## 파일별 책임

| 파일 | 도는 곳 | 하는 일 |
|---|---|---|
| `config/tasks.yaml` | — | 태스크·위치·좌표 정의 |
| `config/robot.yaml` | — | IP·포트·파킹 자세 + 쓸 카메라 구성 이름 |
| `config/cameras.*.yaml` | — | 카메라 목록 (녹화·추론 공용 단일 진실 소스) |
| `src/camera_config.py` | 🦾 Pi-A | 카메라 설정 로더 + 장치 검사 |
| `src/arm_node.py` | 🦾 Pi-A | 팔 소유, 30Hz 제어, ZMQ 명령 수신 |
| `src/policy_client.py` | 💻 PC | Pi-A 에 명령 보내는 얇은 클라이언트 |
| `src/navigation.py` | 💻 PC | Nav2 목표 전송, 도착 대기 |
| `src/agent.py` | 💻 PC | 명령 → 태스크 라우팅, 순서 강제 |
| `src/task_registry.py` | 💻 PC | YAML 로드 + 검증 |
| `src/main.py` | 💻 PC | 조립 + 명령 루프 |

## 담당 나누기

세 사람이 병렬로 작업할 수 있게 경계를 잡아뒀습니다.

- **자율주행** — 🛞 Pi-B 의 ROS2 스택. `NavigateToPose` 액션과 `map` 프레임만 맞으면
  내부는 자유입니다. PC 쪽 `navigation.py` 는 목표만 던집니다.
- **SmolVLA** — 데모 수집 → 학습 → `arm_node.py` 의 `run_task` 튜닝.
  태스크별 `max_seconds` 와 `travel_pose` 담당.
- **에이전트** — `agent.py` + `config/tasks.yaml` 의 `aliases` 관리.

세 명 다 `--dry-run` 으로 나머지 둘 없이 자기 부분을 돌려볼 수 있습니다.
