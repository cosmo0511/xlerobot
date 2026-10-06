# 텔레옵 & 녹화 — host(라즈베리파이) / client(노트북)

리더암은 노트북에, 팔로워·바퀴·카메라는 Pi 에 있습니다. 그래서 둘로 나눠 돌립니다.

```
💻 노트북 (client)                        🦾 라즈베리파이 (host)
─────────────────────                    ──────────────────────
리더암 왼쪽  /dev/ttyACM0                 왼팔 버스    /dev/ttyACM0  ID 1~6
리더암 오른쪽 /dev/ttyACM1                오른팔+르키위 /dev/ttyACM1  ID 1~6 팔
키보드 (베이스 주행)                                                ID 7~9 바퀴
lerobot-record (데이터셋 저장)            카메라 3대   video0/2/4
       │                                        │
       └──── ZMQ 5555 (action) ────────────────▶│
       ◀──── ZMQ 5556 (관절+JPEG 3장) ─────────┘
```

**핵심: 노트북에서는 `lerobot-record` 가 Pi 를 그냥 로봇 하나로 봅니다.** 녹화 중 키
조작(←/→/ESC)이나 데이터셋 저장은 평소와 완전히 같습니다.

---

## 1. 왜 전용 코드가 필요했나

바로 `lerobot-record` 를 쓸 수 없는 이유가 세 가지 있습니다. `src/xlerobot_devices/`
가 그 세 개를 메운 것입니다.

| 막힌 곳 | 설명 | 해결 |
|---|---|---|
| lerobot 에 `xlerobot` 이 없다 | 업스트림 lerobot 에는 `lekiwi` 까지만 있습니다. 양팔+베이스는 XLeRobot 저장소에만 있습니다 | `xlerobot` / `xlerobot_client` 를 플러그인으로 등록 |
| 업스트림 XLeRobot 은 **머리 모터**를 전제한다 | `port1` 에 ID 7,8(머리)이 있다고 보고 읽습니다. 우리 왼팔엔 1~6 뿐이라 `sync_read` 가 터집니다 | `use_head` 로 분리, 기본 꺼짐 |
| `lerobot-record` 는 텔레옵 장치를 **하나만** 받는다 | 리더암+키보드를 같이 받는 경로가 있지만 `robot.name == "lekiwi_client"` 로 하드코딩돼 있습니다 | 리더암 2개+키보드를 **한 장치**로 포장 (`bi_leader_base`) |

lerobot 은 포크하지 않았습니다. `--robot.discover_packages_path=xlerobot_devices` 로
우리 패키지를 끼워 넣습니다.

### 이름 한 글자 함정

`bi_so_leader` 가 내보내는 키는 `left_shoulder_pan.pos` 인데, 로봇이 기다리는 건
`left_arm_shoulder_pan.pos` 입니다. 이 `arm_` 하나 때문에 **팔이 아무 경고 없이 안
움직입니다.** `bi_leader_base` 가 중간에서 이름을 바꿔줍니다.

수집 전에 한 번 확인하세요:

```bash
python tests_devices.py
```

host / client / 텔레옵 세 쪽의 키가 글자까지 같은지 봅니다. 로봇을 꽂지 않아도 됩니다.

---

## 2. 설치

**양쪽 다** (Pi, 노트북):

```bash
pip install -e "lerobot[feetech]"   # 노트북의 리더암도 feetech 입니다
pip install pyzmq opencv-python
```

노트북에만 추가로 — 학습까지 할 거면:

```bash
pip install -e "lerobot[smolvla,feetech]"
```

**설정은 `scripts/xle_env.sh` 한 군데서만** 고칩니다. 나머지 스크립트는 이걸
source 합니다.

```bash
# scripts/xle_env.sh 에서 확인할 것
PI_IP="192.168.0.101"            # ← 라즈베리파이 IP
PI_PORT1="/dev/ttyACM0"          # ← Pi: 왼팔
PI_PORT2="/dev/ttyACM1"          # ← Pi: 오른팔+르키위
LEADER_LEFT_PORT="/dev/ttyACM0"  # ← 노트북: 왼쪽 리더암
LEADER_RIGHT_PORT="/dev/ttyACM1" # ← 노트북: 오른쪽 리더암
```

포트 번호는 꽂는 순서에 따라 바뀝니다. 헷갈리면 하나씩 뽑아보면서:

```bash
lerobot-find-port
```

---

## 3. 캘리브레이션 — 처음 한 번

**팔로워와 리더가 따로입니다.** 둘 다 해야 합니다.

### 🦾 Pi 에서 (팔로워 2개)

```bash
./scripts/host.sh --calibrate
```

순서: 왼팔 중간자세 → 왼팔 전범위 → 오른팔 중간자세 → 오른팔 전범위.
**바퀴는 손대지 마세요.** 무한 회전 관절이라 0~4095 가 자동으로 들어갑니다.

저장 위치: `~/.cache/huggingface/lerobot/calibration/robots/xlerobot/home_xle.json`

### 💻 노트북에서 (리더 2개)

```bash
./scripts/teleop.sh --calibrate
```

저장 위치: `.../calibration/teleoperators/so_leader/home_xle_leader_{left,right}.json`

> ⚠️ 리더와 팔로워의 `use_degrees` 가 같아야 합니다. 양쪽 다 `True` 로 맞춰뒀습니다.
> 한쪽만 바꾸면 팔이 엉뚱한 각도로 갑니다.

---

## 4. 띄우기 — 터미널 2개

### 터미널 ① 🦾 Pi (SSH)

```bash
cd ~/xlerobot
./scripts/host.sh
```

`Waiting for commands...` 가 뜨면 준비된 겁니다. **이게 떠 있는 동안에만** 노트북
쪽이 동작합니다.

기본 10시간 뒤 스스로 종료합니다 (`HOST_UPTIME_S`). 하루 종일 찍을 거면 늘리세요.

### 터미널 ② 💻 노트북

```bash
cd ~/xlerobot
./scripts/teleop.sh
```

리더암을 움직이면 Pi 의 팔이 따라옵니다. 화면에 카메라 3장이 뜹니다.

| 키 | 동작 |
|---|---|
| `i` `k` | 베이스 전진 / 후진 |
| `j` `l` | 베이스 좌 / 우 (옴니휠이라 횡이동됩니다) |
| `u` `o` | 제자리 회전 |
| `n` `m` | 속도 단계 올리기 / 내리기 (3단) |

> 처음엔 `MAX_REL_TARGET=5` 를 켜고 시작하세요. 리더암을 확 휘두르면 팔로워가
> 그대로 따라가서 책상을 칩니다.
>
> ```bash
> MAX_REL_TARGET=5 ./scripts/teleop.sh
> ```

---

## 5. 녹화

`host.sh` 를 띄워둔 채, 노트북에서:

```bash
export HF_USER=여러분_허깅페이스_아이디

./scripts/record.sh pick_red     40 --first   # 맨 처음 세션
./scripts/record.sh pick_blue    40
./scripts/record.sh pick_yellow  40
# 로봇을 2번 책상으로 옮기고
./scripts/record.sh place_red    40
./scripts/record.sh place_blue   40
./scripts/record.sh place_yellow 40
```

`--first` 는 맨 처음 한 번만. 나머지는 같은 데이터셋에 이어붙습니다.

**데모를 어떻게 찍어야 하는지는 [COLLECTING.md](COLLECTING.md) 를 그대로 따르세요.**
색을 배우게 하는 두 가지 규칙(세 색 다 놓기, 자리 섞기)이 성패를 가릅니다.

### 녹화 중에 주행 키를 누르지 마세요

action 에 `x.vel` `y.vel` `theta.vel` 이 **같이 들어갑니다.** 조작 데모를 찍는
동안 주행 키를 안 누르면 이 3개가 정확히 0 으로 기록되고, 정책은 "조작 중엔
베이스를 안 움직인다"를 깔끔하게 배웁니다. 중간에 조금씩 밀면 그 노이즈를 그대로
학습합니다.

### ⚠️ 예전 데이터와는 섞을 수 없습니다

| | action/state 키 |
|---|---|
| 전 (`bi_so_follower`) | `left_shoulder_pan.pos` … (12개) |
| 후 (`xlerobot_client`) | `left_arm_shoulder_pan.pos` … + `x.vel` `y.vel` `theta.vel` (15개) |

`--first` 로 **새 `repo_id`** 를 쓰세요. 이어붙이면 컬럼이 안 맞아서 터집니다.

---

## 6. 안 될 때

| 증상 | 원인 | 조치 |
|---|---|---|
| `Timeout waiting for host` | host 가 안 떴거나 IP/방화벽 | Pi 에서 `host.sh` 확인, `PI_IP` 확인, `nc -zv $PI_IP 5556` |
| host 가 혼자 종료됨 | `HOST_UPTIME_S` 경과 | `HOST_UPTIME_S=86400 ./scripts/host.sh` |
| `캘리브레이션 파일이 없습니다` | 팔로워 캘리브 안 함 | Pi 에서 `./scripts/host.sh --calibrate` |
| **팔이 아예 안 움직인다** | action 키 불일치 | `python tests_devices.py` |
| 한쪽 팔만 움직인다 | 리더암 포트가 바뀜 | `lerobot-find-port`, `LEADER_*_PORT` 수정 |
| `sync_read` 가 자주 실패 | 한 버스에 모터 9개 | `xle_env.sh` 의 `FPS` 를 20 으로 |
| 팔이 떨린다 | Pi 의 CPU 부족 | `FPS=20`, Pi 에서 `top` 확인 |
| 영상이 끊긴다 | WiFi 대역폭 | `CAM_W=424 CAM_H=240`, 또는 `--host.jpeg_quality=70` |
| 녹화된 action 이 전부 0 | 리더암이 연결 안 됐는데 진행됨 | `teleop.sh` 로 먼저 팔이 움직이는지 확인 |
| 모터 ID 가 섞였다 | 조립 때 ID 를 안 구웠음 | TELEOP.md 하단 "모터 ID" 참고 |

### 포트가 매번 바뀌는 게 귀찮으면

udev 규칙으로 고정하세요. Pi 에서:

```bash
# 시리얼 번호 확인
udevadm info -a -n /dev/ttyACM0 | grep serial

# /etc/udev/rules.d/99-xle.rules
SUBSYSTEM=="tty", ATTRS{serial}=="<왼팔_시리얼>",  SYMLINK+="xle_left"
SUBSYSTEM=="tty", ATTRS{serial}=="<오른팔_시리얼>", SYMLINK+="xle_right"
```

그러면 `PI_PORT1=/dev/xle_left` 로 고정할 수 있습니다.

### 모터 ID

처음 조립이라 ID 가 안 구워졌으면 Pi 에서:

```bash
PYTHONPATH=src python -c "
from xlerobot_devices import XLerobot, XLerobotConfig
r = XLerobot(XLerobotConfig(id='home_xle', cameras={}))
r.setup_motors()
"
```

모터를 하나씩만 연결하라고 안내합니다. 왼팔 1~6, 오른팔 1~6, 바퀴 7~9 순서입니다.

---

## 7. ⚠️ 알고 있어야 할 두 가지 충돌

하드웨어를 이렇게 묶으면서 기존 설계와 어긋나는 데가 두 곳 생겼습니다. 텔레옵·녹화
자체에는 지장이 없지만, 그 다음 단계로 가기 전에 정리해야 합니다.

### (1) Nav2 가 바퀴를 못 가진다

바퀴(ID 7,8,9)가 **오른팔과 같은 시리얼 포트**에 있습니다. 시리얼 포트는 한
프로세스만 열 수 있어서, `host.sh` 가 떠 있는 동안 Nav2 의 바퀴 드라이버를 같이
띄울 수 없습니다. `ARCHITECTURE.md` 의 "Pi-B 가 바퀴를 소유한다"는 전제가 이
배선에서는 성립하지 않습니다.

선택지는 둘입니다.

- **host 를 유일한 소유자로 두고, Nav2 는 ZMQ 로 속도만 넘긴다.**
  Nav2 의 `cmd_vel` → `{"x.vel":…, "y.vel":…, "theta.vel":…}` 로 바꿔서 5555 로
  보내면 됩니다. `host` 는 이미 부분 명령을 받습니다 (팔 키가 없으면 팔은 그대로).
  코드를 가장 덜 고치는 길입니다.
- **바퀴를 별도 컨트롤러 보드로 뺀다.** 배선을 바꿔야 하지만 원래 설계대로 갑니다.

### (2) `arm_node.py` 와 데이터셋 키가 어긋난다

`src/arm_node.py` 는 `bi_so_follower` 로 팔을 엽니다. 그 키는 `left_shoulder_pan.pos`
이고, 이번에 녹화할 데이터는 `left_arm_shoulder_pan.pos` 입니다. **학습한 정책의
출력 키가 `arm_node.py` 가 기대하는 키와 달라서 추론 단계에서 팔이 안 움직입니다.**

수집을 시작하기 전에 둘 중 하나를 정하세요.

- `arm_node.py` 도 `xlerobot` 로 옮긴다 (host 가 이미 그 로봇을 열고 있으니, 정책
  추론도 host 에 붙이는 쪽이 자연스럽습니다)
- 또는 녹화를 기존 `bi_so_follower` 로 되돌린다 (그러면 리더암을 Pi 에 꽂아야 하고,
  베이스는 텔레옵에서 빠집니다)

`host.sh` 와 `arm_node.py` 는 **동시에 띄울 수 없습니다** (같은 포트를 씁니다).
지금은 수집 단계니까 `host.sh` 만 쓰면 되고, 추론 단계로 갈 때 위를 정리하면 됩니다.

---

## 요약 체크리스트

```
[ ] 양쪽에 pip install -e "lerobot[feetech]" + pyzmq + opencv-python
[ ] scripts/xle_env.sh 의 PI_IP / 포트 4개 / 카메라 3개 확인
[ ] python tests_devices.py          ← 키 일치 확인 (하드웨어 없이)
[ ] Pi:    ./scripts/host.sh --calibrate     (팔로워 2개)
[ ] 노트북: ./scripts/teleop.sh --calibrate   (리더 2개)
[ ] Pi:    ./scripts/host.sh                 (띄워둔 채로)
[ ] 노트북: MAX_REL_TARGET=5 ./scripts/teleop.sh   ← 먼저 손으로 움직여보기
[ ] 카메라 3장 다 나오나, 팔 양쪽 다 따라오나, 주행 키 되나
[ ] 노트북: ./scripts/record.sh pick_red 40 --first
[ ] COLLECTING.md 의 규칙 1·2 지키기 (세 색 다 놓기 / 자리 섞기)
```
