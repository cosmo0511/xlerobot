# XLeRobot — 모방학습 기반 자율주행 양팔 로봇

말로 명령하면 로봇이 해당 장소로 자율주행해서, 양팔 SmolVLA 정책으로 태스크를 수행합니다.

```
"빨간 거 가져와"
   → 명령 해석 (Gemini, 태스크 하나로 분류)
   → [팔 접기] → 1번 책상 이동 → "Pick up the red dice"
   → [팔 접기: 그리퍼 유지] → 2번 책상 이동 → "Place the dice on the red spot"
```

태스크는 **단계의 나열**이라 이동이 중간에 끼는 것도 표현됩니다.
색은 지시문으로 구분합니다 — SmolVLA 가 vision-**language**-action 모델이라서요.

## 기기 구성

| | 기기 | 담당 | 프로세스 |
|---|---|---|---|
| 🦾 | Pi-A | SO-101 양팔 + 카메라 3개 | `python src/arm_node.py` |
| 🛞 | Pi-B | 르키위 베이스 + 라이다 + Nav2 | `nav2_bringup` + `python src/nav_node.py` |
| 💻 | PC | SmolVLA 추론 + 에이전트 | `lerobot-policy-server` + `python src/main.py` |

## 문서

| 문서 | 언제 읽나 |
|---|---|
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | 코드 읽기 전에. 무엇이 어디서 도는지 |
| **[RUNNING.md](RUNNING.md)** | 실제로 돌릴 때. 0단계부터 순서대로 |
| **[TELEOP.md](TELEOP.md)** | 리더암이 노트북에 있을 때. host/client 로 텔레옵·녹화 |
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

## 구조

```
config/
  tasks.yaml       태스크·위치 정의 (단일 진실 소스)
  robot.yaml       IP·포트·카메라·파킹 자세
src/
  xlerobot_devices/  🦾💻 host/client 로봇 + 리더암2개+키보드 텔레옵 (lerobot 플러그인)
  arm_node.py      🦾 Pi-A — 팔 소유, 30Hz 제어, ZMQ 명령 수신
  main.py          💻 PC  — 진입점 (조립 + 명령 루프)
  agent.py         💻 PC  — 명령 → 태스크 라우팅
  nav_node.py      🛞 Pi-B — Nav2 액션 호출, ZMQ 명령 수신
  navigation.py    💻 PC  — Pi-B 에 목표 보내는 클라이언트
  policy_client.py 💻 PC  — Pi-A 에 명령 보내는 클라이언트
  task_registry.py 💻 PC  — YAML 로더 + 검증
scripts/
  xle_env.sh       공통 설정 (IP·포트·카메라) — 고치는 건 여기만
  host.sh          🦾 Pi  — 팔·바퀴·카메라를 열고 ZMQ 로 노출
  teleop.sh        💻 노트북 — 리더암으로 조종
  record.sh        💻 노트북 — 데모 녹화 (라벨 6종을 인자로)
tests_smoke.py     하드웨어 없이 도는 에이전트 로직 검증
tests_devices.py   host/client/텔레옵의 action 키가 맞는지 검증
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
