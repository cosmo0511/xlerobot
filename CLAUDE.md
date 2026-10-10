# XLeRobot — 작업 메모 (팀 공용)

**지금 실제 하드웨어가 어떻게 생겼는지**를 적어두는 곳입니다. 코드를 읽기 전에 보세요.

## 하드웨어 구성 (2026-10 현재)

```
💻 PC (GPU)                🍓 라즈베리파이              🤖 로봇
   랜선으로 네트워크   ←무선(WiFi)→   중간에서 통신     ←USB→   팔 2개 + 바퀴 3개
   학습 / 추론 서버
```

- **PC** — 원래 랜선 전제였지만 **2026-10-10 기준 Wi-Fi 입니다** (`wlp4s0`, iptime 5GHz ch149, -41 dBm,
  파이까지 ping 평균 8ms·최대 14ms). 그러면 파이→공유기→PC 가 **둘 다 무선**이라 같은 채널을
  두 번 탑니다. 랜 포트(`enp3s0`)는 있으니 녹화 때는 꽂는 게 낫습니다. SmolVLA 학습·추론.
- **라즈베리파이** — **로봇과 무선으로 통신**합니다.
- **로봇** — SO-101 양팔 + 아래 옴니휠 모터 3개.
  **바퀴 모터 3개는 로봇 오른쪽 팔에 연결돼 있습니다.**

무선 구간이 있어서 **이미지를 매 프레임 보내는 설계는 못 씁니다.** SmolVLA 의
action chunk 방식(한 번에 50스텝 받아오기)이 여기서 필수입니다 —
이유는 `src/arm_node.py` 상단 주석에 있습니다.

## 지금까지 정해진 것

| 항목 | 현재 상태 |
|---|---|
| **주행** | **자율주행(Nav2)은 안 씁니다** (2026-10 결정). 바퀴는 텔레옵으로 녹화하고 정책이 직접 냅니다. `robot.yaml` 의 `navigation.enabled: false` → 에이전트의 이동 단계는 건너뜀. Nav2 코드(`nav_node.py`, `NAV2_SETUP.md`)는 지우지 않고 남겨둠 |
| **태스크** | **1m 주행 → 지시한 색(빨강/파랑) 주사위를 그쪽 팔로 집어 바구니에.** 1단계, 지시문 2종. SmolVLA vs ACT(언어 없는 대조군)로 언어 효과 검증. 원본: 실험설계 마일스톤 PPT → 절차는 **`COLLECTING.md`**. (예전 2책상·3색 태스크는 폐기) |
| **데이터** | 아직 **한 에피소드도 안 찍었습니다** (10/10 기준). 목표 96개 = 8개 × 12블록 (순서표: `COLLECTING.md` 3절) |
| **하드웨어** | 다 있습니다 (베이스캠 포함) |
| **카메라** | 3cam / 4cam 둘 다 지원. `CAMERA_SET` 으로 전환 (추론도 이제 `CAMERA_SET` 이 `robot.yaml` 을 덮어씀). **4cam USB 실측 통과** (4대 동시 MJPG 30fps, 26 Mbps). 무선 구간(`run_4cam.sh check`)은 아직 |
| **일정** | PPT 기준 10/10 데모 마무리·학습 → 10/11 예비 평가 → **10/12 본 평가 72회** → 10/23 제출. **데모 0개라 이미 늦음** |

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

### 무엇을 고쳤나 — 이제 레포에 있습니다: `vendor/lerobot-0.6.patch`

v0.6.0 기준 35 files, +2471 / -21 (기존 파일 15개 수정 + **새 파일 20개**).
예전에 적어둔 "+249" 는 `git diff --stat` 이 새 파일을 안 세서 나온 숫자였습니다.
설치·갱신 방법과 파일 목록은 **`vendor/README.md`** 에 있습니다.
깨끗한 v0.6.0 에 적용하면 원본 PC 의 `src/` 와 똑같아지는 것까지 확인했습니다.

### 코드에서 확인한 것 (예전 "아직 모르는 것")

**등록된 타입 이름** (`config_bi_so_follower.py`, `config_bi_so_leader.py`)

| 타입 | 종류 | 실행 위치 |
|---|---|---|
| `bi_so_base_follower` | 로봇 — 양팔 + 바퀴를 USB 로 직접 엶 | 파이 (호스트가 내부에서 사용) |
| `bi_so_base_client` | 로봇 — ZMQ 로 파이에 붙음, `remote_ip` 필요 | **PC (녹화)** |
| `bi_so_base_leader` | 텔레옵 — 리더암 2개 + 키보드 | **PC (녹화)** |
| `bi_so_client` | 로봇 — 바퀴 없는 양팔 클라이언트 | (안 씀) |

호스트는 등록 타입이 아니라 모듈입니다:
`python -m lerobot.robots.bi_so_follower.bi_so_base_host` → `scripts/host.sh`

**바퀴** (`bi_so_base_follower.py`)
- 모터: `base_left_wheel`(7) / `base_back_wheel`(8) / `base_right_wheel`(9), `sts3215`,
  **오른팔 버스에 추가**. 속도 모드. LeKiwi 와 같은 3옴니휠 기구학(240/0/120°).
- 액션·관측 키: `x.vel` (m/s, 앞 +), `y.vel` (m/s, 왼쪽 +), `theta.vel` (deg/s, 반시계 +)
- 전체 액션 **15차원**: `left_{shoulder_pan,shoulder_lift,elbow_flex,wrist_flex,wrist_roll,gripper}.pos`
  + `right_...pos` (6) + `x.vel, y.vel, theta.vel`
  (상류 xlerobot 의 `left_arm_` 접두사가 **아님** — `left_` / `right_`)

**리더암 + 키보드 합치기** — `lerobot_record.py` 는 import 만 추가됐고, 상류의
멀티 텔레옵 경로(`isinstance(teleop, list)`, lekiwi 게이트)는 **아예 안 탑니다.**
`bi_so_base_leader` 가 `BiSOLeader` + `KeyboardTeleop` 을 감싸서 **텔레옵 하나**로
15차원 액션을 냅니다. 그래서 예전에 적어둔 "멀티 텔레옵 제약 3개" 는 해당 없습니다.
- 바퀴는 **잠긴 상태로 시작**합니다. `g` 를 눌러야 움직입니다 (키보드 리스너가
  전역이라 다른 창에서 친 wasd 로 로봇이 움직이는 걸 막으려고).
- 실제로 쓰던 키: w/s/a/d 이동, **z/x 회전, c/v 속도**, t 종료 (`record.sh` 에 고정).

### 녹화·추론 경로 (확정) — 둘 다 같은 호스트에 같은 클래스로 붙습니다

```
🍓 파이:  ./scripts/host.sh      bi_so_base_host — 팔·바퀴·카메라를 엶, ZMQ 5555/5556
💻 PC  :  ./scripts/record.sh    bi_so_base_client + bi_so_base_leader     (녹화)
💻 PC  :  lerobot-policy-server + python src/arm_node.py (bi_so_base_client) (추론)
```

- 녹화와 추론이 **같은 로봇 클래스**라서 관측·액션 키, 순서(15차원), 카메라 이름,
  이미지(파이에서 JPEG 압축된 것)까지 같습니다. `tests_smoke.py` 13번이 지킵니다.
- 추론 노드·정책 서버·에이전트가 전부 PC 에 있으므로 무선을 타는 건 녹화 때와
  똑같은 호스트↔클라이언트 트래픽뿐입니다. 무선이 끊기면 호스트 워치독(500ms)이 바퀴를 세웁니다.
- `arm_node.py` 는 에피소드가 끝나면 항상 바퀴를 0 으로 보냅니다 (정책 마지막 액션이 주행이어도).
- 파이의 팔 포트·캘리브레이션 id 는 `config/robot.yaml` 의 `host:` 블록 한 곳 (아직 비어 있음).

- `remote_ip` 기본값 `xlerobot2.local` (`PI_HOST=` 로 변경). 실제 쓰던 명령에서 가져옴.
- 리더: `/dev/so101_leader_{left,right}`, id `bi_so101_leader`
  (캘리브레이션 `bi_so101_leader_{left,right}.json` 이 PC 에 있음 — id 를 바꾸면 재캘리브레이션).
- 카메라: 둘 다 `config/cameras.<CAMERA_SET>.yaml` 을 읽습니다. 파이는 `per_arm`
  (장치를 엶, `--check` 도 파이에서), PC 클라이언트는 `flat` (같은 최종 이름으로 프레임만 받음).
  **두 쪽 `CAMERA_SET` 이 같아야 합니다.**

## 아직 안 정해진 것 / 확인 필요

- **4cam USB 쪽은 됩니다 (2026-10-10 파이에서 실측).** `run_4cam.sh selftest` 결과:

  | 카메라 | 포맷 | 해상도 | fps | 추정 Mbps |
  |---|---|---|---|---|
  | top | MJPG | 640x480 | 30.6 | 6.0 |
  | base | MJPG | 640x480 | 30.6 | 4.1 |
  | left_wrist | MJPG | 640x480 | 30.2 | 7.0 |
  | right_wrist | MJPG | 640x480 | 30.0 | 8.4 |
  | **합계** | | | | **25.6** |

  4대 동시에 전부 MJPG 로 열리고 fps 가 안 떨어집니다. `bi_so_base_host.py` 주석의
  "카메라당 ~12 Mbps (4대면 48)" 은 **과대평가**였습니다 — 실제는 카메라당 6.4,
  합계 26 Mbps. 무선 여유가 생각보다 있습니다.
- **무선 쪽은 아직 미확인.** PC 에서 `./scripts/run_4cam.sh check` 를 돌려야 합니다
  (파이에서 `host.sh` 를 띄운 상태로). 녹화와 같은 경로라서, 여기서 통과하면 그
  그림이 그대로 데이터셋에 들어갑니다.
- ~~**파이 쪽 카메라 장치 경로**~~ — **확정됐습니다 (2026-10-10).**
  `config/cameras.4cam.yaml` 에 by-path 로 적혀 있고 머리말에 꽂은 자리 표가 있습니다.

  | USB 포트 | 그때의 노드 | 카메라 |
  |---|---|---|
  | 1 | /dev/video6 | top (YHTek — 유일하게 다른 모델) |
  | 1.4.3 | /dev/video0 | base |
  | 1.2 | /dev/video4 | left_wrist |
  | 1.3 | /dev/video2 | right_wrist |

  **by-id 는 쓰면 안 됩니다.** 4대 중 3대가 같은 모델·같은 시리얼
  (`Generic_USB_Camera_200901010001`) 이라 udev 가 by-id 링크를 **하나만** 만들고,
  그게 재부팅 때 셋 중 누구를 가리킬지 보장이 없습니다. by-path 는 "꽂은 USB 포트"
  기준이라 안전한 대신 **포트를 옮겨 꽂으면 경로가 바뀝니다.** 96개 다 찍을 때까지
  같은 자리여야 하니 꽂은 자리를 테이프로 표시하세요.
  (파이는 `bcm2835-isp` 를 /dev/video14/15/21/22 로 "캡처 장치"라고 신고합니다 —
  카메라가 아닙니다. `run_4cam.sh scan` 이 걸러서 보여줍니다.)
- **파이의 팔로워 포트와 id** — 이 PC 에서 확인 불가. `host.sh` 는 기본값 없이 env 로 받습니다.
- **파이에서 `bi_so_base_follower` 를 직접 쓰면 안 됩니다 (패치 버그).** 바퀴 모터가
  오른팔 버스에 추가되면서 `_motors_ft` 에 `right_base_*_wheel.pos` 3개가 끼어
  18차원이 됩니다. 호스트 경유(녹화·추론)는 15차원이라 영향 없음. 직접 쓸 일이 생기면
  `bi_so_base_follower.py` 의 `_motors_ft` 를 `self.right_arm_motors` 기준으로 고쳐야 합니다.
- **책상 1 → 책상 2 이동을 누가 하나** — 자율주행을 안 쓰므로 정책이 해야 합니다.
  그러려면 place 데모에 **이동까지 포함해서** 찍어야 합니다(또는 사람이 옮김). 아직 안 정함.

## 카메라 확인 (따로 실행하는 테스트)

```bash
python src/view_cameras.py            # PC 에서, 파이 host.sh 경유 (녹화와 같은 그림) → rerun 창
python src/view_cameras.py --local    # 카메라가 꽂힌 기기에서 장치 직접 열기
python src/view_cameras.py --save     # 창 없이 한 장씩 outputs/camera_check/ 에 저장
```

lerobot venv 의 OpenCV 는 headless 라 `cv2.imshow` 가 안 됩니다. 그래서 화면은 rerun.

## 환경: lerobot 0.6 (venv)

PC 는 `/home/user/lerobot-venv-0.6` + editable `/home/user/lerobot_0.6`.
임포트 경로와 CLI 플래그가 버전마다 바뀌므로 이 버전 기준으로 맞춥니다.

## 팀 작업 규칙

- **카메라 장치 경로를 `scripts/record.sh` / `scripts/host.sh` 에 다시 적지 마세요.**
  `config/cameras.*.yaml` 에만 있고, 녹화(`record.sh`)와 추론(`arm_node.py`)이
  같은 파일을 읽습니다. 어긋나면 팔이 아예 안 움직입니다. `tests_smoke.py` 가 막습니다.
- 카메라 구성이 다르면 데이터셋도 분리됩니다 (`xlerobot-dice-3cam` / `-4cam`).
  관측 키가 다른 데이터를 한 데이터셋에 섞으면 깨집니다.
- 코드를 고쳤으면 `python tests_smoke.py` 를 먼저 돌리세요 (하드웨어 없이 돕니다).
- 지금 뭐가 돌아가고 뭐가 아직인지는 `README.md` 의 상태 표를 보세요.
