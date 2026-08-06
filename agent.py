"""
LLM agent routing layer for XLeRobot -- Gemini-backed parsing.

The routing/safety skeleton is:

    parse(command)  ->  navigate_to(desk_id)  ->  run_policy(exact_task_prompt)

_parse_command() asks Gemini to classify the command, with the output CONSTRAINED
to the exact task_prompt labels via a response schema. The model literally cannot
emit a string that isn't a valid training label -- it can only pick one, say
"ambiguous", or say "unknown". desk_id is then derived in code (single source of
truth), never trusted from the model.

Requires:  pip install google-genai pydantic
Env:       GEMINI_API_KEY
Assumes navigate_to() and run_policy() are provided by the host system
(navigation.py and policy_client.py).
"""

import os
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel
from google import genai
from google.genai import types

# Real tools from the rest of the system. During standalone testing (the
# __main__ block below) these are shadowed by local dummies.
try:
    from navigation import navigate_to
    from policy_client import run_policy
except ImportError:
    # navigation.py / policy_client.py not present yet -- the __main__ demo
    # defines its own dummies, so this is fine for isolated testing.
    navigate_to = None
    run_policy = None


# --- Task map (single source of truth) ---------------------------------------
# The exact task_prompt strings, and which desk each one lives on. desk_id is
# looked up here from the model's chosen task_prompt -- so even if the model
# were wrong about location, we can't send a task to the wrong desk.
DESK_OF_TASK = {
    "Water the plant":                "desk_1",
    "Give nutrients to the plant":    "desk_1",
    "Fold the towel and put it away": "desk_2",
    "Sweep with the dustpan":         "desk_2",
    "Sort the recycling":             "desk_3",
}


# --- Constrained output schema -----------------------------------------------
# TaskPrompt is an enum of ONLY the valid labels. Because the Gemini response
# schema uses this enum, the model's task_prompt field can only ever be one of
# these five exact strings -- no paraphrasing, no hallucinated labels.
class TaskPrompt(str, Enum):
    WATER = "Water the plant"
    NUTRIENTS = "Give nutrients to the plant"
    FOLD = "Fold the towel and put it away"
    SWEEP = "Sweep with the dustpan"
    RECYCLE = "Sort the recycling"


class Decision(BaseModel):
    # "route": one clear task. "ambiguous": plausibly >1 task -> ask. "unknown": no match.
    kind: Literal["route", "ambiguous", "unknown"]
    task_prompt: Optional[TaskPrompt] = None      # set when kind == "route"
    options: Optional[List[TaskPrompt]] = None    # set when kind == "ambiguous"
    reason: Optional[str] = None                  # clarifying question / why unknown


SYSTEM_PROMPT = """\
You route a robot command to exactly one manipulation task. The command may be
casual English or Korean. Available tasks (use these EXACT strings, never reword):
  desk_1: "Water the plant", "Give nutrients to the plant"
  desk_2: "Fold the towel and put it away", "Sweep with the dustpan"
  desk_3: "Sort the recycling"

Rules:
- If the command clearly indicates ONE task, return kind="route" with that task_prompt.
- If it points at a thing but not a specific task (e.g. mentions the plant but not
  whether to water it or give nutrients), return kind="ambiguous" with the candidate
  tasks in options and a short clarifying question in reason. Do NOT guess.
- If it matches no available task, return kind="unknown" with a brief reason.
- Only ever use the exact task strings listed above.
"""
os.environ["GEMINI_API_KEY"] = "AQ.Ab8RN6KBW83-ObutkyCtWjFIL555AY2P2kO_eMdlrR5n8ZznpA"
# Reuse one client across calls.
_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Flash-Lite is the recommended tier for classification/routing: cheapest model,
# and routing doesn't need a big brain. Model identifiers change over time -- if
# this errors, list available models and update the string (Google also exposes
# rolling aliases like "gemini-flash-lite-latest").
_MODEL = "gemini-3.1-flash-lite"


def _parse_command(user_command: str) -> Decision:
    """Ask Gemini to classify the command into a Decision (schema-constrained)."""
    resp = _client.models.generate_content(
        model=_MODEL,
        contents=user_command,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=Decision,
            temperature=0,  # deterministic routing
            # Turn thinking OFF: this is a trivial classify-into-5-labels task,
            # and thinking tokens bill at the (higher) output rate. Keeps cost and
            # latency minimal. If a model rejects budget=0, use a small value.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    # SDK parses the JSON into our Pydantic model when response_schema is set.
    decision = resp.parsed
    if decision is None:  # extremely defensive: treat unparseable output as unknown
        return Decision(kind="unknown", reason="Could not parse the command.")
    return decision


# --- Main entry point --------------------------------------------------------
def handle_command(user_command: str) -> dict:
    """Route a natural-language command to navigate_to() then run_policy()."""
    # 1. Parse (via Gemini).
    try:
        decision = _parse_command(user_command)
    except Exception as e:
        # Network/API failure -> fail safe, don't move the robot.
        return {"status": "parse_error", "message": f"LLM parse failed: {e}"}

    if decision.kind == "unknown":
        return {"status": "unknown",
                "message": decision.reason or "Couldn't map that to a known task."}

    if decision.kind == "ambiguous":
        opts = [o.value for o in (decision.options or [])]
        return {"status": "needs_clarification",
                "message": decision.reason or "Which task did you mean?",
                "options": opts}

    # kind == "route"
    task_prompt = decision.task_prompt.value
    desk_id = DESK_OF_TASK[task_prompt]  # derive location in code, not from the model

    # 2. Navigate FIRST and check the result.
    nav = navigate_to(desk_id)
    if nav.get("status") != "arrived":
        # failed / blocked -> report and DO NOT run the policy.
        return {"status": "nav_failed",
                "desk_id": desk_id,
                "message": (f'Navigation to {desk_id} '
                            f'{nav.get("status", "failed")}: '
                            f'{nav.get("message", "")}').strip()}

    # 3. Only after "arrived": run the manipulation policy.
    result = run_policy(task_prompt)
    if result.get("status") != "done":
        return {"status": "policy_failed",
                "desk_id": desk_id,
                "task_prompt": task_prompt,
                "message": f'Policy failed: {result.get("message", "")}'.strip()}

    # 4. Success.
    return {"status": "done",
            "desk_id": desk_id,
            "task_prompt": task_prompt,
            "message": f'Completed "{task_prompt}" at {desk_id}.'}


# --- Standalone demo (uses local dummies for navigate_to / run_policy) --------
if __name__ == "__main__":
    def navigate_to(desk_id):
        print(f"  [nav] going to {desk_id} ...")
        return {"status": "arrived", "desk_id": desk_id, "message": "ok"}

    def run_policy(task_prompt):
        print(f"  [policy] running: {task_prompt!r}")
        return {"status": "done", "message": "ok"}

    for cmd in ["식물에 물 좀 줘", "do something with the plant", "make me a sandwich"]:
        print(f"\nUSER: {cmd}")
        print("RESULT:", handle_command(cmd))
