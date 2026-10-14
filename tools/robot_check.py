#!/usr/bin/env python3
"""로봇 PC 상태 점검 — WiFi · 서보 전원 · USB 대역폭

라즈베리파이를 AP(공유기)로만 쓰고 카메라와 팔/리더를 전부 PC 에 직접 꽂은
구성에서, 추론(ACT)을 돌리기 전에 PC 쪽 상태를 한 번에 확인한다.

    python3 ~/Desktop/로봇_점검.py              # 전체 점검
    python3 ~/Desktop/로봇_점검.py wifi         # 한 부분만
    python3 ~/Desktop/로봇_점검.py servo
    python3 ~/Desktop/로봇_점검.py usb

점검 항목
    1. WiFi      세기 · 채널 혼잡 · 링크 속도 · 지연(유휴/부하) · 실효 전송량
    2. 서보 전원  팔로워/리더 각 축의 공급 전압과 온도
    3. USB 대역폭 카메라를 동시에 열었을 때 실제로 몇 fps 가 나오는지

설치가 필요한 것은 없다. 없는 도구는 건너뛰고 무엇이 없는지 알려준다.
    pyserial  없으면 → 서보 점검 생략
    opencv    없으면 → 카메라 점검 생략
"""

import glob
import os
import re
import shutil
import socket
import subprocess
import sys
import time

# ── 기준값 ───────────────────────────────────────────────────────────────
SERVO_BAUD = 1_000_000  # STS3215 기본 통신 속도
SERVO_IDS = range(1, 10)  # 7축 + 베이스 바퀴까지 여유 있게 훑는다
ADDR_VOLTAGE = 62  # 1바이트, 0.1V 단위
ADDR_TEMP = 63  # 1바이트, 섭씨

VOLT_OK = (10.0, 13.0)  # 12V 계열 정상 범위
TEMP_WARN = 60  # 이 온도를 넘으면 주의
SIGNAL_OK = -60  # dBm, 이보다 크면 양호
LAT_OK = 10.0  # ms, 유휴 지연이 이보다 작으면 양호

C = {
    "r": "\033[0m", "b": "\033[1m", "dim": "\033[2m",
    "ok": "\033[32m", "warn": "\033[33m", "no": "\033[31m", "hi": "\033[36m",
}
if not sys.stdout.isatty():
    C = dict.fromkeys(C, "")


def title(text):
    print(f"\n{C['b']}{'=' * 74}\n {text}\n{'=' * 74}{C['r']}")


def sub(text):
    print(f"\n{C['b']}── {text} ──{C['r']}")


def row(label, value, verdict="", width=26):
    tag = {"ok": f"{C['ok']}정상{C['r']}", "warn": f"{C['warn']}주의{C['r']}",
           "no": f"{C['no']}문제{C['r']}", "": ""}.get(verdict, verdict)
    print(f"  {label:<{width}s} {value}" + (f"   {tag}" if tag else ""))


def run(cmd, timeout=15):
    """셸 명령을 돌리고 표준출력을 돌려준다. 실패하면 빈 문자열."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""


def have(tool):
    return shutil.which(tool) is not None


# ══════════════════════════════════════════════════════════════════════════
# 1. WiFi
# ══════════════════════════════════════════════════════════════════════════

def wifi_interface():
    """무선 인터페이스 이름을 찾는다."""
    for path in glob.glob("/sys/class/net/*/wireless"):
        return path.split("/")[-2]
    return None


def wifi_link(iface):
    """현재 접속 정보. nmcli 가 없으면 iw / sysfs 로 떨어진다."""
    info = {}
    if have("nmcli"):
        out = run(f"nmcli -t -f ACTIVE,SSID,CHAN,FREQ,RATE,SIGNAL,BARS dev wifi list ifname {iface}")
        for line in out.splitlines():
            if line.startswith("yes:"):
                p = line.split(":")
                info.update(ssid=p[1], chan=p[2], freq=p[3], rate=p[4], signal=p[5])
                break
    if have("iw"):
        out = run(f"iw dev {iface} link")
        if m := re.search(r"SSID:\s*(.+)", out):
            info.setdefault("ssid", m.group(1).strip())
        if m := re.search(r"freq:\s*([\d.]+)", out):
            info["freq_mhz"] = float(m.group(1))
        if m := re.search(r"signal:\s*(-?\d+)", out):
            info["dbm"] = int(m.group(1))
        if m := re.search(r"tx bitrate:\s*([\d.]+)", out):
            info["tx_mbps"] = float(m.group(1))
        if m := re.search(r"rx bitrate:\s*([\d.]+)", out):
            info["rx_mbps"] = float(m.group(1))
    return info


def wifi_congestion(iface):
    """주변 AP 를 채널별로 센다. 같은 채널에 많을수록 느려진다."""
    if not have("nmcli"):
        return {}
    out = run(f"nmcli -t -f CHAN dev wifi list ifname {iface} --rescan auto", timeout=30)
    counts = {}
    for line in out.splitlines():
        ch = line.strip()
        if ch.isdigit():
            counts[int(ch)] = counts.get(int(ch), 0) + 1
    return counts


def gateway():
    """기본 게이트웨이 = AP(라즈베리파이) 주소."""
    out = run("ip route show default")
    m = re.search(r"default via (\S+)", out)
    return m.group(1) if m else None


def ping_stats(host, count=20, interval=0.2, extra=""):
    out = run(f"ping -c {count} -i {interval} -q {extra} {host}", timeout=count * interval + 20)
    m = re.search(r"=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", out)
    loss = re.search(r"(\d+(?:\.\d+)?)% packet loss", out)
    if not m:
        return None
    return {"min": float(m.group(1)), "avg": float(m.group(2)),
            "max": float(m.group(3)), "mdev": float(m.group(4)),
            "loss": float(loss.group(1)) if loss else 0.0}


def throughput_to(host, seconds=6, port=5299):
    """AP 로 실제 데이터를 밀어 넣어 실효 전송량을 잰다.

    상대쪽에 받아줄 프로그램이 필요하므로 SSH 가 되는 경우에만 측정한다.
    안 되면 None 을 돌려주고, 링크 속도만 보고한다.
    """
    user = os.environ.get("ROBOT_SSH_USER", "")
    target = f"{user}@{host}" if user else host
    probe = run(f"ssh -o BatchMode=yes -o ConnectTimeout=4 {target} 'echo ok'", timeout=12)
    if "ok" not in probe:
        return None

    my_ip = re.search(r"src (\S+)", run(f"ip route get {host}"))
    if not my_ip:
        return None
    my_ip = my_ip.group(1)

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(1)
    srv.settimeout(seconds + 15)

    sender = (
        f"python3 -c \"import socket,time;"
        f"s=socket.socket();s.settimeout(8);s.connect(('{my_ip}',{port}));"
        f"b=b'x'*65536;e=time.time()+{seconds};"
        f"\nwhile time.time()<e: s.send(b)\ns.close()\""
    ).replace("\n", "")
    proc = subprocess.Popen(
        ["ssh", "-o", "BatchMode=yes", target, sender],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        conn, _ = srv.accept()
        conn.settimeout(seconds + 10)
        total, t0, last = 0, time.time(), time.time()
        while True:
            chunk = conn.recv(1 << 20)
            if not chunk:
                break
            total += len(chunk)
            last = time.time()
        conn.close()
        elapsed = max(last - t0, 1e-9)
        return total * 8 / elapsed / 1e6
    except Exception:
        return None
    finally:
        proc.kill()
        srv.close()


def check_wifi():
    title("1. WiFi — 세기 · 채널 · 지연 · 전송량")

    iface = wifi_interface()
    if not iface:
        print(f"  {C['no']}무선 인터페이스를 찾을 수 없습니다.{C['r']}")
        return
    row("무선 인터페이스", iface)

    link = wifi_link(iface)
    if not link.get("ssid"):
        print(f"  {C['no']}WiFi 에 접속되어 있지 않습니다.{C['r']}")
        return

    sub("접속 상태")
    row("SSID", link.get("ssid", "?"))

    freq = link.get("freq_mhz") or float(re.sub(r"\D", "", link.get("freq", "0")) or 0)
    band = "5GHz" if freq >= 5000 else ("2.4GHz" if freq else "?")
    chan = link.get("chan", "?")
    row("대역 · 채널", f"{band}  ch{chan}  ({freq:.0f} MHz)" if freq else band,
        "ok" if band == "5GHz" else "warn")

    if "dbm" in link:
        d = link["dbm"]
        v = "ok" if d >= SIGNAL_OK else ("warn" if d >= -70 else "no")
        row("신호 세기", f"{d} dBm", v)
    elif link.get("signal", "").isdigit():
        # iw 가 없으면 nmcli 의 백분율만 얻을 수 있다. 대략 dBm = 백분율/2 - 100.
        pct = int(link["signal"])
        approx = pct / 2 - 100
        v = "ok" if pct >= 70 else ("warn" if pct >= 50 else "no")
        row("신호 세기", f"{pct} %  (약 {approx:.0f} dBm)", v)

    tx, rx = link.get("tx_mbps"), link.get("rx_mbps")
    if not tx and link.get("rate"):
        if m := re.search(r"([\d.]+)", link["rate"]):
            tx = float(m.group(1))
    if tx:
        # 링크 속도는 전파상 속도이고, 실제 데이터는 이보다 훨씬 적게 흐른다.
        row("링크 속도 (송신/수신)", f"{tx:.1f} / {rx or tx:.1f} Mbps")
        width = {72.2: "20MHz", 86.7: "20MHz", 150: "40MHz", 200: "40MHz",
                 433.3: "80MHz", 390: "80MHz", 866.7: "160MHz"}.get(round(tx, 1))
        if width:
            row("채널 폭 (추정)", width, "ok" if width != "20MHz" else "warn")

    sub("채널 혼잡도  — 같은 채널에 몰릴수록 느려진다")
    counts = wifi_congestion(iface)
    if counts:
        mine = int(chan) if str(chan).isdigit() else None
        for ch, n in sorted(counts.items(), key=lambda x: -x[1])[:6]:
            mark = "  ← 현재 사용 중" if ch == mine else ""
            v = ""
            if ch == mine:
                v = "ok" if n <= 2 else ("warn" if n <= 5 else "no")
            row(f"ch{ch}", f"AP {n}개{mark}", v, width=10)
        if mine and counts.get(mine, 0) > 5:
            print(f"  {C['no']}현재 채널에 AP 가 많습니다. 전송량이 크게 떨어집니다.{C['r']}")
    else:
        print(f"  {C['dim']}nmcli 가 없어 건너뜁니다.{C['r']}")

    gw = gateway()
    if not gw:
        print(f"\n  {C['warn']}기본 게이트웨이를 찾지 못해 지연을 재지 못했습니다.{C['r']}")
        return

    sub(f"지연  — AP({gw}) 까지")
    idle = ping_stats(gw, count=20)
    if idle:
        v = "ok" if idle["avg"] < LAT_OK else ("warn" if idle["avg"] < 50 else "no")
        row("유휴 상태", f"평균 {idle['avg']:.1f} ms   최대 {idle['max']:.1f}   흔들림 {idle['mdev']:.1f}", v)
        row("패킷 손실", f"{idle['loss']:.0f} %", "ok" if idle["loss"] == 0 else "no")

    # 부하를 주면서 다시 잰다. 평소엔 멀쩡하다가 데이터가 흐를 때 튀는 경우를 잡는다.
    load = subprocess.Popen(f"ping -f -w 6 {gw} >/dev/null 2>&1", shell=True)
    busy = ping_stats(gw, count=15)
    load.wait()
    if busy and idle:
        jump = busy["avg"] - idle["avg"]
        v = "ok" if jump < 20 else ("warn" if jump < 100 else "no")
        row("부하 중", f"평균 {busy['avg']:.1f} ms   (유휴 대비 +{jump:.1f})", v)
        if jump > 100:
            print(f"  {C['no']}부하를 주면 지연이 크게 늘어납니다 — 대역이 포화 상태입니다.{C['r']}")

    sub("실효 전송량")
    mbps = throughput_to(gw)
    if mbps is None:
        print(f"  {C['dim']}AP 에 SSH 로 접속할 수 없어 실제 전송량은 재지 못했습니다.{C['r']}")
        print(f"  {C['dim']}재려면:  ROBOT_SSH_USER=<계정> python3 {sys.argv[0]} wifi{C['r']}")
        if tx:
            print(f"  {C['dim']}참고로 링크 속도 {tx:.0f} Mbps 면 실효는 보통 그 30~50% 입니다.{C['r']}")
    else:
        v = "ok" if mbps >= 50 else ("warn" if mbps >= 33 else "no")
        row("AP 로 보낸 실측", f"{mbps:.1f} Mbps", v)
        row("카메라 2대(품질90) 기준", f"필요 33 Mbps  —  여유 {mbps / 33:.1f}배",
            "ok" if mbps / 33 >= 1.5 else "warn")


# ══════════════════════════════════════════════════════════════════════════
# 2. 서보 전원
# ══════════════════════════════════════════════════════════════════════════

def feetech_read(ser, motor_id, addr, length):
    """Feetech STS/SCS 프로토콜로 레지스터 하나를 읽는다.

    보내는 형식:  FF FF ID LEN INST ADDR N CHK      (INST 0x02 = READ)
    받는 형식  :  FF FF ID LEN ERR DATA.. CHK
    """
    body = [motor_id, 4, 0x02, addr, length]
    packet = bytes([0xFF, 0xFF] + body + [(~sum(body)) & 0xFF])

    ser.reset_input_buffer()
    ser.write(packet)

    deadline = time.time() + 0.05
    buf = b""
    while time.time() < deadline:
        buf += ser.read(ser.in_waiting or 1)
        idx = buf.find(b"\xff\xff")
        if idx >= 0 and len(buf) >= idx + 6 + length - 1:
            frame = buf[idx + 2:]
            if frame[0] != motor_id:
                return None
            data = frame[3:3 + length]
            if len(data) < length:
                return None
            return int.from_bytes(data, "little")
    return None


def serial_ports():
    """후보 시리얼 포트를 모은다. 이름 붙은 심볼릭 링크를 우선한다."""
    named = sorted(glob.glob("/dev/so1*") + glob.glob("/dev/*follower*") + glob.glob("/dev/*leader*"))
    raw = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
    seen, out = set(), []
    for p in named + raw:
        real = os.path.realpath(p)
        if real in seen:
            continue
        seen.add(real)
        out.append(p)
    return out


def check_servo():
    title("2. 서보 전원 — 팔로워 / 리더 각 축")

    try:
        import serial  # noqa: F401
    except ImportError:
        print(f"  {C['warn']}pyserial 이 없어 건너뜁니다.{C['r']}")
        print(f"  {C['dim']}lerobot 가상환경에서 실행하면 보통 들어 있습니다.{C['r']}")
        return
    import serial

    ports = serial_ports()
    if not ports:
        print(f"  {C['no']}시리얼 포트를 찾지 못했습니다. USB 케이블을 확인하세요.{C['r']}")
        return

    print(f"  찾은 포트 {len(ports)}개: {', '.join(ports)}")

    for port in ports:
        sub(f"{port}  →  {os.path.realpath(port)}")
        try:
            ser = serial.Serial(port, SERVO_BAUD, timeout=0.05)
        except Exception as exc:
            print(f"  {C['no']}열 수 없음: {exc}{C['r']}")
            print(f"  {C['dim']}다른 프로그램이 쓰고 있거나 권한이 없을 수 있습니다.{C['r']}")
            continue

        found = []
        with ser:
            time.sleep(0.1)
            for mid in SERVO_IDS:
                raw_v = feetech_read(ser, mid, ADDR_VOLTAGE, 1)
                if raw_v is None:
                    continue
                temp = feetech_read(ser, mid, ADDR_TEMP, 1)
                found.append((mid, raw_v / 10.0, temp))

        if not found:
            print(f"  {C['no']}응답하는 서보가 없습니다.{C['r']}")
            print(f"  {C['dim']}전원이 꺼져 있거나, 통신 속도가 {SERVO_BAUD} 가 아닐 수 있습니다.{C['r']}")
            continue

        print(f"  {'ID':<5s}{'전압':>9s}{'온도':>8s}   상태")
        print(f"  {'-' * 44}")
        volts = []
        for mid, volt, temp in found:
            volts.append(volt)
            notes = []
            if not (VOLT_OK[0] <= volt <= VOLT_OK[1]):
                notes.append(f"{C['no']}전압 이상{C['r']}")
            if temp and temp >= TEMP_WARN:
                notes.append(f"{C['warn']}온도 높음{C['r']}")
            mark = "  ".join(notes) or f"{C['ok']}정상{C['r']}"
            t = f"{temp}°C" if temp else "-"
            print(f"  {mid:<5d}{volt:>8.1f}V{t:>8s}   {mark}")

        lo, hi = min(volts), max(volts)
        row("축 수", f"{len(found)}개", "ok" if len(found) >= 7 else "warn")
        row("전압 범위", f"{lo:.1f} ~ {hi:.1f} V",
            "ok" if hi - lo < 0.5 else "warn")
        if hi - lo >= 0.5:
            # 끝쪽 축의 전압이 더 낮으면 배선 저항이나 전원 용량이 모자란 것이다.
            print(f"  {C['warn']}축마다 전압 차가 큽니다 — 배선 저항이나 전원 용량을 확인하세요.{C['r']}")


# ══════════════════════════════════════════════════════════════════════════
# 3. USB 대역폭
# ══════════════════════════════════════════════════════════════════════════

def usb_tree():
    if not have("lsusb"):
        return []
    out = run("lsusb -t")
    rows = []
    for line in out.splitlines():
        if m := re.search(r"Port (\d+):.*Class=(\S+).*Driver=(\S+?),\s*(\d+)M", line):
            rows.append({
                "port": m.group(1), "cls": m.group(2),
                "drv": m.group(3), "speed": int(m.group(4)),
                "depth": len(line) - len(line.lstrip(" |_")),
            })
        elif m := re.search(r"Bus (\d+).*Driver=(\S+?),\s*(\d+)M", line):
            rows.append({"bus": m.group(1), "speed": int(m.group(3)), "root": True})
    return rows


def video_devices():
    """영상이 실제로 나오는 노드만 고른다 (index 0)."""
    out = []
    for dev in sorted(glob.glob("/dev/video*"), key=lambda p: int(re.sub(r"\D", "", p) or 0)):
        idx_file = f"/sys/class/video4linux/{os.path.basename(dev)}/index"
        try:
            if open(idx_file).read().strip() != "0":
                continue
        except OSError:
            continue
        name = ""
        try:
            name = open(f"/sys/class/video4linux/{os.path.basename(dev)}/name").read().strip()
        except OSError:
            pass
        real = os.path.realpath(f"/sys/class/video4linux/{os.path.basename(dev)}/device")
        speed = ""
        m = re.search(r"/(\d+-[\d.]+)/", real + "/")
        if m:
            try:
                speed = open(f"/sys/bus/usb/devices/{m.group(1)}/speed").read().strip() + "M"
            except OSError:
                pass
        links = [p for p in glob.glob("/dev/cam*") if os.path.realpath(p) == dev]
        out.append({"dev": dev, "name": name, "bus": m.group(1) if m else "?",
                    "speed": speed, "links": links})
    return out


def measure_cameras(cams, width=640, height=480, fps=30, seconds=4):
    """카메라를 전부 동시에 열고 실제로 몇 장이 들어오는지 센다.

    USB 대역폭이 모자라면 요청한 30fps 가 안 나오고 그만큼 프레임이 빈다.
    """
    try:
        import cv2
    except ImportError:
        return None

    opened = []
    for c in cams:
        cap = cv2.VideoCapture(c["dev"], cv2.CAP_V4L2)
        if not cap.isOpened():
            opened.append((c, None))
            continue
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)
        opened.append((c, cap))

    live = [(c, cap) for c, cap in opened if cap is not None]
    for _, cap in live:
        for _ in range(5):
            cap.read()

    counts = {c["dev"]: 0 for c, _ in live}
    end = time.time() + seconds
    while time.time() < end:
        for c, cap in live:
            if cap.grab():
                counts[c["dev"]] += 1

    results = []
    for c, cap in opened:
        if cap is None:
            results.append({**c, "fps": None})
            continue
        ok, frame = cap.read()
        shape = frame.shape if ok and frame is not None else None
        cap.release()
        results.append({**c, "fps": counts[c["dev"]] / seconds, "shape": shape})
    return results


def check_usb():
    title("3. USB 대역폭 — 카메라를 동시에 열었을 때")

    sub("USB 구조")
    tree = usb_tree()
    if tree:
        out = run("lsusb -t")
        for line in out.splitlines():
            hot = "Video" in line or "cdc_acm" in line or "ftdi" in line or "ch34" in line
            print(f"  {C['hi'] if hot else C['dim']}{line}{C['r']}")
    else:
        print(f"  {C['dim']}lsusb 가 없어 건너뜁니다.{C['r']}")

    cams = video_devices()
    if not cams:
        print(f"\n  {C['no']}카메라를 찾지 못했습니다.{C['r']}")
        return

    sub(f"카메라 {len(cams)}대")
    for c in cams:
        alias = f"  ({', '.join(c['links'])})" if c["links"] else ""
        bus_speed = f"{c['speed']}" if c["speed"] else "?"
        tag = "USB3" if c["speed"] in ("5000M", "10000M") else "USB2"
        row(c["dev"], f"{c['name'][:28]:<28s} 포트 {c['bus']:<8s} {bus_speed:>7s} {tag}{alias}", width=14)

    # 서보와 카메라가 같은 버스를 나눠 쓰면 서로 간섭한다.
    cam_buses = {c["bus"].split(".")[0] for c in cams}
    if len(cam_buses) == 1 and len(cams) >= 3:
        print(f"  {C['warn']}카메라 {len(cams)}대가 모두 같은 USB 버스에 있습니다 — 경합할 수 있습니다.{C['r']}")

    sub("동시 열기 + 실제 fps 측정  (640x480 MJPG, 4초)")
    results = measure_cameras(cams)
    if results is None:
        print(f"  {C['warn']}opencv 가 없어 건너뜁니다.{C['r']}")
        print(f"  {C['dim']}lerobot 가상환경에서 실행하면 보통 들어 있습니다.{C['r']}")
        return

    ok_count = 0
    print(f"  {'장치':<14s}{'요청':>7s}{'실측':>9s}{'달성률':>9s}   상태")
    print(f"  {'-' * 58}")
    for r in results:
        if r["fps"] is None:
            print(f"  {r['dev']:<14s}{'30':>7s}{'열기 실패':>11s}{'':>7s}   {C['no']}문제{C['r']}")
            continue
        ratio = r["fps"] / 30 * 100
        if ratio >= 90:
            mark, ok_count = f"{C['ok']}정상{C['r']}", ok_count + 1
        elif ratio >= 70:
            mark = f"{C['warn']}주의{C['r']}"
        else:
            mark = f"{C['no']}부족{C['r']}"
        print(f"  {r['dev']:<14s}{'30':>7s}{r['fps']:>8.1f}{ratio:>8.0f}%   {mark}")

    print()
    if ok_count == len(results):
        print(f"  {C['ok']}모든 카메라가 30fps 를 내고 있습니다. USB 대역폭에 여유가 있습니다.{C['r']}")
    else:
        print(f"  {C['warn']}30fps 를 못 내는 카메라가 있습니다.{C['r']}")
        print(f"  {C['dim']}  · 카메라를 다른 USB 포트(가능하면 파란색 USB3)로 분산해 보세요.{C['r']}")
        print(f"  {C['dim']}  · 조명이 어두우면 카메라가 노출을 늘리려고 스스로 느려집니다.{C['r']}")
        print(f"  {C['dim']}  · 해상도를 낮추면 확실히 좋아집니다.{C['r']}")

    # 추론 때 PC 가 실제로 감당해야 하는 양
    live = [r for r in results if r["fps"]]
    if live:
        mbps_usb = len(live) * 17  # 640x480 MJPG 30fps ≈ 17 Mbps/대
        sub("참고 — 이 카메라 구성이 만들어 내는 데이터량")
        row("USB 로 들어오는 양", f"약 {mbps_usb} Mbps  (MJPG 기준)")
        row("무압축(YUYV)이었다면", f"약 {len(live) * 147} Mbps",
            "no" if len(live) * 147 > 400 else "warn")
        print(f"  {C['dim']}카메라를 열 때 fourcc 를 MJPG 로 지정해야 이 차이가 생깁니다.{C['r']}")


# ══════════════════════════════════════════════════════════════════════════

def main():
    which = sys.argv[1].lower() if len(sys.argv) > 1 else "all"

    print(f"{C['b']}로봇 PC 점검{C['r']}  —  {socket.gethostname()}  "
          f"{time.strftime('%Y-%m-%d %H:%M:%S')}")

    steps = {"wifi": check_wifi, "servo": check_servo, "usb": check_usb}
    if which in steps:
        steps[which]()
    elif which == "all":
        for fn in steps.values():
            try:
                fn()
            except KeyboardInterrupt:
                print("\n  중단됨")
                break
            except Exception as exc:
                print(f"  {C['no']}점검 중 오류: {exc}{C['r']}")
    else:
        print(__doc__)
        return

    print(f"\n{C['b']}{'=' * 74}{C['r']}")
    print("  판정 기준")
    print(f"    WiFi   신호 {SIGNAL_OK} dBm 이상 · 유휴 지연 {LAT_OK} ms 미만 · 현재 채널 AP 2대 이하")
    print(f"    서보   전압 {VOLT_OK[0]}~{VOLT_OK[1]} V · 온도 {TEMP_WARN}°C 미만 · 축 간 전압차 0.5V 미만")
    print("    USB    요청한 30fps 의 90% 이상")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n중단됨")
