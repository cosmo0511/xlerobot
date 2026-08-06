# 인터페이스 규격

에이전트(`agent.py`) ↔ 자율주행(`navigation.py`) ↔ SmolVLA(`policy_client.py`)
간 연결 지점의 계약. **이 규격이 바뀌면 반드시 팀 전체에 공지할 것.**

에이전트는 아래 두 함수를 호출한다. 각 담당자는 자기 파일 안에서 이 입력·출력 모양을
그대로 지키기만 하면 되고, 내부 구현은 자유롭게 해도 된다. `agent.py`는 이 함수들을
import해서 쓰므로, 더미를 실제 코드로 교체해도 `agent.py`는 건드릴 필요 없다.

---

## `navigate_to(desk_id: str) -> dict`

담당: 자율주행 (`navigation.py`)

**입력**
- `desk_id`: `"desk_1"` | `"desk_2"` | `"desk_3"`
- 좌표는 여기서 안 받는다. desk_id → 좌표 변환은 `navigation.py` 내부 책임.

**동작**
- 블로킹 호출. 해당 책상에서 팔이 조작 가능한 위치까지 이동을 마친 뒤 반환한다.
- 도착 위치·각도는 SmolVLA 데이터 수집 때와 동일해야 한다 (조작 성능에 직결).
- 타임아웃 60초 권장.

**출력**
```python
{"status": "arrived" | "failed" | "blocked", "desk_id": str, "message": str}
```

**호출측(에이전트) 규칙**
- `status == "arrived"`일 때만 `run_policy`를 호출한다.
- `failed`/`blocked`면 실패를 알리고 조작을 시도하지 않는다.

---

## `run_policy(task_prompt: str) -> dict`

담당: SmolVLA (`policy_client.py`)

**입력**
- `task_prompt`: 아래 5개 문자열 중 정확히 하나. **글자·대소문자까지 학습 라벨과 동일.**
  - `"Water the plant"`
  - `"Give nutrients to the plant"`
  - `"Fold the towel and put it away"`
  - `"Sweep with the dustpan"`
  - `"Sort the recycling"`

**동작**
- 블로킹 호출. GPU의 SmolVLA 서버에 카메라 이미지 + `task_prompt`를 보내고,
  조작이 끝날 때까지 대기 후 반환.

**출력**
```python
{"status": "done" | "failed", "message": str}
```

---

## 태스크 ↔ 책상 매핑

| desk_id | task_prompt |
|---|---|
| desk_1 | "Water the plant" |
| desk_1 | "Give nutrients to the plant" |
| desk_2 | "Fold the towel and put it away" |
| desk_2 | "Sweep with the dustpan" |
| desk_3 | "Sort the recycling" |

정책은 **양팔 SmolVLA 단일 모델 1개**. 태스크 5개는 정책 여러 개가 아니라
task_prompt(언어)로 분기한다.

---

## 현재 상태

- `agent.py`: 완성, 더미로 테스트 통과
- `navigation.py`: 미완성 (자율주행 담당이 규격대로 채울 것)
- `policy_client.py`: 더미 상태 (SmolVLA 담당이 규격대로 채울 것)
