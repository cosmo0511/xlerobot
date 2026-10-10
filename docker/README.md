# docker/ — 학습 컨테이너 (GPU 서버용)

SmolVLA / ACT 학습을 GPU 서버(예: RTX 5090 32GB)에서 돌릴 때 씁니다.
서버에서 `pip install` 을 자유롭게 할 수 있으면 컨테이너 없이 venv 로 해도 됩니다
(`RUNNING.md` 3단계). 학습 규칙(둘 다 batch 16 / 80k, 평가는 마지막 체크포인트)은
`scripts/train.sh` 에 고정돼 있어서 어느 쪽이든 같은 조건입니다.

## 클라우드 콘솔(AIEEV Air Container 등)에서 — 이미지 빌드 없이

콘솔이 공개 이미지 주소만 받으면, 이미지를 만들어 올리지 말고 `python:3.12-slim` 으로
띄운 뒤 웹 터미널에서 `setup_cloud.sh` 를 한 번 돌리세요. 결과는 아래 Dockerfile 과 같습니다.

| 항목 | 값 |
|---|---|
| 이미지 | `python:3.12-slim` (Docker Hub, 공개) |
| GPU / 레플리카 | RTX 5090 / **1** |
| 영구 볼륨 | 켜기, 마운트 `/workspace`, 50GB (환경·데이터셋 3GB·체크포인트 ~10GB) |
| 시작 명령 | `sleep infinity` (기본 명령은 바로 끝나서 컨테이너가 꺼짐) |
| 공유 메모리 | 켜기, 16GB (데이터 로더) |
| 포트·헬스 체크 URL·SSH 키·API 키·환경 변수 | 비워 둠 (웹 서버가 없어서 헬스 체크를 넣으면 재시작됨) |

웹 터미널에서 (`python:3.12-slim` 에는 `curl` 이 없어서 먼저 깝니다):

```bash
apt-get update && apt-get install -y curl && curl -fsSL https://raw.githubusercontent.com/cosmo0511/xlerobot/main/docker/setup_cloud.sh | bash
source /workspace/env.sh
STEPS=20 OUTPUT_DIR=/tmp/probe ./scripts/train.sh act      # 메모리 확인
tmux new -s train    # setup_cloud.sh 가 tmux 도 깝니다
./scripts/train.sh smolvla
```

원본 PC 에서 빈 `python:3.12-slim` 컨테이너로 이 순서를 그대로 돌려 Hub 데이터셋으로 ACT 5스텝까지
확인했습니다 (2026-10-10). 결과는 `/workspace/xlerobot/outputs/train/` — 영구 볼륨이라 재시작해도 남습니다.

## 직접 Docker 를 쓸 수 있는 서버에서

## 0. 서버에서 확인할 것

```bash
nvidia-smi                                         # 드라이버 570 이상 (5090 최소 조건)
docker run --rm --gpus all ubuntu nvidia-smi       # 컨테이너에서 GPU 가 보이는지
```

두 번째가 실패하면 서버에 NVIDIA Container Toolkit 이 없는 겁니다 (관리자에게 요청).

## 1. 빌드 (레포 루트에서)

```bash
git clone https://github.com/cosmo0511/xlerobot.git && cd xlerobot
docker build -f docker/Dockerfile.train -t xlerobot-train .
```

드라이버가 580 이상이면 `--build-arg TORCH_CUDA=cu130` 도 됩니다 (기본 cu128).

## 2. 실행

모델·데이터셋 캐시(`/cache`)와 결과(`/xlerobot/outputs`)를 서버 디스크에 붙입니다.
안 붙이면 컨테이너를 지울 때 학습 결과도 같이 사라집니다.

```bash
mkdir -p ~/xlerobot-cache outputs
docker run --rm -it --gpus all --shm-size=16g --user $(id -u):$(id -g) \
  -v ~/xlerobot-cache:/cache -v $PWD/outputs:/xlerobot/outputs \
  xlerobot-train ./scripts/train.sh smolvla
```

ACT 는 마지막 `smolvla` 를 `act` 로. 32GB 면 두 개를 터미널 두 개에서 **동시에** 돌려도
메모리에 들어갑니다 (추정 8 + 16GB — 아래 메모리 확인 먼저).

- `--shm-size=16g` 은 데이터 로더(`num_workers=4`)가 공유 메모리를 써서 필요합니다.
  기본값(64MB)이면 "bus error" 로 죽습니다.
- `--user` 는 결과 파일이 root 소유로 생기지 않게 합니다.
- 오래 걸리니 `tmux` / `screen` 안에서 돌리거나 `-it` 대신 `-d` 로 띄우세요
  (`docker logs -f <컨테이너>` 로 보기).

### 처음 한 번: 메모리 확인 (각 1분 정도)

batch 16 은 노트북(8GB) 실측에서 **추정**한 값입니다. 본 학습 전에 20스텝으로 확인하세요:

```bash
docker run --rm --gpus all --shm-size=16g --user $(id -u):$(id -g) \
  -v ~/xlerobot-cache:/cache -e STEPS=20 -e OUTPUT_DIR=/tmp/probe \
  xlerobot-train ./scripts/train.sh act
```

로그 마지막 줄의 `mem_gb` 와 `updt_s`(스텝당 초)를 보면 됩니다. smolvla 도 같은 방식.

### 끊겼을 때 이어가기

```bash
docker run ... xlerobot-train lerobot-train --resume=true \
  --config_path=outputs/train/smolvla_dice/checkpoints/last/pretrained_model/train_config.json
```

## 3. 결과를 원본 PC 로

```bash
# 원본 PC 에서
scp -r <서버>:~/xlerobot/outputs/train/smolvla_dice ~/xlerobot/outputs/train/
scp -r <서버>:~/xlerobot/outputs/train/act_dice     ~/xlerobot/outputs/train/
```

경로가 `config/robot.yaml` 의 `policy.path` 와 그대로 맞습니다. 평가에는 `checkpoints/last` 만.
