#!/usr/bin/env python3
"""카메라를 브라우저로 실시간 중계한다. (라즈베리파이에서 실행)

MJPEG 로 내보내므로 브라우저만 있으면 보인다. 추가 설치가 필요 없다.

    ~/venv/lerobot_0.6/bin/python ~/cam_stream.py                # cam_top
    ~/venv/lerobot_0.6/bin/python ~/cam_stream.py cam_left       # 다른 카메라
    ~/venv/lerobot_0.6/bin/python ~/cam_stream.py cam_top,cam_left   # 여러 대

그다음 PC 브라우저에서:
    http://<파이주소>:8090

주의
    * host (bi_so_base_host) 가 카메라를 잡고 있으면 먼저 끌 것.
    * 같은 공유기 안에서만 접속된다 (외부 공개 아님).
"""

import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

PORT = int(os.environ.get("CAM_PORT", "8090"))
WIDTH = int(os.environ.get("CAM_WIDTH", "640"))
HEIGHT = int(os.environ.get("CAM_HEIGHT", "480"))
FPS = int(os.environ.get("CAM_FPS", "30"))
QUALITY = int(os.environ.get("CAM_QUALITY", "80"))

names = (sys.argv[1] if len(sys.argv) > 1 else "cam_top").split(",")


class Camera:
    """카메라 한 대를 백그라운드에서 계속 읽어 최신 프레임만 보관한다.

    브라우저가 여러 개 붙어도 카메라는 한 번만 열린다.
    """

    def __init__(self, name):
        # 장치 경로와 URL 용 이름을 분리한다. "/dev/video6" 를 그대로 이름으로
        # 쓰면 /stream//dev/video6 가 되어 주소가 깨진다.
        self.path = name if name.startswith("/dev/") else f"/dev/{name}"
        self.name = self.path.rsplit("/", 1)[-1]
        self.frame = None
        self.count = 0
        self.fps = 0.0
        self.alive = False
        self.error = ""
        self.lock = threading.Lock()

    def start(self):
        cap = cv2.VideoCapture(self.path, cv2.CAP_V4L2)
        if not cap.isOpened():
            self.error = "열 수 없음 (다른 프로그램이 쓰고 있거나 장치가 없음)"
            print(f"  {self.name:<16s} {self.error}")
            return False
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, FPS)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.alive = True
        print(f"  {self.name:<16s} {self.path}  열림")
        threading.Thread(target=self._loop, args=(cap,), daemon=True).start()
        return True

    def _loop(self, cap):
        t0, n = time.time(), 0
        while self.alive:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            ok, buf = cv2.imencode(".jpg", frame,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), QUALITY])
            if ok:
                with self.lock:
                    self.frame = buf.tobytes()
                    self.count += 1
            n += 1
            if n >= 30:  # 30장마다 실제 fps 를 갱신한다
                now = time.time()
                self.fps, t0, n = n / (now - t0), now, 0
        cap.release()

    def get(self):
        with self.lock:
            return self.frame


cams = {}

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>카메라</title><style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#11151c;color:#e6ecf5;font-family:"Noto Sans CJK KR",sans-serif;padding:20px}}
h1{{font-size:17px;font-weight:700;margin-bottom:4px}}
.sub{{font-size:12px;color:#7d8aa0;margin-bottom:18px}}
.grid{{display:flex;flex-wrap:wrap;gap:18px}}
.cam{{background:#1a2030;border-radius:8px;padding:12px;}}
.hd{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px}}
.nm{{font-size:14px;font-weight:700;color:#4ecdc4}}
.st{{font-size:11px;color:#7d8aa0;font-variant-numeric:tabular-nums}}
img{{display:block;border-radius:4px;background:#000;max-width:100%}}
.err{{color:#ff6b6b;font-size:13px;padding:30px 10px}}
</style></head><body>
<h1>XLeRobot 카메라</h1>
<div class="sub">{res} · 품질 {q} · 새로고침하면 다시 연결됩니다</div>
<div class="grid">{cards}</div>
<script>
setInterval(async () => {{
  try {{
    const r = await fetch('/stat'); const j = await r.json();
    for (const k in j) {{
      const el = document.getElementById('st-' + k);
      if (el) el.textContent = j[k].fps.toFixed(1) + ' fps · ' + j[k].count + '장';
    }}
  }} catch (e) {{}}
}}, 1000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass  # 접속 로그로 화면이 지저분해지지 않게

    def do_GET(self):
        if self.path == "/":
            cards = []
            for name, cam in cams.items():
                if cam.error:
                    inner = f"<div class='err'>{cam.error}</div>"
                else:
                    inner = f"<img src='/stream/{name}' width='{WIDTH}' height='{HEIGHT}'>"
                cards.append(
                    f"<div class='cam'><div class='hd'><span class='nm'>{name}</span>"
                    f"<span class='st' id='st-{name}'>연결 중…</span></div>{inner}</div>")
            body = PAGE.format(res=f"{WIDTH}×{HEIGHT}", q=QUALITY,
                               cards="".join(cards)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/stat":
            import json
            body = json.dumps({n: {"fps": c.fps, "count": c.count}
                               for n, c in cams.items()}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path.startswith("/stream/"):
            name = self.path[len("/stream/"):]
            cam = cams.get(name)
            if cam is None or cam.error:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last = -1
            try:
                while True:
                    if cam.count == last:  # 새 프레임이 없으면 기다린다
                        time.sleep(0.005)
                        continue
                    last = cam.count
                    data = cam.get()
                    if not data:
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                     + f"Content-Length: {len(data)}\r\n\r\n".encode()
                                     + data + b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass  # 브라우저 탭을 닫은 것
        else:
            self.send_error(404)


def my_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return socket.gethostbyname(socket.gethostname())
    finally:
        s.close()


def main():
    print(f"카메라 여는 중  ({WIDTH}x{HEIGHT} MJPG, 품질 {QUALITY})")
    for name in names:
        cam = Camera(name.strip())
        cam.start()
        cams[cam.name] = cam
    if not any(c.alive for c in cams.values()):
        print("\n열린 카메라가 없습니다. host 가 쓰고 있지 않은지 확인하세요:")
        print('  pkill -f "[b]i_so_base_host"')
        return

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    print(f"\n  PC 브라우저에서 열어 보세요:")
    print(f"    http://{my_ip()}:{PORT}")
    print(f"    http://{socket.gethostname()}.local:{PORT}")
    print(f"\n  종료: Ctrl+C\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료 중...")
    finally:
        for c in cams.values():
            c.alive = False
        time.sleep(0.3)
        server.server_close()
        print("종료")


if __name__ == "__main__":
    main()
