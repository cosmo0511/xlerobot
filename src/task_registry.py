"""
task_registry.py — config/tasks.yaml 을 읽어서 검증하는 로더.

왜 필요한가?
------------
태스크 문자열이 코드 여러 곳에 흩어져 있으면, 하나를 바꿀 때 한 곳을 빠뜨리기 쉽습니다.
그러면 **학습 라벨과 글자가 다른 지시문**이 정책에 들어가는데, 이건 에러가 안 나고
조용히 성능만 떨어집니다. 그래서 더 위험합니다.

정의를 YAML 한 곳으로 몰고, 이 파일이 프로그램 시작 시점에 정합성을 검사합니다.
잘못된 설정이면 로봇이 움직이기 전에 죽습니다.

태스크는 "단계(step)"의 나열
----------------------------
한 자리에서 끝나는 태스크(화분 물주기)도 있고, 중간에 이동이 끼는 태스크
(1번 책상에서 집어서 2번 책상에 놓기)도 있습니다. 그래서 태스크가 단계를 여러 개
가질 수 있게 했습니다. 단계 1개짜리는 그냥 특수한 경우입니다.

사용법
------
    from task_registry import load_registry
    reg = load_registry()
    reg.task_ids                     # -> ["toy_transfer", ...]
    reg.tasks["toy_transfer"].steps  # -> [Step(location="desk_1", prompt="Pick up..."), ...]
    reg.pose_of("desk_1")            # -> Pose(x=..., y=..., yaw_deg=...)
    reg.all_prompts()                # -> 학습 라벨 전체 (데이터 수집 체크용)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TASKS_PATH = PROJECT_ROOT / "config" / "tasks.yaml"


@dataclass(frozen=True)
class Pose:
    """Nav2 map 프레임 기준 목표 자세."""

    x: float
    y: float
    yaw_deg: float

    @property
    def yaw_rad(self) -> float:
        return math.radians(self.yaw_deg)

    def as_quaternion(self) -> tuple[float, float, float, float]:
        """yaw 만 있는 2D 자세를 (x, y, z, w) 쿼터니언으로. Nav2 가 이 형식을 요구합니다."""
        half = self.yaw_rad / 2.0
        return (0.0, 0.0, math.sin(half), math.cos(half))


@dataclass(frozen=True)
class Location:
    id: str
    name: str
    pose: Pose

    @property
    def is_placeholder(self) -> bool:
        """좌표를 아직 안 찍은 상태인지. (0,0,0)이면 아직 맵을 안 만든 것으로 봅니다."""
        return self.pose.x == 0.0 and self.pose.y == 0.0 and self.pose.yaw_deg == 0.0


@dataclass(frozen=True)
class Step:
    """태스크의 한 단계. 한 위치에서 한 정책을 돌립니다."""

    location: str
    prompt: str
    max_seconds: float = 120.0
    # 이 단계가 끝났을 때 그리퍼에 물건이 있어야 하는가.
    # True 인데 그리퍼가 끝까지 닫혀 있으면(= 아무것도 못 잡음) 실패로 처리하고
    # 다음 단계로 넘어가지 않습니다. 못 집고도 다음 책상까지 가는 걸 막습니다.
    expect_holding: bool = False


@dataclass(frozen=True)
class Task:
    id: str
    name: str
    steps: tuple[Step, ...]
    aliases: tuple[str, ...] = ()

    @property
    def is_multi_step(self) -> bool:
        return len(self.steps) > 1


@dataclass
class TaskRegistry:
    locations: dict[str, Location] = field(default_factory=dict)
    tasks: dict[str, Task] = field(default_factory=dict)  # task id -> Task

    # --- 조회 ------------------------------------------------------------
    @property
    def task_ids(self) -> list[str]:
        return list(self.tasks.keys())

    def all_prompts(self) -> list[str]:
        """모든 단계의 지시문. 데이터 수집 때 찍어야 할 학습 라벨 목록입니다."""
        seen: list[str] = []
        for task in self.tasks.values():
            for step in task.steps:
                if step.prompt not in seen:
                    seen.append(step.prompt)
        return seen

    def pose_of(self, location_id: str) -> Pose:
        return self.locations[location_id].pose

    def location_name(self, location_id: str) -> str:
        return self.locations[location_id].name

    def describe_for_llm(self) -> str:
        """LLM 시스템 프롬프트에 넣을 태스크 목록 텍스트."""
        lines = []
        for task in self.tasks.values():
            where = " → ".join(self.location_name(s.location) for s in task.steps)
            hint = f"  <- e.g. {', '.join(task.aliases)}" if task.aliases else ""
            lines.append(f'  "{task.id}": {task.name} ({where}){hint}')
        return "\n".join(lines)

    def placeholder_locations(self) -> list[str]:
        """좌표가 아직 (0,0,0)인 위치 목록. 실행 전 경고용."""
        return [loc_id for loc_id, loc in self.locations.items() if loc.is_placeholder]


class TaskConfigError(ValueError):
    """tasks.yaml 이 잘못됐을 때. 로봇이 움직이기 전에 터뜨리는 게 목적."""


def load_registry(path: str | Path | None = None) -> TaskRegistry:
    """tasks.yaml 을 읽고 검증한 TaskRegistry 를 반환."""
    path = Path(path) if path else DEFAULT_TASKS_PATH
    if not path.exists():
        raise TaskConfigError(f"설정 파일이 없습니다: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    # --- locations ---
    locations: dict[str, Location] = {}
    for entry in raw.get("locations", []):
        loc_id = entry.get("id")
        if not loc_id:
            raise TaskConfigError(f"locations 항목에 id 가 없습니다: {entry}")
        if loc_id in locations:
            raise TaskConfigError(f"위치 id 가 중복됩니다: {loc_id!r}")
        p = entry.get("pose") or {}
        locations[loc_id] = Location(
            id=loc_id,
            name=entry.get("name", loc_id),
            pose=Pose(
                x=float(p.get("x", 0.0)),
                y=float(p.get("y", 0.0)),
                yaw_deg=float(p.get("yaw", 0.0)),
            ),
        )
    if not locations:
        raise TaskConfigError("locations 가 비어 있습니다.")

    # --- tasks ---
    tasks: dict[str, Task] = {}
    prompt_owner: dict[str, str] = {}  # prompt -> 처음 쓴 task id

    for entry in raw.get("tasks", []):
        task_id = entry.get("id")
        if not task_id:
            raise TaskConfigError(f"tasks 항목에 id 가 없습니다: {entry}")
        if task_id in tasks:
            raise TaskConfigError(f"task id 가 중복됩니다: {task_id!r}")

        raw_steps = entry.get("steps") or []
        if not raw_steps:
            raise TaskConfigError(f"task {task_id!r} 에 steps 가 없습니다.")

        steps: list[Step] = []
        for i, s in enumerate(raw_steps, 1):
            prompt = s.get("prompt")
            if not prompt:
                raise TaskConfigError(f"task {task_id!r} 의 {i}단계에 prompt 가 없습니다.")
            # 앞뒤 공백은 학습 라벨과의 불일치를 만드는 대표적 원인 -> 즉시 거부
            if prompt != prompt.strip():
                raise TaskConfigError(
                    f"task {task_id!r} {i}단계의 prompt 앞뒤에 공백이 있습니다: {prompt!r} "
                    "(학습 라벨과 글자가 달라져 정책이 조용히 실패합니다)"
                )
            loc = s.get("location")
            if loc not in locations:
                raise TaskConfigError(
                    f"task {task_id!r} {i}단계의 location {loc!r} 이 locations 에 없습니다. "
                    f"사용 가능: {sorted(locations)}"
                )
            # 같은 지시문을 여러 태스크가 공유하는 건 허용하되, 위치가 다르면 경고 대상.
            prompt_owner.setdefault(prompt, task_id)
            steps.append(
                Step(
                    location=loc,
                    prompt=prompt,
                    max_seconds=float(s.get("max_seconds", 120.0)),
                    expect_holding=bool(s.get("expect_holding", False)),
                )
            )

        tasks[task_id] = Task(
            id=task_id,
            name=entry.get("name", task_id),
            steps=tuple(steps),
            aliases=tuple(entry.get("aliases", []) or ()),
        )

    if not tasks:
        raise TaskConfigError("tasks 가 비어 있습니다.")

    return TaskRegistry(locations=locations, tasks=tasks)


if __name__ == "__main__":
    reg = load_registry()
    print(f"위치 {len(reg.locations)}개, 태스크 {len(reg.tasks)}개\n")
    for task in reg.tasks.values():
        print(f"[{task.id}] {task.name}")
        for i, s in enumerate(task.steps, 1):
            hold = "  [끝나면 쥐고 있어야 함]" if s.expect_holding else ""
            print(f"   {i}단계  {reg.location_name(s.location):8s}  {s.prompt!r}  ({s.max_seconds:.0f}초){hold}")
    print(f"\n찍어야 할 학습 라벨 {len(reg.all_prompts())}종:")
    for p in reg.all_prompts():
        print(f'   --dataset.single_task="{p}"')
    missing = reg.placeholder_locations()
    if missing:
        print(f"\n[경고] 좌표가 아직 (0,0,0)인 위치: {missing}")
