# XLeRobot 명령 에이전트

말로(또는 터미널 텍스트로) 명령하면, 로봇이 해당 책상으로 이동해
양팔 SmolVLA 정책으로 태스크를 수행하는 시스템.

## 구조

```
[사람 명령] "1번 책상 물 줘"  (터미널 입력)
     ↓
[agent.py]  명령 해석 → 어느 책상 + 어느 지시문
     ↓
[navigation.py]  해당 책상으로 이동 (라이다 자율주행)
     ↓ (도착)
[policy_client.py]  카메라+지시문을 GPU 서버로 전송 → 행동 수신 → 양팔 실행
     ↓
[SmolVLA 서버 (별도 GPU)]  (이미지+언어) → 팔 동작 계산
```

## 파일

| 파일 | 역할 | 상태 |
|---|---|---|
| `main.py` | 터미널 명령 입력 진입점 | 완성 |
| `agent.py` | 명령 해석 + 라우팅 (handle_command) | 완성 |
| `navigation.py` | 책상 이동 (navigate_to) | 미완성 |
| `policy_client.py` | SmolVLA 서버 호출 (run_policy) | 더미 |
| `INTERFACE.md` | 함수 간 인터페이스 규격 | — |

## 실행

```bash
python main.py
```
```
명령 > 1번 책상 물 줘
명령 > 분리수거 해줘
명령 > quit
```

현재는 navigation·policy가 더미/미완성이라 출력만 되고, 완성되면 실제로 로봇이 움직인다.

## 하드웨어

- XLeRobot, 양팔 SO-101, 카메라 3개(탑 + 손목 2)
- 라즈베리파이 4 (로봇 제어), 별도 GPU 기기 (SmolVLA 추론)
- 모델: SmolVLA 단일 정책, task_prompt(언어)로 태스크 5개 분기

## 담당별 할 일

- 자율주행: `navigation.py`의 `navigate_to`를 INTERFACE.md 규격대로 구현
- SmolVLA: `policy_client.py`의 `run_policy`를 규격대로 구현 + 서버 준비
- 에이전트/language: `agent.py` (완성), 명령→지시문 매핑 관리
