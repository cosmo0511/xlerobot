# lang — 언어 조건부 제어와 직접 추론

정책 서버(`src/arm_node.py`) 없이 **PC 에서 바로 돌리는 추론 경로**와,
사람의 말을 모델이 아는 지시문으로 바꾸는 해석기입니다.

파이에서 `./scripts/host.sh` 만 떠 있으면 되고, PC 터미널 하나로 끝납니다.

## 빠른 시작

```bash
# 🍓 파이 — 모델이 4cam 으로 학습됐으므로 반드시 4cam
CAMERA_SET=4cam ./scripts/host.sh

# 💻 PC — SmolVLA (언어 지시 가능)
python lang/lang_infer.py --policy-path=bilimili/xlerobot-dice-4cam-v2-smolvla --display

# 💻 PC — ACT (언어 없음, 대조군)
python lang/act_infer.py --policy-path=bilimili/xlerobot-dice-4cam-v2-act --display
```

파이 주소·로봇 id 는 `config/robot.yaml` 의 `arms` 에서(`PI_HOST=` 로 변경),
카메라는 `config/cameras.<구성>.yaml` 에서 읽습니다 — 녹화·`arm_node.py` 와 같은 파일.
구성은 `--camera-set` > `CAMERA_SET` > 정책 카메라와 이름이 맞는 구성 순서로 고르고,
정책이 기대하는 카메라와 다르면 로봇에 붙기 전에 멈춥니다.

조작키 — `R` 빨강 / `Y` 노랑 / `T` 문장으로 말하기 / `SPACE` 일시정지 / `Q` 종료

`--fps` 는 기본 30 입니다. **학습 데이터의 fps 와 같아야 합니다.** 제한을 걸지 않으면
PC 성능에 따라 로봇이 학습 때보다 빠르게 움직입니다.

## 파일

| 파일 | 하는 일 |
|---|---|
| `lang_parser.py` | 사람 말 → 학습 때 쓴 지시문. LLM 없이 키워드로. `--test` 로 33항목 시험 |
| `llm_parser.py` | 위가 못 알아들을 때 LLM(Qwen)으로. 모델이 없으면 자동으로 건너뜀 |
| `lang_infer.py` | SmolVLA 추론. 돌리는 중에 지시를 바꿀 수 있음 |
| `act_infer.py` | ACT 추론. ACT 는 언어 입력이 없어 지시를 바꿀 수 없음 |
| `eval_following.py` | 지시 추종률 혼동행렬. "항상 한쪽만 고르는" 모델을 걸러냄 |
| `dataset_tools.py` | 데이터셋 지시문 분포 점검(`check`)과 병합(`merge`) |
| `pose_guide.py` | 에피소드마다 리더암을 같은 자세로 맞추도록 안내 |
| `record_alternating.sh` | 지시문을 번갈아 가며 녹화 |

지시문을 바꾸려면 `lang_parser.py` 의 `TASKS` 만 고칩니다.
**`task` 문자열은 학습 데이터와 글자 하나까지 같아야 합니다.**

## analysis — 로봇 없이 재는 지표

실제 로봇을 돌리지 않고 체크포인트를 비교할 때 씁니다. 시행 횟수에 묶이지 않습니다.

| 파일 | 재는 것 |
|---|---|
| `analysis/lang_strength.py` | **지시문 교체 시험.** 반대 지시를 넣었을 때 오차가 몇 배 커지는가 |
| `analysis/lang_wiring.py` | 지시문이 토큰으로 변환돼 모델까지 가는지 (배선 점검) |
| `analysis/robustness.py` | 영상을 흔들었을 때 출력이 얼마나 무너지는가 |
| `analysis/infer_time.py` | 추론 1회 / 큐 꺼내기 시간. 제어 주기를 지킬 수 있는지 |
| `analysis/memorization_probe.py` | **99.7% 의 이유.** 분기 3초~0.17초 전 시점별 정답률 + "같은 배치 짝" 영상·관절 교체로 장면 암기 vs 움직임 시작 흔적 구분 |
| `analysis/bias_probe.py` | **왜 한쪽 팔만?** 왼팔·오른팔 데이터 비중 + 영상·관절 단서를 지웠을 때 정책이 기본으로 가는 팔 |
| `analysis/shortcut_probe.py` | **지름길 점검.** 팔이 갈라지는 시점 앞뒤에서 지시문·영상·관절 상태를 하나씩 바꿔 예측 팔이 뒤집히는지 (104 에피소드 전부) |

⚠️ `lang_strength.py` · `robustness.py` 는 `select_action` 의 행동 큐 때문에 에피소드당 **첫 프레임에서 한 번만** 추론하고,
비교 구간도 0–19초(주행)뿐입니다. 그 결과(1.44배, 1.3배)는 팔 선택에 대한 언어·영상 영향이 아닙니다 (2026-10-16 확인).
언어 영향은 `shortcut_probe.py` 로 재세요.

### 교체 시험 읽는 법

같은 영상에 올바른 지시문과 반대 지시문을 각각 넣고, 사람 동작과의 오차를 비교합니다.

| 비율 | 뜻 |
|---|---|
| 1.0 근처 | 지시문을 전혀 안 본다 |
| 1.4 | 출력이 흔들리지만 팔을 바꿀 만큼은 아니다 |
| 3 ~ 5 | 지시대로 다른 대상을 향한다 |

## 알려진 문제 (2026-10-14)

`action` 과 `observation.state` 의 이름이 **완전히 같습니다**(관절 15개).
그래서 "지금 관절값을 그대로 내놓기"만 해도 오차가 1.215 로, 전체 평균을
내놓는 모델(8.087)보다 7배 정확합니다. 영상도 지시문도 안 보고 얻는 점수입니다.

학습이 이 지름길에 머무르면 **시작 자세에서 어느 팔로 갈지 결정하는 법을 배우지
않습니다.** 실제로 ACT 는 20회 중 19회 같은 팔을 썼고, SmolVLA 의 교체 시험
비율도 1.44 에 그쳤습니다.

학습률 일정도 확인하세요. `scheduler_decay_steps` 는 학습이 **짧을 때만**
자동 조정되고 길어질 때는 조정되지 않습니다. `--steps` 를 올리면 반드시
같이 올려야 합니다. 안 그러면 그 이후 구간이 최고값의 1/40 로 돕니다.

```bash
--steps=80000 --policy.scheduler_decay_steps=80000   # 쌍으로
--dataset.eval_split=0.1 --eval_steps=2000           # 검증 없이는 판단 불가
```
