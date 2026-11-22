"""gpsdから現在地を受け取り、最新値を保持する。

gpsdのJSONストリーム（?WATCH）を直接読む。追加ライブラリは不要。
"""
import json
import logging
import socket
import threading
import time

import config

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state: dict = {}
_STALE_S = 15   # この秒数TPVが来なければ「測位なし」扱い


def get_status() -> dict:
    with _lock:
        s = dict(_state)
    if not s:
        return {"connected": False}
    age = time.time() - s.get("_rx", 0)
    s["age_s"] = round(age, 1)
    if age > _STALE_S:
        s["mode"] = 0
    s.pop("_rx", None)
    return s


def _handle(msg: dict):
    cls = msg.get("class")
    with _lock:
        if cls == "TPV":
            mode = msg.get("mode", 0)
            _state.update({
                "connected": True,
                "mode": mode,                       # 0/1=測位なし 2=2D 3=3D
                "lat": msg.get("lat"),
                "lon": msg.get("lon"),
                "alt": msg.get("altMSL", msg.get("alt")),
                "speed_kmh": round(msg["speed"] * 3.6, 1) if msg.get("speed") is not None else None,
                "track": msg.get("track"),
                "eph": msg.get("eph"),              # 水平誤差の目安[m]
                "time": msg.get("time"),
                "_rx": time.time(),
            })
        elif cls == "SKY":
            sats = msg.get("satellites")
            if sats is not None:
                _state["sats_used"] = sum(1 for s in sats if s.get("used"))
                _state["sats_seen"] = len(sats)
            else:
                if msg.get("uSat") is not None:
                    _state["sats_used"] = msg["uSat"]
                if msg.get("nSat") is not None:
                    _state["sats_seen"] = msg["nSat"]
        elif cls == "DEVICES":
            _state["device"] = ",".join(d.get("path", "") for d in msg.get("devices", []))


def _loop(shutdown: threading.Event):
    while not shutdown.is_set():
        try:
            with socket.create_connection((config.GPS_HOST, config.GPS_PORT), timeout=10) as sock:
                sock.sendall(b'?WATCH={"enable":true,"json":true};\n')
                sock.settimeout(10)
                buf = b""
                while not shutdown.is_set():
                    chunk = sock.recv(4096)
                    if not chunk:
                        raise ConnectionError("gpsd closed connection")
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        try:
                            _handle(json.loads(line))
                        except ValueError:
                            pass
        except Exception as e:
            with _lock:
                _state["connected"] = False
                _state["error"] = str(e)[:120]
            logger.debug("gpsd connection error: %s", e)
            shutdown.wait(5)


def start(shutdown: threading.Event) -> threading.Thread:
    t = threading.Thread(target=_loop, args=(shutdown,), daemon=True, name="gps")
    t.start()
    return t
