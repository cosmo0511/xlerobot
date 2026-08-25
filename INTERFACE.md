# 인터페이스 규격

담당자끼리 지켜야 할 계약. **이 규격이 바뀌면 팀 전체에 공지할 것.**

기기 표기: 🦾 Pi-A(양팔) · 🛞 Pi-B(르키위) · 💻 PC(GPU)

---

## 1. 팔 노드 제어 프로토콜 (💻 PC ↔ 🦾 Pi-A)

ZMQ REQ/REP, JSON 한 줄. 주소는 `robot.yaml` 의 `arms.control_address`.

| 요청 | 응답 | 설명 |
|---|---|---|
| `{"cmd":"ping"}` | `{"status":"done"}` | 살아 있는지 확인 |
| `{"cmd":"park","hold_gripper":bool}` | `{"status":"done"\|"failed","message":str}` | 팔을 주행 자세로 접음. `hold_gripper=true` 면 그리퍼 유지 |
| `{"cmd":"run","task":str,"max_seconds":float}` | `{"status":"done"\|"failed","message":str}` | 한 에피소드 실행 |

세 명령 모두 **블로킹**입니다. `run` 은 `max_seconds` 만큼 걸리므로 PC 쪽 타임아웃은
`max_seconds + 30초` 로 잡혀 있습니다.

> ZMQ REQ 소켓은 응답을 못 받으면 상태가 망가져 이후 요청이 전부 막힙니다.
> `policy_client.py` 는 타임아웃 시 소켓을 새로 만듭니다. 직접 짤 때 조심하세요.

---

## 2. `navigate_to(location_id) -> dict`

담당: 자율주행 · 실행: 💻 PC (Nav2 스택은 🛞 Pi-B)

**입력**
- `location_id`: `config/tasks.yaml` 의 `locations[].id` 중 하나.
- 좌표는 인자로 안 받습니다. `tasks.yaml` 의 `pose` 에서 읽습니다.

**동작**
- 블로킹. `NavigateToPose` 액션으로 목표를 던지고 결과를 기다립니다.
- Nav2 스택(라이다, AMCL, 코스트맵, 컨트롤러, 바퀴 드라이버, `/odom`, `/cmd_vel`)은
  전부 🛞 Pi-B 안에서 돕니다. **PC 는 관여하지 않습니다.**
- 도착 위치·각도는 **SmolVLA 데모 수집 때와 동일**해야 합니다 (조작 성능에 직결).
- 도착 후 `settle_s`(기본 1.5초) 대기 — 트롤리 관성이 가라앉을 때까지.
- 두 기기의 `ROS_DOMAIN_ID` 가 같아야 합니다.

**출력**
```python
{"status": "arrived" | "failed" | "blocked", "location_id": str, "message": str}
```

**호출측 규칙**
- `arrived` 일 때만 조작을 시작합니다.
- `failed` / `blocked` 면 조작을 시도하지 않고 실패를 보고합니다.

---

## 3. `run_policy(task_prompt, max_seconds) -> dict`

담당: SmolVLA · 실행: 🦾 Pi-A (추론은 💻 PC)

**입력**
- `task_prompt`: `config/tasks.yaml` 의 `tasks[].prompt` 중 정확히 하나.
  **글자·대소문자까지 학습 라벨(`--dataset.single_task`)과 동일해야 합니다.**
- `max_seconds`: 조작 제한 시간. `tasks.yaml` 의 `max_seconds`.

**동작**
- 블로킹. 30Hz 제어 루프는 🦾 Pi-A 안에서 로컬로 돕니다.
- 관측은 행동 큐가 `chunk_size_threshold`(기본 0.5) 이하로 줄 때만 전송됩니다.
  → 약 0.8초에 한 번. 매 프레임 이미지를 보내지 않습니다.
- 태스크 문자열은 관측마다 실려 가므로 **태스크 전환에 정책 재로딩이 없습니다.**
- 에피소드 시작 시 이전 태스크의 행동 큐를 비웁니다.
  (안 비우면 첫 1초 동안 이전 태스크 동작이 그대로 나갑니다)

**출력**
```python
{"status": "done" | "failed", "message": str}
```

---

## 4. `park(hold_gripper=False) -> dict`

담당: SmolVLA · 실행: 🦾 Pi-A

`robot.yaml` 의 `travel_pose` 로 `park_seconds` 에 걸쳐 선형 보간 이동.

**에이전트는 이동 전에 항상 이걸 먼저 호출하고, 실패하면 이동하지 않습니다.**
Pi 가 둘이라 주행과 조작이 하드웨어적으로 충돌하지는 않지만, 팔이 벌어진 채로
이동하면 문틀·가구에 부딪힙니다.

`hold_gripper=True` 면 **그리퍼 관절을 건드리지 않습니다.**
여러 단계짜리 태스크에서 물건을 든 채로 다음 위치로 이동할 때 필수입니다.
False 로 부르면 `travel_pose` 의 그리퍼 값으로 움직여서 물건을 떨어뜨립니다.

에이전트의 호출 규칙:

| 시점 | hold_gripper |
|---|---|
| 첫 단계 전 | `False` |
| 단계 사이 | `True` — 물건 운반 중 |
| 마지막 단계 후 | `False` |

관절 이름이 로봇과 다르면 `failed` 와 함께 어긋난 키를 알려줍니다.

---

## 5. `config/tasks.yaml` — 태스크·위치의 단일 진실 소스

**태스크는 단계(steps)의 나열입니다.** 한 자리에서 끝나는 것도, 중간에 이동이 끼는
것도 같은 형식으로 씁니다.

```yaml
locations:
  - id: desk_1
    name: 1번 책상
    pose: {x: 2.41, y: -1.08, yaw: 92.5}    # Nav2 map 프레임, yaw 는 도

tasks:
  - id: toy_transfer
    name: 물건 옮기기
    aliases: ["장난감 옮겨줘"]                 # LLM 힌트 + 오프라인 폴백용
    steps:
      - location: desk_1
        prompt: "Pick up the toy from the desk"   # 학습 라벨과 글자까지 동일
        max_seconds: 60
      - location: desk_2
        prompt: "Place the toy on the desk"
        max_seconds: 60
```

**단계마다 별도의 학습 라벨입니다.** 2단계 태스크면 데모도 2종류를 찍습니다.
찍어야 할 라벨 목록은 이걸로 확인하세요:

```bash
python src/task_registry.py
```

`task_registry.py` 가 프로그램 시작 시점에 검증합니다:
- 중복 task id → 에러
- `steps` 가 비었거나 `prompt` 가 없음 → 에러
- `location` 이 `locations` 에 없음 → 에러
- prompt 앞뒤 공백 → 에러 (학습 라벨과 어긋나는 대표적 원인)
- `pose` 가 `(0,0,0)` → 실행 시 `failed` + 안내 메시지

**태스크를 바꾸면 학습 데이터셋의 `single_task` 도 같이 맞추세요.**
안 맞아도 에러가 안 납니다. 조용히 성능만 떨어집니다.

### 다단계 태스크의 이어붙는 지점

1단계가 끝난 팔 자세 = 2단계가 시작하는 팔 자세여야 합니다.
둘 다 **파킹 자세**로 통일하고, 데모도 그렇게 찍으세요. 자세한 건 COLLECTING.md 참고.

---

## 6. 카메라 이름 규칙

`bi_so_follower` 가 접두사를 자동으로 붙입니다.

| robot.yaml | 적는 이름 | 최종 관측 키 |
|---|---|---|
| `top_cameras` | `top` | `observation.images.top` |
| `left_cameras` | `wrist` | `observation.images.left_wrist` |
| `right_cameras` | `wrist` | `observation.images.right_wrist` |

이 최종 키가 데모 수집 때와 같아야 SmolVLA 가 이미지를 찾습니다.

---

## 7. 현재 상태

| 파일 | 도는 곳 | 상태 |
|---|---|---|
| `task_registry.py` | 💻 PC | 완성, 테스트 통과 |
| `agent.py` | 💻 PC | 완성 (Gemini + 키워드 폴백) |
| `main.py` | 💻 PC | 완성 |
| `policy_client.py` | 💻 PC | 완성 (드라이런 지원) |
| `navigation.py` | 💻 PC | 구현 완료 — **Nav2 실기 검증 필요**, 좌표 미작성 |
| `arm_node.py` | 🦾 Pi-A | 구현 완료 — **실기 검증 필요**, `travel_pose` 값 미측정 |
| Nav2 스택 | 🛞 Pi-B | 맵핑까지 확인됨 — Nav2 기동 여부 확인 필요 |
| SmolVLA 체크포인트 | 💻 PC | **미학습** — 데이터 수집부터 |
