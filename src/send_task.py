"""
send_task.py — arm_node.py(제어 소켓 5580)에 지시문을 보내는 채팅식 프로그램

    cd ~/xlerobot
    source ~/lerobot-venv-0.6/bin/activate
    python src/send_task.py

입력:
    r            -> 빨강 지시문 실행 (아래 TASKS)
    y            -> 노랑 지시문 실행
    그 외 문장    -> 그 문장을 그대로 지시문으로 실행
    park         -> 팔 접기
    ping         -> 노드 살아있는지 확인
    q            -> 종료

결과는 results/eval_results.csv 에 한 줄씩 쌓입니다 (평가 기록용).
실행 도중 급히 멈추려면 arm_node 탭에서 Ctrl+C 하세요.
"""

import csv
import json
import os
import pathlib
import time

import zmq

ADDRESS = "tcp://127.0.0.1:5580"
MAX_SECONDS = 180  # 1회 실행 제한 (평가 조건과 같게)

# ⚠️ 학습 데이터의 task 문장과 글자 하나까지 같아야 합니다 (record.sh 에서 확인)
TASKS = {
    "r": "Pick up the red dice and put it in the basket",
    "y": "Pick up the yellow dice and put it in the basket",
}
# 어디서 실행하든 레포의 results/ 에 쌓입니다
LOG = pathlib.Path(__file__).resolve().parent.parent / "results" / "eval_results.csv"


def make_socket(ctx, timeout_ms):
    s = ctx.socket(zmq.REQ)
    s.setsockopt(zmq.RCVTIMEO, timeout_ms)
    s.setsockopt(zmq.LINGER, 0)
    s.connect(ADDRESS)
    return s


def send(ctx, req, timeout_s):
    s = make_socket(ctx, int(timeout_s * 1000))
    try:
        s.send_string(json.dumps(req, ensure_ascii=False))
        return json.loads(s.recv_string())
    except zmq.Again:
        return {"status": "failed", "message": f"{timeout_s:.0f}초 동안 응답 없음"}
    finally:
        s.close()


def log_result(task, reply, elapsed):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "task", "status", "seconds", "message"])
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), task, reply.get("status"),
                    f"{elapsed:.1f}", reply.get("message")])


def main():
    ctx = zmq.Context()
    print(send(ctx, {"cmd": "ping"}, 5))
    print("지시문 입력 (r=빨강, y=노랑, park, ping, q=종료)")

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line == "q":
            break
        if line in ("ping", "park"):
            print(send(ctx, {"cmd": line}, 30))
            continue

        task = TASKS.get(line, line)
        print(f"실행: {task!r} (최대 {MAX_SECONDS}초) ...")
        t0 = time.time()
        reply = send(ctx, {"cmd": "run", "task": task, "max_seconds": MAX_SECONDS},
                     MAX_SECONDS + 30)
        elapsed = time.time() - t0
        print(f"결과: {reply.get('status')} — {reply.get('message')} ({elapsed:.1f}초)")
        log_result(task, reply, elapsed)

    ctx.term()


if __name__ == "__main__":
    main()
