# XLeRobot — 언어 지시를 보고 팔을 고르는 양팔 모바일 로봇

로봇이 1 m 앞 테이블까지 주행해서, **지시한 색(빨강/노랑)의 주사위를 그쪽 팔로 집어 바구니에** 넣습니다.
주행·집기·넣기를 정책 하나가 전부 냅니다 (자율주행·Nav2 안 씀).

```
"Pick up the red dice and put it in the basket"     ← 장면은 같고 지시문만 red ↔ yellow
   → 정책이 카메라 4대 + 지시문을 보고 15차원 행동(양팔 12 + 바퀴 3)을 50스텝씩 냄
```

**묻는 것: 정책이 정말 언어를 보고 팔을 고르나?** 장면을 똑같이 두고 지시문만 바꿔서,
언어를 보는 모델과 못 보는 모델의 팔 선택 정확도를 비교합니다. 언어를 못 보면 50% 를 넘을 수 없습니다.
실험 설계·수집 절차는 [COLLECTING.md](COLLECTING.md).

## 지금 어디까지 왔나 (2026-10-13)

| 단계 | 상태 |
|---|---|
| 하드웨어·4cam 세팅 | ✅ 끝 |
| 데이터 v1 — 빨강/파랑 96개 (`bilimili/xlerobot-dice-4cam`) | ✅ 찍음 → 10/12 주사위를 파랑→노랑으로 바꾸면서 **v2 로 대체** (지금 학습엔 안 씀) |
| 데이터 v2 — 빨강/노랑 104개, 66분 (`bilimili/xlerobot-dice-4cam-v2`) | ✅ 끝 (2026-10-12) |
| 예비 평가 (v1 모델) | ✅ 10/11 — 안전정지(양팔 급동작)로 대부분 중단. 기록: [results/](results/) |
| 학습 (v2 데이터, 아래 3개 정책) | ⏳ **진행 중** |
| 본 평가 (정책당 36회) | ⬜ 학습 끝나면 |
| 원고 제출 | ⬜ 10/23 |

### 비교하는 정책

모두 같은 데이터(v2)·같은 조건(batch 16 / 80k 스텝, 평가는 마지막 체크포인트) — [RUNNING.md](RUNNING.md) 3단계.

| 정책 | 언어 | 역할 | 학습 명령 |
|---|---|---|---|
| **SmolVLA** | 봄 | 본 모델 | `./scripts/train.sh smolvla` |
| **SmolVLA no-lang** | 안 봄 | 같은 구조에서 언어만 뺀 대조군 | ⚠️ 학습 중, **사용한 변경이 아직 레포에 없음** |
| **ACT** | 안 봄 | 언어 없는 다른 구조의 대조군 | `./scripts/train.sh act` |

## 기기 구성

```
💻 PC (GPU)          ←Wi-Fi→   🍓 라즈베리파이           ←USB→   🤖 로봇
   녹화 / 추론                    host.sh (ZMQ 5555/5556)          SO-101 양팔 + 옴니휠 3개 + 카메라 4대
🖥 GPU 서버 (RTX 5090)            학습만 (docker/)
```

- 파이는 팔·바퀴·카메라를 열어 그대로 PC 에 넘기기만 합니다. 녹화·추론은 둘 다 PC 에서 **같은 로봇 클래스**
  (`bi_so_base_client`)로 붙어서 관측·행동 형식이 똑같습니다.
- 상류 XLeRobot 이 아니라 **lerobot 0.6 을 직접 패치**해서 씁니다 (`bi_so_base_*`). 양쪽 다 필요 → [vendor/README.md](vendor/README.md).
- 무선이라 이미지를 매 프레임 보내지 않고, 정책 서버에서 행동을 50스텝씩(action chunk) 받아옵니다.

## 한눈에 보는 실행 순서

```bash
# 0. 하드웨어 없이 확인 (코드 고쳤으면 먼저)
python tests_smoke.py

# 1. 녹화 — 🍓 파이 / 💻 PC
./scripts/run_4cam_v2.sh host                      # 파이
./scripts/run_4cam_v2.sh check                     # PC: 녹화와 같은 경로로 카메라 검증
./scripts/run_4cam_v2.sh record red 8 [--first]    # PC: 블록 순서는 COLLECTING.md 3절

# 2. 학습 — 🖥 GPU 서버 (docker/README.md)
PERSIST_DIR=/workspace/xlerobot ./scripts/train.sh smolvla   # 또는 act

# 3. 평가 — 💻 PC (파이에서 host 를 띄운 상태)
lerobot-policy-server --host=127.0.0.1 --port=8080
python src/arm_node.py          # 정책은 config/robot.yaml 의 policy.type / policy.path
python src/send_task.py         # r / y 로 지시문 전송 → results/eval_results.csv
```

자세한 단계별 설명은 [RUNNING.md](RUNNING.md).

## 문서

| 문서 | 언제 읽나 |
|---|---|
| **[COLLECTING.md](COLLECTING.md)** | 실험 설계, 데모 녹화 순서·규칙, 평가 방법 |
| **[RUNNING.md](RUNNING.md)** | 실제로 돌릴 때 (3단계 = 학습 규칙과 이유) |
| [docker/README.md](docker/README.md) | GPU 서버에서 학습 컨테이너 띄우기 |
| [vendor/README.md](vendor/README.md) | 패치된 lerobot 0.6 설치 |
| [CLAUDE.md](CLAUDE.md) | 팀 작업 메모 — 하드웨어 실측값, 결정 기록, 알려진 버그 |
| [docs/archive/](docs/archive/) | 예전 Pi 2대 + Nav2 구성 시절 문서 (지금은 안 맞음, 참고용) |

## 레포 구조

```
config/
  robot.yaml           파이 주소·포트, 정책(type/path), 쓸 카메라 구성
  cameras.4cam.yaml    지금 쓰는 카메라 4대 (by-path 장치 경로) — 녹화·추론 공용
  cameras.3cam.yaml    3대 구성 (안 씀)
  cameras.pc.yaml      PC 웹캠 화면 확인용 (로봇과 무관)
  tasks.yaml           태스크·지시문 정의
scripts/
  host.sh              🍓 파이 호스트 (팔·바퀴·카메라)
  run_4cam_v2.sh       지금 녹화 진입점 (4cam + v2 데이터셋을 고정) → run_4cam.sh → record.sh
  teleop_keys.sh       바퀴 키 배치 (w/s/a/d 이동, z/x 회전, c/v 속도, g 잠금 해제)
  dataset_path.sh      데이터셋 로컬 폴더 고정 (이어찍기용)
  train.sh             학습 — 실험 규칙 고정
src/
  arm_node.py          💻 추론 노드 — 정책 서버에서 행동을 받아 로봇에 보냄
  safety_guard.py      양팔이 동시에 크게 튀면 정지 (results/safety_stops.csv)
  send_task.py         평가 때 지시문 보내기 (results/eval_results.csv)
  policy_client.py     arm_node 제어 클라이언트
  camera_config.py     카메라 설정 로더 / view_cameras.py · preflight_cameras.py 카메라 확인
  check_dataset.py     데이터셋 프레임 손실 확인
  main.py · agent.py · task_registry.py   말 → 태스크 라우팅 (LLM, 아직 안 씀)
  nav_node.py · navigation.py             Nav2 (안 씀, 남겨둠)
docker/                GPU 서버 학습 환경
vendor/                lerobot 0.6 패치
results/               평가 기록 (CSV)
tests_smoke.py         하드웨어 없이 도는 검증
```

## 꼭 지킬 것

- **카메라 장치 경로는 `config/cameras.*.yaml` 에만.** 녹화와 추론이 같은 파일을 읽습니다.
  카메라 이름이 학습 때와 다르면 정책이 행동을 못 내고 팔이 가만히 있습니다 (`tests_smoke.py` 가 막음).
- **파이와 PC 의 `CAMERA_SET` 이 같아야 합니다.** 어긋나면 빠진 카메라가 검은 화면으로 조용히 녹화됩니다.
  `run_4cam_v2.sh` 가 고정하고, `record` 는 검증을 통과해야 시작합니다.
- **카메라 구성이 다르면 데이터셋도 분리** (`-3cam` / `-4cam`). 섞으면 깨집니다. 지시문(red/yellow)은 한 데이터셋에 섞는 게 맞습니다.
- 녹화를 멈출 땐 `→` 로 에피소드를 끝내고 **리셋 시간에** `ESC`. 도중에 `ESC` 하면 토막이 저장됩니다
  (`./scripts/run_4cam.sh droplast` 로 삭제).
- API 키는 환경변수로만 (`GEMINI_API_KEY`). 소스·yaml 에 쓰지 마세요.
