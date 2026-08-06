"""
policy_client.py — SmolVLA 정책 서버에 요청을 보내는 클라이언트.

에이전트(agent.py)가 run_policy(task_prompt)를 호출하면, 이 파일이
카메라 이미지 + 지시문을 GPU 서버로 보내고, 받은 행동을 로봇 팔에 실행한다.

현재는 더미(dummy) 상태 — 출력만 하고 실제 통신/제어는 안 함.
SmolVLA 서버가 준비되면 아래 run_policy 내부를 실제 통신 코드로 교체할 것.
입력/출력 규격은 INTERFACE.md 참고.
"""


def run_policy(task_prompt: str) -> dict:
    """
    TODO(SmolVLA 담당): 실제 정책 서버 호출로 교체.

    입력:
        task_prompt — 아래 5개 문자열 중 정확히 하나 (학습 라벨과 글자까지 동일)
            "Water the plant"
            "Give nutrients to the plant"
            "Fold the towel and put it away"
            "Sweep with the dustpan"
            "Sort the recycling"
    출력:
        {"status": "done"|"failed", "message": str}
    """
    print(f"[더미-POLICY] 실행: '{task_prompt}'")
    return {"status": "done", "message": "dummy"}
