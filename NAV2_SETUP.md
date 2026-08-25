# Nav2 붙이기 — 🛞 Pi-B

맵이 있다는 전제에서, 로봇이 스스로 목표까지 가게 만드는 순서.

각 단계에 **성공 판정**을 적어뒀습니다. 그게 나와야 다음으로 넘어가세요.
안 나온 채로 다음 단계를 하면 어디서 틀렸는지 못 찾습니다.

모든 명령은 이걸 먼저 하고 시작합니다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
```

---

## 0단계. `/cmd_vel` 확인 ← 여기가 갈림길

**나머지 전부가 이거 하나에 달려 있습니다.** Nav2 는 계산 결과를 `/cmd_vel` 토픽에
`geometry_msgs/Twist` 로 내보냅니다. 바퀴 구동부가 그걸 받아야 로봇이 움직입니다.

```bash
# 바퀴 구동 노드를 띄운 상태에서
~/ros2_ws/run_wasd.sh &
ros2 topic info /cmd_vel --verbose
```

찾을 것: **Subscription count 가 1 이상**인지. 즉 누군가 `/cmd_vel` 을 듣고 있는지.

직접 쏴서 확인하는 게 확실합니다. 로봇을 들어올리거나 바퀴를 띄운 상태로 하세요.

```bash
ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist \
  '{linear: {x: 0.1, y: 0.0}, angular: {z: 0.0}}'
```

> ✅ **성공 판정** — 바퀴가 잠깐 돈다.

| 결과 | 의미 | 다음 |
|---|---|---|
| 바퀴가 돈다 | 이미 Nav2 규격 | 1단계로 |
| 토픽은 있는데 구독자 0 | 구동부가 다른 토픽을 씀 | `ros2 topic list` 로 실제 토픽 확인 후 어댑터 |
| `/cmd_vel` 자체가 없음 | 자체 프로토콜 | 어댑터 노드 필요 (아래) |

### 어댑터가 필요한 경우

`/cmd_vel` 을 구독해서 기존 구동 함수를 호출하는 노드 하나만 만들면 됩니다.
`run_wasd.sh` 가 키보드 입력을 바퀴로 바꾸고 있으니, 그 입력부만 `/cmd_vel` 구독으로
바꾸면 끝입니다. 옴니휠이라 `linear.y` 도 살려야 합니다 — 이걸 버리면 나중에 로봇이
옆으로 못 가고 계속 제자리 회전만 합니다.

---

## 1단계. 맵을 Pi-B 로

PC 에 있으면 옮깁니다. `.pgm`(또는 `.png`)과 `.yaml` **둘 다**, 같은 폴더에.

```bash
# PC 에서
scp ~/maps/home.pgm ~/maps/home.yaml choi@xlerobot1:~/maps/
```

`.yaml` 안의 `image:` 줄이 이미지 파일명과 맞는지 확인하세요. 파일 이름을 바꿨다면
안쪽도 같이 고쳐야 합니다.

```bash
# Pi-B 에서
cat ~/maps/home.yaml
```

> ✅ **성공 판정** — `image:` 에 적힌 파일이 같은 폴더에 실제로 있다.

### 맵을 다시 만들어야 하는 경우

**트롤리를 안 단 상태로 만든 맵이면 다시 만드세요.** 회전 반경과 장애물 프로파일이
달라집니다. `/scan_trolley_masked` 필터가 생기기 전에 만든 맵도 마찬가지입니다.

```bash
sudo apt install ros-jazzy-slam-toolbox
ros2 launch slam_toolbox online_async_launch.py \
  use_sim_time:=false scan_topic:=/scan_trolley_masked

# 로봇을 조종해서 집 안을 한 바퀴 (run_wasd.sh)
# RViz 로 맵이 그려지는 걸 보면서 빈 곳이 없게 돕니다

ros2 run nav2_map_server map_saver_cli -f ~/maps/home
```

마지막 줄을 **꼭** 하세요. 이걸 빼면 노드를 끄는 순간 맵이 사라집니다.
이번에 맵을 못 찾은 게 아마 이 이유입니다.

---

## 2단계. Nav2 설치 확인

```bash
ros2 pkg list | grep -E "nav2|slam_toolbox"
```

없으면:

```bash
sudo apt update
sudo apt install ros-jazzy-navigation2 ros-jazzy-nav2-bringup ros-jazzy-slam-toolbox
```

> ✅ **성공 판정** — `nav2_bringup`, `nav2_bt_navigator`, `nav2_amcl` 이 목록에 보인다.

---

## 3단계. 파라미터 맞추기 ← 실제 작업량의 대부분

기본 파일을 복사해서 시작합니다. **직접 처음부터 쓰지 마세요.**

```bash
mkdir -p ~/ros2_ws/config
cp /opt/ros/jazzy/share/nav2_bringup/params/nav2_params.yaml ~/ros2_ws/config/nav2_home.yaml
```

이 파일에서 **바꿔야 하는 것만** 정리했습니다. 나머지는 건드리지 마세요.

### 3-1. 스캔 토픽 — 트롤리 마스킹된 걸 쓰게

파일 안에서 `scan` 관측 소스가 나오는 곳이 두 군데(`local_costmap`, `global_costmap`)
있습니다. 둘 다 토픽을 바꾸세요.

```yaml
      observation_sources: scan
      scan:
        topic: /scan_trolley_masked      # ← 기본값 /scan 에서 변경
        max_obstacle_height: 2.0
        clearing: True
        marking: True
        data_type: "LaserScan"
```

**이걸 안 바꾸면 로봇이 자기 트롤리를 벽으로 인식합니다.** 그러면 "사방이 막혔다"고
판단해서 아예 출발을 안 하거나, 제자리에서 계속 회전합니다.
팀에서 마스킹 필터를 만들어둔 게 여기서 값을 합니다.

### 3-2. 풋프린트 — 트롤리까지 포함한 실제 크기

기본값은 원형(`robot_radius`)인데, 트롤리를 달면 길쭉해지므로 다각형으로 바꿔야 합니다.

**줄자로 재세요.** `base_link` 원점(보통 바퀴 중심)에서 앞뒤좌우 끝까지의 거리입니다.

```yaml
      # robot_radius: 0.22        # ← 이 줄을 지우고
      footprint: "[[0.35, 0.25], [0.35, -0.25], [-0.55, -0.25], [-0.55, 0.25]]"
      #            앞-왼           앞-오른         뒤-오른          뒤-왼
      #            트롤리가 뒤로 55cm 튀어나온 경우의 예시입니다.
      #            실제 값으로 반드시 바꾸세요.
```

`local_costmap` 과 `global_costmap` 양쪽 다 바꿉니다.

> 여유를 조금 크게 잡으세요. 실제보다 5cm 정도 크게 잡으면 벽을 스치는 일이 줄어듭니다.
> 대신 너무 크면 좁은 문을 못 지나갑니다.

### 3-3. 속도 한계 — 옴니휠이라 `vy` 를 살려야

controller 섹션에서 속도 한계를 로봇에 맞춥니다.

```yaml
      max_vel_x: 0.25
      min_vel_x: -0.25
      max_vel_y: 0.25        # ← 0 이 아니어야 합니다. 옴니휠이라 옆으로 갑니다
      min_vel_y: -0.25
      max_vel_theta: 1.0
```

`max_vel_y: 0.0` 으로 두면 옴니휠의 장점을 통째로 버리는 겁니다.
컨트롤러가 DWB 면 `vy_samples` 도 1 이상이어야 합니다.

> 트롤리를 달면 무게가 늘어 가감속이 둔해집니다. 처음엔 속도를 낮게(0.15 정도) 잡고
> 잘 도는 걸 확인한 뒤 올리세요.

### 3-4. 초기 위치

```yaml
amcl:
  ros__parameters:
    set_initial_pose: true
    initial_pose: {x: 0.0, y: 0.0, z: 0.0, yaw: 0.0}
```

로봇을 항상 같은 자리(예: 충전 스테이션)에서 시작한다면, 그 좌표를 넣으면 매번
RViz 에서 초기 위치를 찍어줄 필요가 없어집니다.

---

## 4단계. 띄우고 위치추정 확인

센서·오도메트리 쪽을 먼저 다 띄운 다음 Nav2 를 올립니다.

```bash
# 터미널 1~3: 기존 스크립트들
~/ros2_ws/run_lidar_driver_tf.sh
~/ros2_ws/run_lidar_filter.sh
~/ros2_ws/run_wasd_ekf.sh

# 터미널 4: Nav2
ros2 launch nav2_bringup bringup_launch.py \
  map:=$HOME/maps/home.yaml \
  params_file:=$HOME/ros2_ws/config/nav2_home.yaml \
  use_sim_time:=false
```

확인:

```bash
ros2 action list | grep navigate_to_pose      # 액션이 떴는지
ros2 run tf2_ros tf2_echo map base_link       # 위치추정이 되는지
```

> ✅ **성공 판정** — `tf2_echo map base_link` 가 좌표를 계속 뱉는다.
> 로봇을 손으로 밀면 그 값이 따라 움직인다.

`map` → `base_link` 가 안 나오면 AMCL 이 위치를 못 잡은 겁니다.
PC 에서 RViz 를 띄워 `2D Pose Estimate` 로 현재 위치를 찍어주세요.

---

## 5단계. 수동으로 목표 주기 ← 진짜 관문

**여기가 "자율주행이 된다"의 판정 지점입니다.** 여기까지 되면 나머지는 조립입니다.

PC 에서 RViz 를 띄우고 (같은 `ROS_DOMAIN_ID`), 툴바의 **`2D Goal Pose`** 로
로봇에서 2~3m 떨어진 빈 바닥을 찍습니다.

> ✅ **성공 판정** — 로봇이 스스로 그 지점까지 가서 멈춘다.

### 자주 나오는 증상

| 증상 | 원인 | 조치 |
|---|---|---|
| 아예 안 움직임 | `/cmd_vel` 구독자 없음 | 0단계로 돌아가세요 |
| 제자리 회전만 | 풋프린트가 너무 큼, 또는 트롤리를 장애물로 인식 | 3-1, 3-2 재확인 |
| 출발했다가 바로 포기 | 코스트맵에 로봇 자신이 장애물로 찍힘 | `/scan_trolley_masked` 적용 확인 |
| 옆으로 못 가고 빙 돌아감 | `max_vel_y: 0.0` | 3-3 |
| 목표를 지나쳐 왔다갔다 | 속도가 너무 빠름 / 트롤리 관성 | `max_vel_x` 낮추기 |
| 벽에 스침 | 풋프린트가 실제보다 작음 | 여유 늘리기 |

---

## 6단계. 태스크 위치 좌표 찍기

5단계가 되면, 각 태스크의 **데모 수집 자리**로 로봇을 직접 가져다 놓고 좌표를 읽습니다.

```bash
ros2 topic echo /amcl_pose --once
```

쿼터니언 → yaw(도) 변환:

```python
import math
yaw_deg = math.degrees(2 * math.atan2(qz, qw))
```

`config/tasks.yaml` 에 기입:

```yaml
  - id: bedroom
    name: 안방
    pose: {x: 2.41, y: -1.08, yaw: 92.5}
```

장소 4곳 전부 반복하세요.

> ⚠️ 이 좌표는 **SmolVLA 데모를 수집한 그 자리**여야 합니다. 10cm 만 틀어져도 조작이
> 실패합니다. 바닥에 테이프로 표시해두고, 데모 수집과 좌표 측정을 같은 자리에서 하세요.

---

## 7단계. 에이전트에 연결

Pi-B 에서 자율주행 노드를 띄웁니다.

```bash
python src/nav_node.py
```

```
Nav2 액션 서버 대기 중: navigate_to_pose
Nav2 연결됨
제어 소켓 대기 중: tcp://0.0.0.0:5581
```

`config/robot.yaml` 의 `navigation.control_address` 를 Pi-B 의 IP 로 맞추면
PC 의 `main.py` 가 여기로 목표를 던집니다.

> ✅ **성공 판정** — PC 에서 `python src/main.py --once "분리수거 해줘"` 를 치면
> 로봇이 부엌으로 간다.

---

## 요약 체크리스트

```
[ ] 0.  /cmd_vel 로 바퀴가 돈다
[ ] 1.  ~/maps/home.yaml + home.pgm 이 Pi-B 에 있다 (트롤리 단 상태로 만든 맵)
[ ] 2.  ros2 pkg list 에 nav2_bringup 이 보인다
[ ] 3.  nav2_home.yaml 에 스캔 토픽·풋프린트·vy 를 반영했다
[ ] 4.  tf2_echo map base_link 가 좌표를 뱉는다
[ ] 5.  RViz 의 2D Goal Pose 로 로봇이 스스로 간다     ← 진짜 관문
[ ] 6.  tasks.yaml 의 pose 4곳을 실측값으로 채웠다
[ ] 7.  nav_node.py 가 떠 있고 PC 에서 명령이 간다
```

0~2단계는 반나절, 3~5단계가 1~2일, 6~7단계는 반나절 정도로 보시면 됩니다.
가장 오래 걸리는 건 3~5단계의 파라미터 튜닝입니다.

이 작업과 **SmolVLA 데이터 수집은 병렬로 진행할 수 있습니다.** 서로 안 막히니
데이터 수집을 지금 동시에 시작하세요 — 그쪽이 사람 손으로 며칠 걸립니다.
