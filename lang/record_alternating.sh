#!/usr/bin/env bash
# 지시문을 번갈아 바꿔가며 데이터셋을 쌓는다.
#
# lerobot-record 는 한 번에 지시문 하나만 받는다(--dataset.single_task).
# 그래서 지시문별로 따로 쌓은 뒤 dataset_tools.py merge 로 합친다.
#
#   ./record_alternating.sh 30          지시문당 30 에피소드
#
set -euo pipefail

EPISODES="${1:-30}"
HF_USER="${HF_USER:-roboseasylabs}"
DATA_ROOT="$HOME/workspace/lerobot_data"
REMOTE_IP="${REMOTE_IP:-192.168.200.114}"

# 지시문 — lang_parser.py 의 TASKS 와 글자까지 같아야 한다
declare -A TASKS=(
  [red]="Pick up the red block"
  [blue]="Pick up the blue block"
)

CAMERAS='{"cam_wrist_left": {"type": "opencv", "index_or_path": "/dev/cam_left", "width": 640, "height": 480, "fps": 30},
          "cam_wrist_right": {"type": "opencv", "index_or_path": "/dev/cam_right", "width": 640, "height": 480, "fps": 30},
          "cam_top": {"type": "opencv", "index_or_path": "/dev/cam_top", "width": 640, "height": 480, "fps": 30}}'

echo "════════════════════════════════════════════════════════"
echo " 언어 데이터셋 수집   지시문당 ${EPISODES} 에피소드"
echo "════════════════════════════════════════════════════════"
for k in "${!TASKS[@]}"; do
  echo "   ${k}: \"${TASKS[$k]}\"  →  ${DATA_ROOT}/pick_${k}"
done
echo
echo " 주의"
echo "   · 색마다 블록 위치를 골고루 바꿔 주세요."
echo "   · 개수를 맞춰야 모델이 한쪽으로 치우치지 않습니다."
echo
read -rp " 시작하려면 Enter, 취소는 Ctrl+C > "

for k in "${!TASKS[@]}"; do
  echo
  echo "────────────────────────────────────────────────────────"
  echo " [${k}]  \"${TASKS[$k]}\"   ${EPISODES} 에피소드"
  echo "────────────────────────────────────────────────────────"
  read -rp " ${k} 블록을 놓고 Enter > "

  lerobot-record \
      --robot.type=bi_so_base_client \
      --robot.remote_ip="${REMOTE_IP}" \
      --robot.id=bi_so101 \
      --robot.cameras="${CAMERAS}" \
      --teleop.type=bi_so_base_leader \
      --teleop.left_arm_config.port=/dev/so101_leader_left \
      --teleop.right_arm_config.port=/dev/so101_leader_right \
      --teleop.id=bi_so101_leader \
      --dataset.repo_id="${HF_USER}/pick_${k}" \
      --dataset.root="${DATA_ROOT}/pick_${k}" \
      --dataset.single_task="${TASKS[$k]}" \
      --dataset.num_episodes="${EPISODES}" \
      --dataset.episode_time_s=60 \
      --dataset.reset_time_s=10 \
      --dataset.fps=30 \
      --dataset.push_to_hub=false \
      --display_data=true
done

echo
echo "════════════════════════════════════════════════════════"
echo " 수집 완료. 이제 합치세요:"
echo
echo "   python dataset_tools.py merge \\"
echo "       ${DATA_ROOT}/pick_red_blue \\"
for k in "${!TASKS[@]}"; do echo "       ${DATA_ROOT}/pick_${k} \\"; done
echo
echo " 그다음 확인:"
echo "   python dataset_tools.py check ${DATA_ROOT}/pick_red_blue"
echo "════════════════════════════════════════════════════════"
