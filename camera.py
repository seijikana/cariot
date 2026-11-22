"""ダッシュボード用USBカメラのスナップショット。

ffmpegでMJPEGフレームを再エンコードせずに1枚取り出す（-c:v copy）。
Zero 2Wでは1枚に約7秒かかるため、撮影はバックグラウンドで行い、
WebUIはメモリ上の最新画像を即座に返す。
閲覧が一定時間ないときは撮影しない（CPU・通信量の節約）。
"""
import logging
import subprocess
import threading
import time
from typing import Optional

import config
import settings_store

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_jpeg: Optional[bytes] = None
_captured_at: Optional[float] = None
_last_error: Optional[str] = None
_busy = False
_last_viewed = 0.0
_wake = threading.Event()


def _capture() -> bytes:
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "v4l2", "-input_format", "mjpeg",
        "-video_size", config.CAMERA_SNAPSHOT_SIZE, "-framerate", "15",
        "-i", config.CAMERA_DEVICE,
        "-ss", "1",              # 露出が落ち着くまで最初の約1秒は捨てる
        "-frames:v", "1", "-c:v", "copy", "-f", "mjpeg", "-",
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=20)
    if r.returncode != 0 or not r.stdout.startswith(b"\xff\xd8"):
        msg = r.stderr.decode(errors="replace").strip().splitlines()
        raise RuntimeError(msg[-1] if msg else f"ffmpeg rc={r.returncode}")
    return r.stdout


def interval_s() -> int:
    return int(settings_store.get().get("camera_interval_s", config.CAMERA_INTERVAL_S))


def touch():
    """閲覧があったことを記録し、撮影ループを起こす。"""
    global _last_viewed
    _last_viewed = time.time()
    _wake.set()


def get_snapshot():
    """(jpeg_bytes or None, captured_at or None)"""
    touch()
    with _lock:
        return _jpeg, _captured_at


def get_info() -> dict:
    with _lock:
        return {
            "interval_s": interval_s(),
            "captured_at": _captured_at,
            "error": _last_error,
            "busy": _busy,
            "available": _jpeg is not None,
        }


def _loop(shutdown: threading.Event):
    global _jpeg, _captured_at, _last_error, _busy
    while not shutdown.is_set():
        iv = interval_s()
        idle = time.time() - _last_viewed > max(config.CAMERA_IDLE_STOP_S, iv * 2)
        due = _captured_at is None or time.time() - _captured_at >= iv
        if iv > 0 and not idle and due:
            with _lock:
                _busy = True
            try:
                img = _capture()
                with _lock:
                    _jpeg, _captured_at, _last_error = img, time.time(), None
            except Exception as e:
                with _lock:
                    _last_error = str(e)[:200]
                logger.warning("camera snapshot failed: %s", e)
            finally:
                with _lock:
                    _busy = False
        _wake.wait(timeout=2.0)
        _wake.clear()


def start(shutdown: threading.Event) -> threading.Thread:
    t = threading.Thread(target=_loop, args=(shutdown,), daemon=True, name="camera")
    t.start()
    return t
