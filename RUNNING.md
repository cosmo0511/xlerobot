# 실행 가이드

기기 표기: 🦾 Pi-A(양팔) · 🛞 Pi-B(르키위) · 💻 PC(GPU)

0단계부터 순서대로. **처음이면 0단계만 해도 전체 흐름이 도는 걸 볼 수 있습니다.**

---

## 0단계. 하드웨어 없이 흐름부터 확인 (5분) 💻

```bash
pip install pyyaml pyzmq
python src/main.py --dry-run
python tests_smoke.py          # 로직 검증 9종
```

```
명령 > 분리수거 해줘
[dry-run] 팔 접는 척
[dry-run] 부엌(kitchen) 로 이동하는 척 ... 1.0s
[dry-run] 정책 실행하는 척: 'Sort the recycling'
결과: {'status': 'done', 'location_id': 'kitchen', ...}
```

명령 해석까지 진짜로 하려면:

```bash
pip install google-genai
export GEMINI_API_KEY="새로_발급받은_키"    # ⚠️ 소스에 절대 쓰지 마세요
```

> 키가 없거나 네트워크가 안 되면 `aliases` 기반 키워드 매칭으로 자동 폴백합니다.
> 심사장 WiFi 가 안 될 때를 대비한 안전장치입니다.

---

## 1단계. 팔 준비 🦾 Pi-A

### 포트·카메라 확인

```bash
lerobot-find-port        # 팔로워 2개 포트
lerobot-find-cameras     # 카메라 인덱스 (구성에 적힌 개수만큼)
```

### 캘리브레이션 (처음 한 번)

```bash
lerobot-calibrate --robot.type=so101_follower --robot.port=/dev/ttyACM0 --robot.id=home_bi_left
lerobot-calibrate --robot.type=so101_follower --robot.port=/dev/ttyACM1 --robot.id=home_bi_right
```

### `config/robot.yaml` 의 `arms` 블록 채우기

```yaml
arms:
  control_address: "tcp://192.168.0.101:5580"   # Pi-A 의 IP
  left_port:  "/dev/ttyACM0"
  right_port: "/dev/ttyACM1"
  camera_set: "3cam"        # ← 카메라는 여기 안 적습니다
```

### 카메라는 `config/cameras.<이름>.yaml` 에 채우기

```yaml
# config/cameras.3cam.yaml
top_cameras:
  top:   {index_or_path: "/dev/video0", width: 640, height: 480, fps: 30}
left_cameras:
  wrist: {index_or_path: "/dev/video2", width: 640, height: 480, fps: 30}  # → left_wrist
right_cameras:
  wrist: {index_or_path: "/dev/video4", width: 640, height: 480, fps: 30}  # → right_wrist
```

채운 뒤 바로 확인하세요:

```bash
python src/camera_config.py              # 쓸 수 있는 구성 목록
python src/camera_config.py 3cam --check # 장치가 실제로 있는지
```

> ⚠️ 최종 관측 키는 `top` / `left_wrist` / `right_wrist` 입니다. 팔에 묶인 카메라는
> 접두사가 자동으로 붙습니다. **이 이름이 2단계 데모 수집 때와 같아야** 합니다.
> 이 파일을 녹화(`record.sh`)와 추론(`arm_node.py`)이 **같이 읽으므로** 어긋날
> 일은 없지만, 데이터를 찍기 시작한 뒤에는 파일 자체를 고치지 마세요.
> 다른 구성을 시험하려면 `cameras.<새이름>.yaml` 을 새로 만드세요.

### 파킹 자세 값 찾기

```bash
lerobot-find-joint-limits --robot.type=so101_follower --robot.port=/dev/ttyACM0
```

팔을 손으로 접어보고 그때 값을 `robot.yaml` 의 `travel_pose` 에 적으세요.
문틀을 통과할 수 있고 트롤리에 안 걸리는 자세여야 합니다.

---

## 2단계. 모방학습 데모 수집 🦾 Pi-A

> 자세한 방법은 **[COLLECTING.md](COLLECTING.md)** 참고. 태스크 하나부터 시작하는 순서,
> 녹화 중 키 조작, 좋은 시연 기준이 거기 있습니다.

태스크 **하나당** 한 번씩, 총 5번. `--dataset.single_task` 값은
`config/tasks.yaml` 의 `prompt` 와 **글자까지 동일**해야 합니다.

카메라 인자는 손으로 적지 말고 설정에서 생성하세요. 그래야 추론 때와 어긋나지 않습니다.

```bash
mapfile -t CAM_ARGS < <(python3 src/camera_config.py 3cam --record-args)
```

```bash
lerobot-record \
  --robot.type=bi_so_follower \
  --robot.left_arm_config.port=/dev/ttyACM0 \
  --robot.right_arm_config.port=/dev/ttyACM1 \
  --robot.id=home_bi \
  "${CAM_ARGS[@]}" \
  --teleop.type=bi_so_leader \
  --teleop.left_arm_config.port=/dev/ttyACM2 \
  --teleop.right_arm_config.port=/dev/ttyACM3 \
  --teleop.id=home_bi_leader \
  --dataset.repo_id=$HF_USER/xlerobot-home \
  --dataset.single_task="Water the plant" \
  --dataset.num_episodes=50 \
  --display_data=true
```

같은 `--dataset.repo_id` 에 `--resume=true` 를 붙여 나머지 4개 태스크를 이어서 녹화하면
**태스크 5개가 한 데이터셋에 들어갑니다.** SmolVLA 는 지시문으로 구분합니다.

수집할 때 지켜야 할 것:

- **로봇이 서 있는 위치와 각도를 태스크마다 고정하세요.** 나중에 Nav2 가 그 자리로
  데려다 놓습니다. 10cm 만 틀어져도 정책이 실패합니다. 바닥에 테이프로 표시하세요.
- 태스크당 최소 **40~50 에피소드**. 물체 위치를 5가지 정도로 바꿔가며 각 10회씩.
  SmolVLA 문서에 25개로는 부족했다고 명시돼 있습니다.
- 실패한 시연은 지우세요 (`lerobot-edit-dataset`). 실패 데이터는 정책을 망칩니다.
- **트롤리를 결합한 상태로** 수집하세요. 실제 운용 형상과 다르면 무게중심·카메라
  높이가 달라져 그대로 실패합니다.

> 베이스가 안 움직이므로 액션 차원은 팔 12관절뿐입니다. 주행 명령이 정책 학습에
> 섞이지 않아서, 단일 Pi 구성보다 학습이 오히려 깔끔합니다.

---

## 3단계. SmolVLA 학습 💻 PC

```bash
lerobot-train \
  --policy.path=lerobot/smolvla_base \
  --dataset.repo_id=$HF_USER/xlerobot-home \
  --batch_size=64 \
  --steps=20000 \
  --output_dir=outputs/train/smolvla_home \
  --job_name=smolvla_home \
  --policy.device=cuda \
  --wandb.enable=true
```

A100 기준 20k 스텝에 약 4시간. 메모리가 부족하면 `--batch_size` 를 32, 16으로 낮추세요.
GPU 가 없으면 [Colab 노트북](https://colab.research.google.com/github/huggingface/notebooks/blob/main/lerobot/training-smolvla.ipynb)으로 돌릴 수 있습니다.

끝나면 `config/robot.yaml` 의 `policy.path` 를 결과 경로로 맞추세요.

### 정책만 단독 확인

에이전트·자율주행 없이 팔만 돌려보고 싶을 때 (🦾 Pi-A 가 GPU 가 없으므로 PC 에 팔을
잠깐 USB 로 물려서 확인하거나, 4단계의 서버/노드 구성으로 확인):

```bash
lerobot-rollout \
  --strategy.type=base \
  --robot.type=bi_so_follower \
  --robot.left_arm_config.port=/dev/ttyACM0 \
  --robot.right_arm_config.port=/dev/ttyACM1 \
  --robot.cameras='{ ... 2단계와 동일 ... }' \
  --task="Water the plant" \
  --policy.path=outputs/train/smolvla_home/checkpoints/last/pretrained_model
```

**정책이 여기서 안 되면 통합해도 안 됩니다.** 반드시 이 단계에서 먼저 되게 만드세요.

---

## 4단계. 추론 서버 + 팔 노드 띄우기 💻🦾

### 💻 PC — SmolVLA 추론 서버

```bash
lerobot-policy-server --host=0.0.0.0 --port=8080
```

정책은 팔 노드가 처음 붙을 때 한 번 로드되고, 그 뒤로는 계속 메모리에 떠 있습니다.
태스크를 바꿔도 재로딩하지 않습니다.

### 🦾 Pi-A — 팔 노드

```bash
python src/arm_node.py
```

```
로봇 연결 및 정책 서버 접속 중: 192.168.0.200:8080
팔 준비 완료
제어 소켓 대기 중: tcp://0.0.0.0:5580
```

이게 팔의 유일한 주인입니다. **이 프로세스가 떠 있는 동안 다른 프로그램이 같은 포트를
열면 안 됩니다.** 시연 중에는 계속 켜둡니다.

---

## 5단계. 자율주행 🛞 Pi-B

이 단계는 분량이 많아서 **[NAV2_SETUP.md](NAV2_SETUP.md)** 로 따로 뺐습니다.
0~7단계 체크리스트와 단계별 성공 판정이 거기 있습니다.

요약하면:

```
[ ] 0.  /cmd_vel 로 바퀴가 돈다              ← 여기가 갈림길
[ ] 1.  맵(.yaml + .pgm)이 Pi-B 에 있다
[ ] 2.  nav2_bringup 이 설치돼 있다
[ ] 3.  스캔 토픽·풋프린트·max_vel_y 를 로봇에 맞춘다
[ ] 4.  tf2_echo map base_link 가 좌표를 뱉는다
[ ] 5.  RViz 의 2D Goal Pose 로 로봇이 스스로 간다   ← 진짜 관문
[ ] 6.  tasks.yaml 의 pose 4곳을 실측값으로 채운다
[ ] 7.  nav_node.py 가 뜬다
```

시작 전에 항상:

```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
```

### 자율주행 노드 띄우기

Nav2 가 돌고 있으면 그 앞에 이 노드를 하나 더 띄웁니다.

```bash
python src/nav_node.py
```

```
Nav2 액션 서버 대기 중: navigate_to_pose
Nav2 연결됨
제어 소켓 대기 중: tcp://0.0.0.0:5581
```

> Nav2 액션 클라이언트가 **Pi-B 안에** 있으므로 PC 에는 ROS2 를 설치할 필요가 없습니다.
> PC 는 팔 노드와 똑같이 ZMQ 로만 말합니다.

---

## 6단계. 전체 실행 💻 PC

세 프로세스가 다 떠 있어야 합니다.

| 기기 | 프로세스 |
|---|---|
| 💻 PC | `lerobot-policy-server --host=0.0.0.0 --port=8080` |
| 🦾 Pi-A | `python src/arm_node.py` |
| 🛞 Pi-B | `nav2_bringup` + `python src/nav_node.py` |

```bash
# 💻 PC — ROS2 불필요
export GEMINI_API_KEY="..."
python src/main.py
```

```
명령 > 화분에 물 좀 줘
명령 수신: {'cmd': 'park'}
안방 도착
명령 수신: {'cmd': 'run', 'task': 'Water the plant'}
결과: {'status': 'done', 'task_prompt': 'Water the plant', ...}
```

시연 스크립트로는 한 줄씩:

```bash
python src/main.py --once "장난감 정리해줘"
```

---

## 문제 해결

| 증상 | 원인 | 조치 |
|---|---|---|
| `팔 노드가 응답하지 않습니다` | Pi-A 의 `arm_node.py` 가 안 떴거나 IP 틀림 | `control_address` 확인, Pi-A 방화벽 5580 |
| `정책 서버에 붙지 못했습니다` | PC 의 policy-server 미기동 | `--host=0.0.0.0` 로 떴는지 확인 (localhost 면 외부에서 못 붙음) |
| `자율주행 노드가 응답하지 않습니다` | Pi-B 의 `nav_node.py` 미기동 또는 IP 틀림 | `navigation.control_address` 확인, Pi-B 방화벽 5581 |
| `Nav2 액션 서버가 응답하지 않습니다` | Pi-B 에서 `nav2_bringup` 미기동 | Pi-B 에서 `ros2 action list \| grep navigate` |
| `좌표가 아직 (0,0,0) 입니다` | 5단계 좌표 찍기를 건너뜀 | `tasks.yaml` 의 `pose` 를 채우세요 |
| `travel_pose 의 관절 이름이 로봇과 다릅니다` | 관절 키 오타 | 로그에 나온 이름을 그대로 쓰세요 (`left_shoulder_pan.pos` 형식) |
| `정책에서 행동을 하나도 못 받았습니다` | 카메라 이름이 학습 때와 다름 | policy-server 로그 확인, `top`/`left_wrist`/`right_wrist` 대조 |
| 팔이 엉뚱하게 움직임 | 지시문이 학습 라벨과 다름 | `tasks.yaml` 의 `prompt` 와 `--dataset.single_task` 를 글자 단위로 비교 |
| 정책이 아예 못 함 | 도착 위치가 데모 수집 자리와 다름 | 바닥 테이프 위치 확인, `pose` 재측정 |
| 도착하자마자 흔들림 | 트롤리 관성 | `navigation.settle_s` 를 3.0 정도로 늘리세요 |
| 이동 중 팔이 부딪힘 | `travel_pose` 가 너무 벌어짐 | 더 접힌 자세로 다시 측정 |

---

## 병렬 작업 순서

세 갈래가 서로 안 막힙니다.

1. **데이터 수집** (가장 오래 걸림 — 지금 당장 시작) — 2단계.
   태스크 5개 × 50 에피소드는 사람 손으로 며칠 필요합니다.
2. **Nav2 붙이기 + 좌표 찍기** — 5단계. 트롤리 결합 상태의 맵이 핵심.
3. **통합** — 0단계 `--dry-run` 으로 이미 검증됨. 1·2가 끝나는 대로 붙이면 됩니다.

VR 텔레오퍼레이션(Meta Quest 3S)은 **2단계의 리더암을 대체하는 입력 장치**로 붙이면
됩니다. `lerobot-record` 의 `--teleop.type` 만 바뀌고 나머지 파이프라인은 그대로입니다.
업스트림 참고: `software/examples/8_vr_teleop_with_dataset_recording.py`
