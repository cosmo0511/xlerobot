# 시뮬레이션 모델 (상류 XLeRobot 에서 가져옴)

`upstream/` 은 [Vector-Wangel/XLeRobot](https://github.com/Vector-Wangel/XLeRobot) 의
`simulation/` 폴더를 **그대로** 복사한 것입니다 (커밋 `b017b5e`, 2026-10-29, Apache-2.0 → `upstream/LICENSE`).
고치지 않았습니다. 갱신할 땐 통째로 다시 덮어쓰세요.

| 경로 | 내용 |
|---|---|
| `upstream/mujoco/xlerobot.xml`, `scene.xml` | MuJoCo MJCF. **바퀴 3개(ST3215)** + 평면 베이스(`slide_joint_x/y`, `hinge_joint_z`) |
| `upstream/xlerobot/xlerobot.urdf` | URDF (ROS/일반용). 메시 `meshes/xlerobot/assets/*.stl` |
| `upstream/Maniskill/assets/xlerobot/*.urdf` | ManiSkill 용 URDF (`xlerobot.urdf`, `xlerobot_front.urdf`) + 예제·에이전트 |
| `upstream/Isaac_sim/xlerobot.zip` | Isaac Sim 에셋 (압축) |

## ⚠️ 우리 로봇과 다른 점

- **관절 이름이 다릅니다.** 상류: `Rotation_L, Pitch_L, Elbow_L, Wrist_Pitch_L, Wrist_Roll_L, Jaw_L` (+`_R`).
  우리: `left_{shoulder_pan,shoulder_lift,elbow_flex,wrist_flex,wrist_roll,gripper}.pos` 순서 그대로 대응.
  우리 데이터를 재생하려면 이 매핑과 단위(우리 `.pos` 는 lerobot 정규화 값, 시뮬은 rad)를 맞춰야 합니다.
- **바퀴:** 두 URDF 는 **2륜 차동**(`left_wheel_joint`/`right_wheel_joint`) 입니다.
  우리 3옴니휠과 가장 가까운 건 **MuJoCo 모델**(바퀴 3개)입니다.
- **머리** `head_pan_joint` / `head_tilt_joint` 가 있지만 우리 로봇엔 없습니다 (고정으로 두면 됨).
- 카메라 위치·종류(우리는 top/base/left_wrist/right_wrist 4대)는 맞춰져 있지 않습니다.
