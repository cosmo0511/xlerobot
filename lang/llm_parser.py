#!/usr/bin/env python3
"""LLM 을 얹어 더 자유로운 말을 알아듣는다.

lang_parser.py 는 미리 적어 둔 단어만 안다. 이 파일은 그 위에 작은 언어모델을
올려서, 목록에 없는 표현과 여러 동작이 섞인 명령까지 다룬다.

중요 — LLM 이 늘려주는 것은 "말을 알아듣는 범위" 뿐이다.
로봇은 여전히 학습한 동작만 할 수 있다. 학습 안 한 일을 시키면
이 파일은 "못 한다" 고 분명히 알려준다. 조용히 틀린 동작을 하는 것보다 낫다.

동작 방식 (2단계)
    1. 키워드로 먼저 본다 — "파란거 잡아" 같은 흔한 말은 0초에 끝난다
    2. 애매하면 LLM 에게 묻는다 — 모델이 없으면 여기서 솔직히 모른다고 한다

    python llm_parser.py --test            모델 없이 되는 범위까지 시험
    python llm_parser.py "빨간거 집어서 상자에 넣어"
    python llm_parser.py --download        모델 받기 (약 3GB, 한 번만)
"""

import argparse
import json
import os
import re
import sys

from lang_parser import TASKS, parse as keyword_parse

# 모델이 커지면 GPU 가 모자란다. SmolVLA 와 같이 올리는 걸 전제로 작은 걸 쓴다.
DEFAULT_MODEL = os.environ.get("LANG_LLM", "Qwen/Qwen2.5-1.5B-Instruct")

C = {"r": "\033[0m", "b": "\033[1m", "dim": "\033[2m", "ok": "\033[32m",
     "w": "\033[33m", "no": "\033[31m", "hi": "\033[36m"}
if not sys.stdout.isatty():
    C = dict.fromkeys(C, "")


# ── 로봇이 할 줄 아는 일 ────────────────────────────────────────────────
#
# LLM 에게 "이 중에서만 골라라" 고 알려줄 목록. 여기 없는 건 못 하는 일이다.

def skill_list():
    return [{"key": s["key"], "label": s["label"], "task": s["task"]} for s in TASKS]


SYSTEM_PROMPT = """You translate a user's casual request into robot skills.

The robot can ONLY do these skills:
{skills}

Rules:
- Reply with JSON only. No explanation outside JSON.
- "plan": list of skill keys in order. Empty list if nothing matches.
- "say": one short Korean sentence telling the user what will happen,
  or why it cannot be done.
- If the user asks for something not in the skill list (e.g. a color or object
  the robot never learned), return an empty plan and say so plainly in "say".
- If the request contains several steps, put each step in "plan" in order.
- Never invent a skill key that is not in the list.

Example:
  user: 빨간거 집어
  {{"plan": ["red"], "say": "빨간 블록을 집겠습니다."}}

  user: 초록색 집어
  {{"plan": [], "say": "초록은 학습되지 않았습니다. 빨강·파랑만 가능합니다."}}
"""


class LLMInterpreter:
    """작은 언어모델로 자유로운 말을 기술 목록에 맞춘다."""

    def __init__(self, model_id=DEFAULT_MODEL, device="cuda", load_in_8bit=True):
        self.model_id = model_id
        self.device = device
        self.load_in_8bit = load_in_8bit
        self.ok = False
        self.error = ""
        self.tok = None
        self.model = None

    def load(self):
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as e:
            self.error = f"transformers 가 없습니다: {e}"
            return False
        try:
            # local_files_only=True → 인터넷 없이, 이미 받아 둔 것만 쓴다
            self.tok = AutoTokenizer.from_pretrained(self.model_id, local_files_only=True)
            kw = {"local_files_only": True, "dtype": torch.float16}
            if self.device == "cuda" and self.load_in_8bit:
                try:
                    import bitsandbytes  # noqa: F401
                    kw = {"local_files_only": True, "load_in_8bit": True}
                except ImportError:
                    pass  # 8bit 가 안 되면 fp16 으로 간다
            self.model = AutoModelForCausalLM.from_pretrained(self.model_id, **kw)
            if "load_in_8bit" not in kw:
                self.model.to(self.device)
            self.model.eval()
            self.ok = True
            return True
        except Exception as e:
            self.error = str(e).split("\n")[0][:160]
            return False

    def ask(self, text: str, max_new_tokens: int = 120) -> dict | None:
        if not self.ok:
            return None
        import torch
        skills = "\n".join(f'  - key "{s["key"]}" : {s["task"]}  ({s["label"]})'
                           for s in skill_list())
        msgs = [
            {"role": "system", "content": SYSTEM_PROMPT.format(skills=skills)},
            {"role": "user", "content": text},
        ]
        prompt = self.tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        ids = self.tok(prompt, return_tensors="pt").to(self.model.device)
        with torch.inference_mode():
            out = self.model.generate(**ids, max_new_tokens=max_new_tokens,
                                      do_sample=False,
                                      pad_token_id=self.tok.eos_token_id)
        reply = self.tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
        return self._extract(reply)

    @staticmethod
    def _extract(reply: str) -> dict | None:
        """모델이 JSON 외에 군더더기를 붙여도 건져낸다."""
        m = re.search(r"\{.*\}", reply, re.S)
        if not m:
            return None
        try:
            d = json.loads(m.group(0))
        except Exception:
            return None
        valid = {s["key"] for s in skill_list()}
        plan = [k for k in d.get("plan", []) if k in valid]   # 없는 기술은 버린다
        return {"plan": plan, "say": str(d.get("say", "")).strip()}


# ── 두 단계 해석 ────────────────────────────────────────────────────────

_llm: LLMInterpreter | None = None


def get_llm(device="cuda") -> LLMInterpreter:
    global _llm
    if _llm is None:
        _llm = LLMInterpreter(device=device)
        _llm.load()
    return _llm


def interpret(text: str, use_llm: bool = True, device: str = "cuda") -> dict:
    """사람의 말을 '할 일 목록' 으로 바꾼다.

    돌려주는 것:
        plan   : 실행할 기술 key 목록. 빈 목록이면 할 수 있는 게 없다는 뜻
        say    : 사용자에게 보여줄 한 줄
        source : "keyword" / "llm" / "none"
        detail : 근거
    """
    # 1단계 — 키워드. 흔한 말은 여기서 즉시 끝난다.
    k = keyword_parse(text)
    if k["key"] == "stop":
        return {"plan": [], "say": "정지합니다.", "source": "keyword",
                "detail": k["reason"], "stop": True}
    # 키워드가 확실히 하나를 집어냈으면 그대로 쓴다. 점수 자체보다
    # "애매함" 표시가 없는지를 본다 — 단어 하나만 맞아도 0.48 쯤 나오므로
    # 숫자 문턱으로 자르면 멀쩡한 매치가 전부 걸러진다.
    if k["task"] and "애매" not in k["reason"]:
        return {"plan": [k["key"]], "say": f"{k['label']} 블록을 집겠습니다.",
                "source": "keyword", "detail": k["reason"], "stop": False}

    # 2단계 — LLM. 목록에 없는 표현, 여러 단계가 섞인 명령.
    if use_llm:
        llm = get_llm(device)
        if llm.ok:
            r = llm.ask(text)
            if r is not None:
                labels = {s["key"]: s["label"] for s in TASKS}
                return {
                    "plan": r["plan"],
                    "say": r["say"] or ("할 수 있는 일이 없습니다."
                                        if not r["plan"] else
                                        " → ".join(labels[k] for k in r["plan"])),
                    "source": "llm", "detail": "LLM 해석", "stop": False,
                }
        else:
            return {"plan": [], "source": "none", "stop": False,
                    "say": "알아듣지 못했습니다.",
                    "detail": f"LLM 미탑재 ({llm.error or '모델 없음'})"}

    return {"plan": [], "say": "알아듣지 못했습니다.", "source": "none",
            "detail": k["reason"], "stop": False}


# ── 모델 내려받기 ───────────────────────────────────────────────────────

def download(model_id=DEFAULT_MODEL):
    print(f"  모델을 내려받습니다: {model_id}")
    print(f"  {C['dim']}약 3GB. 인터넷이 필요하고 한 번만 받으면 됩니다.{C['r']}")
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
        AutoTokenizer.from_pretrained(model_id)
        AutoModelForCausalLM.from_pretrained(model_id)
        print(f"  {C['ok']}완료{C['r']}")
        return 0
    except Exception as e:
        print(f"  {C['no']}실패: {e}{C['r']}")
        return 1


# ── 시험 ────────────────────────────────────────────────────────────────

TEST = [
    ("파란거 잡아", ["blue"], "keyword"),
    ("빨간거", ["red"], "keyword"),
    ("빨간 거 말고 파란 거", ["blue"], "keyword"),
    ("멈춰", [], "keyword"),
    # 아래는 LLM 이 있어야 제대로 된다
    ("진홍색 물건 집어", ["red"], "llm"),
    ("빨간거 집고 파란거도", ["red", "blue"], "llm"),
    ("초록색 집어", [], "llm"),
]


def run_tests(use_llm: bool):
    llm = get_llm() if use_llm else None
    have = bool(llm and llm.ok)
    print(f"  LLM: {C['ok'] + '탑재됨' if have else C['w'] + '없음 — 키워드만 시험'}{C['r']}")
    if not have and llm:
        print(f"  {C['dim']}{llm.error}{C['r']}")
    print()
    print(f"  {'입력':<26s}{'기대':>16s}{'결과':>16s}{'경로':>9s}  판정")
    print("  " + "-" * 78)
    bad = 0
    for text, want, need in TEST:
        if need == "llm" and not have:
            print(f"  {text:<26s}{str(want):>16s}{'(건너뜀)':>16s}{'-':>9s}  {C['dim']}LLM 필요{C['r']}")
            continue
        r = interpret(text, use_llm=use_llm)
        got = r["plan"]
        ok = got == want
        bad += (not ok)
        print(f"  {text:<26s}{str(want):>16s}{str(got):>16s}{r['source']:>9s}  "
              f"{'OK' if ok else C['no'] + '★' + C['r']}")
    print("  " + "-" * 78)
    return bad


def main():
    p = argparse.ArgumentParser(description="LLM 지시 해석기")
    p.add_argument("text", nargs="*")
    p.add_argument("--test", action="store_true")
    p.add_argument("--download", action="store_true")
    p.add_argument("--no-llm", action="store_true", help="키워드만 쓴다")
    p.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    a = p.parse_args()

    if a.download:
        sys.exit(download())
    if a.test:
        sys.exit(1 if run_tests(not a.no_llm) else 0)

    if a.text:
        r = interpret(" ".join(a.text), use_llm=not a.no_llm, device=a.device)
        labels = {s["key"]: s["label"] for s in TASKS}
        print(f"  할 일 : {[labels[k] for k in r['plan']] or '없음'}")
        print(f"  안내  : {r['say']}")
        print(f"  경로  : {r['source']}   {C['dim']}{r['detail']}{C['r']}")
        return

    print("아무렇게나 말해 보세요. 빈 줄이면 종료합니다.\n")
    labels = {s["key"]: s["label"] for s in TASKS}
    while True:
        try:
            line = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break
        r = interpret(line, use_llm=not a.no_llm, device=a.device)
        plan = " → ".join(labels[k] for k in r["plan"]) or "-"
        print(f"    할 일: {plan}")
        print(f"    {r['say']}   {C['dim']}({r['source']}){C['r']}")
    print("종료")


if __name__ == "__main__":
    main()
