"""
agent.py — 사람의 말을 태스크 하나로 라우팅하고, 그 태스크의 단계들을 순서대로 실행.

    "장난감 옮겨줘"
        -> LLM 분류 -> task id = "toy_transfer"
        -> 단계 목록을 코드에서 조회 (LLM 출력을 위치 결정에 쓰지 않음)
        -> [팔 접기] → 1번 책상 이동 → "Pick up the toy from the desk"
           [팔 접기(물건 든 채)] → 2번 책상 이동 → "Place the toy on the desk"

■ 설계 원칙
---------------------------------------------------------------------------
1. **API 키는 환경변수로만.** 소스에 쓰지 않습니다.
2. **태스크 목록은 config 에서.** LLM 응답 스키마를 런타임에 생성하므로,
   태스크를 늘리든 줄이든 이 파일은 안 건드립니다.
3. **위치는 코드가 결정.** LLM 이 장소를 말해도 무시합니다.
   LLM 이 틀려도 엉뚱한 방으로 가는 일은 구조적으로 불가능해야 하니까요.
4. **단계 하나라도 실패하면 즉시 중단.** 물건을 못 집었는데 놓으러 가지 않습니다.

필요 패키지: pip install google-genai pyyaml
환경변수:    export GEMINI_API_KEY="..."
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

from task_registry import TaskRegistry

logger = logging.getLogger(__name__)


@dataclass
class Decision:
    kind: str  # "route" | "ambiguous" | "unknown"
    task_id: str | None = None
    options: list[str] | None = None
    reason: str | None = None


SYSTEM_PROMPT_TEMPLATE = """\
You route a robot command to exactly one task id.
The command may be casual Korean or English.

Available tasks (return the id string on the left, never reword it):
{task_list}

Rules:
- If the command clearly indicates ONE task, return kind="route" with that task_id.
- If it plausibly matches more than one, return kind="ambiguous", put the candidate ids
  in `options`, and put a short clarifying question in Korean in `reason`. Do NOT guess.
- If it matches no available task, return kind="unknown" with a brief Korean reason.
- Only ever use the exact task ids listed above.
"""


class CommandParser:
    """Gemini 로 자연어 명령을 태스크 하나로 분류합니다.

    응답 스키마에 태스크 id enum 을 박아서, 모델이 **없는 태스크를 물리적으로 뱉을 수
    없게** 만듭니다. 이게 이 계층의 핵심 안전장치입니다.
    """

    def __init__(self, registry: TaskRegistry, agent_cfg: dict | None = None):
        from google import genai

        agent_cfg = agent_cfg or {}
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "환경변수 GEMINI_API_KEY 가 설정돼 있지 않습니다.\n"
                '  export GEMINI_API_KEY="your-key-here"\n'
                "※ 소스코드에 키를 직접 쓰지 마세요."
            )

        self.registry = registry
        self.model = agent_cfg.get("model", "gemini-flash-lite-latest")
        self._client = genai.Client(api_key=api_key)
        self._system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            task_list=registry.describe_for_llm()
        )
        self._schema = self._build_schema(registry.task_ids)

    @staticmethod
    def _build_schema(task_ids: list[str]) -> dict:
        task_enum = {"type": "STRING", "enum": list(task_ids)}
        return {
            "type": "OBJECT",
            "properties": {
                "kind": {"type": "STRING", "enum": ["route", "ambiguous", "unknown"]},
                "task_id": task_enum,
                "options": {"type": "ARRAY", "items": task_enum},
                "reason": {"type": "STRING"},
            },
            "required": ["kind"],
        }

    def parse(self, user_command: str) -> Decision:
        import json

        from google.genai import types

        resp = self._client.models.generate_content(
            model=self.model,
            contents=user_command,
            config=types.GenerateContentConfig(
                system_instruction=self._system_prompt,
                response_mime_type="application/json",
                response_schema=self._schema,
                temperature=0,
                # 몇 개 중 하나 고르는 분류에 사고 토큰은 낭비입니다. 지연시간도 늘어납니다.
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )

        try:
            data = json.loads(resp.text)
        except (json.JSONDecodeError, TypeError):
            return Decision(kind="unknown", reason="명령을 해석하지 못했습니다.")

        task_id = data.get("task_id")
        # 스키마가 막아주긴 하지만 한 번 더 확인합니다.
        if task_id is not None and task_id not in self.registry.tasks:
            logger.error("스키마를 벗어난 task id 가 반환됨: %r", task_id)
            return Decision(kind="unknown", reason="알 수 없는 태스크입니다.")

        return Decision(
            kind=data.get("kind", "unknown"),
            task_id=task_id,
            options=data.get("options"),
            reason=data.get("reason"),
        )


class KeywordParser:
    """LLM 없이 aliases 로만 매칭하는 대체 파서.

    API 키가 없거나 네트워크가 안 될 때(심사장 WiFi!) 데모가 아예 안 되는 걸 막습니다.
    정확도는 떨어지지만 미리 정한 표현은 확실히 동작합니다.
    """

    def __init__(self, registry: TaskRegistry):
        self.registry = registry

    @staticmethod
    def _norm(s: str) -> str:
        """공백을 전부 제거해서 비교합니다. '물 좀 줘' 처럼 조사가 끼어도 걸리게."""
        return "".join(s.lower().split())

    def parse(self, user_command: str) -> Decision:
        text = self._norm(user_command)
        hits = [
            t.id
            for t in self.registry.tasks.values()
            if self._norm(t.name) in text
            or any(self._norm(a) in text for a in t.aliases)
        ]
        if not hits:
            return Decision(kind="unknown",
                            reason="아는 표현이 없습니다. tasks.yaml 의 aliases 를 참고하세요.")
        if len(hits) > 1:
            return Decision(kind="ambiguous", options=hits, reason="어느 쪽인가요?")
        return Decision(kind="route", task_id=hits[0])


class Agent:
    """파서 + 자율주행 + 정책을 묶어 한 명령을 끝까지 처리합니다."""

    def __init__(
        self,
        registry: TaskRegistry,
        parser: Any,
        navigate_to: Callable[[str], dict],
        run_policy: Callable[..., dict],
        park_arms: Callable[..., dict] | None = None,
    ):
        self.registry = registry
        self.parser = parser
        self.navigate_to = navigate_to
        self.run_policy = run_policy
        # 이동 전에 팔을 접는 콜백. Pi 가 둘이라 주행과 조작이 하드웨어적으로
        # 충돌하지는 않지만, 팔이 벌어진 채로 이동하면 문틀·가구에 부딪힙니다.
        self.park_arms = park_arms

    def handle_command(self, user_command: str) -> dict[str, Any]:
        # 1. 해석
        try:
            decision = self.parser.parse(user_command)
        except Exception as e:
            # 해석 실패 시 로봇은 절대 움직이지 않습니다.
            return {"status": "parse_error", "message": f"명령 해석 실패: {e}"}

        if decision.kind == "unknown":
            return {"status": "unknown",
                    "message": decision.reason or "아는 태스크가 아닙니다."}

        if decision.kind == "ambiguous":
            names = [self.registry.tasks[o].name for o in (decision.options or [])
                     if o in self.registry.tasks]
            return {"status": "needs_clarification",
                    "message": decision.reason or "어느 태스크인가요?",
                    "options": names}

        if not decision.task_id:
            return {"status": "unknown", "message": "태스크를 특정하지 못했습니다."}

        return self.run_task(decision.task_id)

    def run_task(self, task_id: str) -> dict[str, Any]:
        """태스크의 단계들을 순서대로 실행합니다."""
        task = self.registry.tasks[task_id]
        done_steps: list[str] = []

        for i, step in enumerate(task.steps):
            # 첫 단계 전에는 그리퍼를 자유롭게 접고,
            # 단계 사이에는 **그리퍼를 유지한 채로** 접습니다.
            # 안 그러면 1단계에서 집은 물건을 이동 직전에 떨어뜨립니다.
            carrying = i > 0
            if self.park_arms is not None:
                park = self.park_arms(hold_gripper=carrying)
                if park.get("status") != "done":
                    return self._fail("park_failed", task, i, done_steps,
                                      f"팔 파킹 실패: {park.get('message', '')}")

            # 이동 -> arrived 일 때만 조작
            nav = self.navigate_to(step.location)
            if nav.get("status") != "arrived":
                return self._fail("nav_failed", task, i, done_steps,
                                  f"이동 실패({nav.get('status')}): {nav.get('message', '')}")

            # 조작. expect_holding=True 면 팔 노드가 끝나고 그리퍼를 확인해서,
            # 아무것도 못 잡았으면 failed 를 돌려줍니다.
            result = self.run_policy(
                step.prompt,
                max_seconds=step.max_seconds,
                expect_holding=step.expect_holding,
            )
            if result.get("status") != "done":
                return self._fail("policy_failed", task, i, done_steps,
                                  f"조작 실패: {result.get('message', '')}")

            done_steps.append(step.prompt)

        # 마지막에 팔을 원위치 (그리퍼도 열림)
        if self.park_arms is not None:
            self.park_arms(hold_gripper=False)

        return {"status": "done",
                "task_id": task.id,
                "steps_done": done_steps,
                "message": f"{task.name} 완료 ({len(done_steps)}단계)"}

    def _fail(self, status: str, task, step_index: int,
              done_steps: list[str], message: str) -> dict[str, Any]:
        """단계 중간에 실패했을 때. 어디까지 갔는지 남깁니다.

        중간 실패는 물건을 든 채로 멈추는 상황이 될 수 있어서, 사람이 상태를
        알아야 합니다. 그래서 몇 단계까지 됐는지 반환에 포함합니다.
        """
        step = task.steps[step_index]
        where = self.registry.location_name(step.location)
        return {"status": status,
                "task_id": task.id,
                "failed_at_step": step_index + 1,
                "total_steps": len(task.steps),
                "location_id": step.location,
                "steps_done": done_steps,
                "message": (f"{task.name} {step_index + 1}/{len(task.steps)}단계"
                            f"({where}) 에서 중단 — {message}").strip()}
