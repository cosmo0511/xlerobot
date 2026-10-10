# vendor/ — 우리가 고친 lerobot 0.6

`lerobot-0.6.patch` 는 lerobot **v0.6.0** (커밋 `30da8e6`) 에 우리가 붙인 수정 전부입니다.
이게 없으면 `bi_so_base_client` / `bi_so_base_leader` / `bi_so_base_host` 가 없어서
`scripts/record.sh` 와 `scripts/host.sh` 가 돌지 않습니다.

- 35 files, +2471 / -21 (기존 파일 15개 수정 + 새 파일 20개)
- 깨끗한 v0.6.0 에 적용하면 원본 PC(`/home/user/lerobot_0.6`)의 `src/` 와 바이트 단위로 같아지는 것 확인함

## 설치 (PC, 라즈베리파이 둘 다)

```bash
git clone https://github.com/huggingface/lerobot.git lerobot_0.6
cd lerobot_0.6
git checkout v0.6.0
git apply /path/to/xlerobot/vendor/lerobot-0.6.patch
pip install -e ".[feetech]"
```

> ⚠️ `pip install -U lerobot` 를 하면 editable 설치가 PyPI 버전으로 덮여서 이 수정이
> 사라집니다. 그 경우 위 순서를 다시 하세요.

## 들어 있는 것

| 타입 이름 | 파일 | 어디서 |
|---|---|---|
| `bi_so_base_follower` (로봇) | `robots/bi_so_follower/bi_so_base_follower.py` | 파이 — 양팔 + 바퀴 3개를 직접 엶 |
| (호스트, `python -m ...bi_so_base_host`) | `robots/bi_so_follower/bi_so_base_host.py` | 파이 — ZMQ 5555/5556 |
| `bi_so_base_client` (로봇) | `robots/bi_so_follower/bi_so_base_client.py` | PC — 녹화·텔레옵 |
| `bi_so_base_leader` (텔레옵) | `teleoperators/bi_so_leader/bi_so_base_leader.py` | PC — 리더암 2개 + 키보드를 **한 텔레옵**으로 |
| `bi_so_client` / `bi_so_host` | `robots/bi_so_follower/bi_so_{client,host}.py` | 바퀴 없는 양팔 버전 |
| `so102_*`, `bi_so102_*` | `robots/so102_follower/`, `teleoperators/so102_leader/` 등 | SO-102 팔 |

나머지는 `make_robot_from_config` / `make_teleoperator_from_config` 등록과
`lerobot_*.py` 스크립트의 import 추가입니다. `lerobot_record.py` 의 녹화 로직은 **안 바뀌었습니다**.

## 패치 갱신

lerobot 소스를 더 고쳤으면 다시 뽑아서 이 파일을 교체하고 커밋하세요:

```bash
cd /home/user/lerobot_0.6
git add -N . && git diff --binary > /path/to/xlerobot/vendor/lerobot-0.6.patch && git reset
```
