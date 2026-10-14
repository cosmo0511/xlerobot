# tools — 점검과 수동 조작

| 파일 | 하는 일 | 어디서 |
|---|---|---|
| `base_wasd.py` | 베이스 수동 조작. WASD 이동 / QE 회전 / ZX 속도(10단계) | 💻 PC |
| `cam_stream.py` | 카메라를 브라우저로 중계 (MJPEG, 포트 8090) | 🍓 파이 |
| `robot_check.py` | WiFi 세기·대역폭·지연, 서보 전원, USB 대역폭 점검 | 어디서나 |

```bash
python tools/base_wasd.py --remote-ip=xlerobot2.local --robot-id=bi_so101

# 파이에서 — 호스트를 먼저 꺼야 카메라가 열립니다
python tools/cam_stream.py cam_top          # 그 뒤 http://<파이>:8090
```

`robot_check.py` 는 의존성이 없으면 그 항목만 건너뛰고 나머지를 보고합니다.
다른 PC 에 복사해서 그대로 실행할 수 있습니다.
