#!/usr/bin/env python3
"""사람이 아무렇게나 한 말을 모델이 아는 지시문으로 바꾼다.

SmolVLA 는 학습할 때 본 문장만 제대로 알아듣는다. 그래서 사람이
"파란 거 좀 집어줄래?" 라고 해도 모델에는 학습 때 쓴 문장
"Pick up the blue block" 을 그대로 넣어 줘야 한다. 이 파일이 그 변환을 한다.

LLM 없이 동작한다. 지시 종류가 몇 개뿐일 때는 이쪽이 더 빠르고 확실하다.

단독 실행하면 시험해 볼 수 있다:
    python lang_parser.py                    대화형
    python lang_parser.py "파란거 잡아"        한 번만
    python lang_parser.py --test             내장 시험 전체 실행
"""

import re
import sys
import unicodedata

# ── 지시문 목록 ─────────────────────────────────────────────────────────
#
# task  : 모델에 실제로 넣는 문자열. 학습 때 쓴 것과 "글자 하나까지" 같아야 한다.
# words : 사람이 쓸 법한 표현. 한글·영어·오타·줄임말을 넉넉히 적는다.
# label : 화면에 보여줄 짧은 이름
#
# 새 지시를 추가하려면 여기에 한 덩이를 더 쓰면 된다.

TASKS = [
    {
        "key": "red",
        "label": "빨강",
        "task": "Pick up the red dice and put it in the basket",
        "words": [
            "빨강", "빨간", "빨갛", "빨개", "뻘건", "뻘겅",
            "적색", "붉은", "붉", "레드",
            "red", "crimson", "scarlet",
            "빨간주사위", "빨강주사위",
        ],
    },
    {
        "key": "yellow",
        "label": "노랑",
        "task": "Pick up the yellow dice and put it in the basket",
        "words": [
            "노랑", "노란", "노랗", "노래", "누런", "누렁",
            "황색", "golden", "금색", "옐로",
            "yellow", "gold", "amber",
            "노란주사위", "노랑주사위",
        ],
    },
]

# 부정 표현 — 어느 쪽을 부정하는지가 언어마다 다르다.
#   한국어: "빨간 거 말고"   → 부정어 '앞' 을 부정
#   영어  : "not red"      → 부정어 '뒤' 를 부정
# 한쪽만 봐야 한다. 둘 다 보면 "빨간 거 말고 파란 거" 에서 파랑까지 깎인다.
NEG_BACKWARD = ["말고", "아니고", "아니라", "아니야", "아닌", "빼고", "제외", "대신"]
NEG_FORWARD = ["not", "except", "no"]

# 멈추라는 뜻
STOP_WORDS = ["멈춰", "정지", "스톱", "그만", "stop", "halt", "pause", "wait"]

# 입력에서 지워도 뜻이 안 변하는 말 (조사·어미·군더더기)
FILLER = ["좀", "그", "저", "이거", "그거", "저거", "거를", "것을", "해줄래",
          "해줘", "해봐", "주세요", "please", "can", "you", "the", "a", "an"]


def normalize(text: str) -> str:
    """비교하기 좋게 다듬는다. 한글은 자모를 합치고, 공백·기호를 정리한다."""
    text = unicodedata.normalize("NFC", text).strip().lower()
    text = re.sub(r"[^\w가-힣\s]", " ", text)   # 기호 제거
    text = re.sub(r"\s+", " ", text)
    return text


def _negated_spans(text: str) -> list[tuple[int, int]]:
    """부정어가 걸리는 구간을 찾는다.

    한국어는 "빨간 거 말고" 처럼 부정어가 뒤에 온다. 그래서 부정어 앞쪽
    일정 범위를 '부정된 구간' 으로 본다. 영어는 "not red" 처럼 앞에 오므로
    뒤쪽도 함께 본다.
    """
    spans = []
    for neg in NEG_BACKWARD:
        for m in re.finditer(re.escape(neg), text):
            spans.append((max(0, m.start() - 12), m.start()))
    for neg in NEG_FORWARD:
        for m in re.finditer(r"\b" + re.escape(neg) + r"\b", text):
            spans.append((m.end(), min(len(text), m.end() + 12)))
    return spans


def _in_span(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in spans)


def parse(text: str, tasks: list[dict] | None = None) -> dict:
    """사람의 말을 지시문으로 바꾼다.

    돌려주는 것:
        {"task": 모델에 넣을 문자열 또는 None,
         "key": "red"/"blue"/"stop"/None,
         "label": 화면용 이름,
         "score": 확신 정도,
         "reason": 왜 그렇게 골랐는지}
    """
    tasks = tasks or TASKS
    raw = text
    t = normalize(text)
    if not t:
        return {"task": None, "key": None, "label": "-", "score": 0.0,
                "reason": "입력이 비어 있음"}

    for w in STOP_WORDS:
        if w in t:
            return {"task": None, "key": "stop", "label": "정지", "score": 1.0,
                    "reason": f"정지 표현 '{w}'"}

    neg_spans = _negated_spans(t)
    scores, hits = {}, {}

    for spec in tasks:
        score, found = 0.0, []
        for w in spec["words"]:
            for m in re.finditer(re.escape(w), t):
                if _in_span(m.start(), neg_spans):
                    score -= 1.5          # 부정된 색은 오히려 감점
                    found.append(f"-{w}")
                else:
                    # 긴 단어가 더 확실한 신호다 ("파랑색" > "파")
                    score += 1.0 + 0.1 * len(w)
                    found.append(w)
        scores[spec["key"]] = score
        hits[spec["key"]] = found

    best = max(scores, key=scores.get)
    best_score = scores[best]

    # 모든 색이 감점만 받았다면, 부정되지 않은 쪽을 고른다
    #   "빨간 거 말고"  →  빨강 -1.5, 파랑 0  →  파랑
    if best_score <= 0:
        positives = [k for k, v in scores.items() if v >= 0]
        negatives = [k for k, v in scores.items() if v < 0]
        if negatives and len(positives) == 1:
            best = positives[0]
            spec = next(s for s in tasks if s["key"] == best)
            return {"task": spec["task"], "key": best, "label": spec["label"],
                    "score": 0.6,
                    "reason": f"'{','.join(hits[negatives[0]])}' 를 제외 → {spec['label']}"}
        return {"task": None, "key": None, "label": "-", "score": 0.0,
                "reason": f"'{raw}' 에서 아는 지시를 못 찾음"}

    # 1·2위가 붙어 있으면 애매하다고 알린다
    ordered = sorted(scores.values(), reverse=True)
    margin = best_score - (ordered[1] if len(ordered) > 1 else 0.0)
    spec = next(s for s in tasks if s["key"] == best)
    return {
        "task": spec["task"], "key": best, "label": spec["label"],
        "score": round(min(1.0, best_score / 2.5), 2),
        "reason": ("찾은 말: " + ", ".join(hits[best])
                   + ("" if margin > 0.5 else "  (다른 지시와 비슷해 애매함)")),
    }


# ── 시험 ────────────────────────────────────────────────────────────────

TEST_CASES = [
    # (입력, 기대하는 key)
    ("노란거 잡아", "yellow"),
    ("빨간거 잡아", "red"),
    ("노랑", "yellow"),
    ("빨강", "red"),
    ("노란 블록 집어", "yellow"),
    ("빨간 블록을 집어줘", "red"),
    ("노란색 좀 집어줄래?", "yellow"),
    ("빨간색 물건 가져와", "red"),
    ("yellow", "yellow"),
    ("red", "red"),
    ("pick up the yellow one", "yellow"),
    ("grab red", "red"),
    ("노랑색", "yellow"),
    ("뻘건거", "red"),
    ("누런거 잡아", "yellow"),
    ("노랗게 생긴 거", "yellow"),
    ("붉은 거", "red"),
    ("레드", "red"),
    ("옐로 잡아", "yellow"),
    ("황색 집어", "yellow"),
    ("적색 집어", "red"),
    ("빨간 거 말고 노란 거", "yellow"),
    ("노란 거 말고 빨간 거", "red"),
    ("빨간색 말고", "yellow"),
    ("노란색 말고", "red"),
    ("not red", "yellow"),
    ("멈춰", "stop"),
    ("정지", "stop"),
    ("stop", "stop"),
    ("그만", "stop"),
    ("아무거나", None),
    ("안녕하세요", None),
    ("", None),
]


def run_tests() -> int:
    print(f"{'입력':<28s}{'기대':>8s}{'결과':>8s}   판정   근거")
    print("-" * 92)
    bad = 0
    for text, want in TEST_CASES:
        r = parse(text)
        got = r["key"]
        ok = got == want
        if not ok:
            bad += 1
        print(f"{text or '(빈칸)':<28s}{str(want):>8s}{str(got):>8s}   "
              f"{'OK ' if ok else '★틀림'}   {r['reason'][:40]}")
    print("-" * 92)
    print(f"{len(TEST_CASES) - bad}/{len(TEST_CASES)} 통과"
          + ("" if bad == 0 else f"   ★ {bad}건 실패"))
    return bad


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        sys.exit(1 if run_tests() else 0)
    if len(sys.argv) > 1:
        r = parse(" ".join(sys.argv[1:]))
        print(f"  지시문 : {r['task']}")
        print(f"  해석   : {r['label']}  (확신 {r['score']})")
        print(f"  근거   : {r['reason']}")
        return

    print("아무렇게나 말해 보세요. 빈 줄이면 종료합니다.")
    print("예: 파란거 잡아 / 빨간색 말고 / blue / 멈춰\n")
    while True:
        try:
            line = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break
        r = parse(line)
        if r["key"] == "stop":
            print(f"    → 정지")
        elif r["task"]:
            print(f"    → {r['label']}   \"{r['task']}\"   ({r['reason']})")
        else:
            print(f"    → 모르겠습니다. ({r['reason']})")
    print("종료")


if __name__ == "__main__":
    main()
