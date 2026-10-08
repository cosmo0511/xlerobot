#!/usr/bin/env bash
# Isaac Sim / Isaac Lab 쪽 쉘 환경.
#   - conda `isaac_lab` (python 3.11) 활성화
#   - /opt/ros/humble 은 절대 source 하지 않음 (3.10 심볼이 Kit 기동을 깨뜨립니다)
#   - 대신 Isaac Sim 에 번들된 내부 Humble 라이브러리를 LD_LIBRARY_PATH 에 한 번만 추가
#
# source 전용. 실행하지 말고 `source isaac-env.sh` 로 쓰세요.

CONDA_DIR="${CONDA_DIR:-/opt/conda}"
ISAAC_CONDA_ENV="${ISAAC_CONDA_ENV:-isaac_lab}"

if [[ "${CONDA_DEFAULT_ENV:-}" != "${ISAAC_CONDA_ENV}" ]]; then
  # shellcheck disable=SC1091
  source "${CONDA_DIR}/etc/profile.d/conda.sh"
  conda activate "${ISAAC_CONDA_ENV}"
fi

export ISAACLAB_PATH="${ISAACLAB_PATH:-/opt/IsaacLab}"
export OMNI_KIT_ACCEPT_EULA=YES
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
export ROS_DISTRO="${ROS_DISTRO:-humble}"

# AMENT_PREFIX_PATH 가 남아 있으면 ros2_bridge 가 시스템(3.10) 설치를 먼저 집습니다.
unset AMENT_PREFIX_PATH CMAKE_PREFIX_PATH COLCON_PREFIX_PATH PYTHONPATH ROS_PYTHON_VERSION

# ros2_bridge 확장이 품고 있는 내부 humble 라이브러리 경로를 찾습니다.
# 경로 이름은 버전마다 바뀌어 왔으므로(omni.isaac.ros2_bridge -> isaacsim.ros2.bridge)
# 하드코딩하지 않고 탐색합니다.
if [[ -z "${ISAAC_ROS_LIB_ADDED:-}" ]]; then
  _isaac_root="$(python -c 'import isaacsim, pathlib; print(pathlib.Path(isaacsim.__file__).parent)' 2>/dev/null)"
  if [[ -n "${_isaac_root}" ]]; then
    _ros_lib="$(find "${_isaac_root}" -maxdepth 4 -type d \
                  -path "*ros2*${ROS_DISTRO}/lib" -print -quit 2>/dev/null)"
    if [[ -n "${_ros_lib}" ]]; then
      export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:+${LD_LIBRARY_PATH}:}${_ros_lib}"
      export ISAAC_ROS_LIB_ADDED=1
      export ISAAC_ROS_LIB_PATH="${_ros_lib}"
    else
      echo "[isaac-env] 내부 ROS 2 ${ROS_DISTRO} 라이브러리를 못 찾았습니다." >&2
      echo "[isaac-env] ROS 2 브리지를 쓸 거면 ${_isaac_root} 아래 ros2 확장 설치를 확인하세요." >&2
    fi
  fi
  unset _isaac_root _ros_lib
fi

alias isaaclab="${ISAACLAB_PATH}/isaaclab.sh"
