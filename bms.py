"""JBD BMS BLE 常時監視 (Phase ②)

2台のJBD BMSに持続BLE接続し、5秒間隔でポーリング。
asyncio.Lockで全BLE操作をシリアライズしInProgress回避。
接続断は自動再接続（10s+ランダムジッター待機）。
オフライン時は前回値を保持。

CMD_PWD  → パスワード解除（CMD_BASICを有効化するために必要）
CMD_BASIC → パック電圧/電流/電力/SOC/温度/FET（2パケット分割対応）
CMD_CELL  → 各セル電圧（4セル）

cell over-voltage検出時はset_alert_callback()で登録したコールバックを呼ぶ。
OV閾値はsettings_storeから読み込む（設定UIで変更可能）。
"""
import asyncio
import logging
import random
import subprocess
import threading
import time
from datetime import datetime
from typing import Optional

import settings_store

logger = logging.getLogger(__name__)

_NOTIFY    = "0000ff01-0000-1000-8000-00805f9b34fb"
_WRITE     = "0000ff02-0000-1000-8000-00805f9b34fb"
_CMD_PWD   = bytes([0xDD, 0x5A, 0x00, 0x02, 0x00, 0x00, 0xFF, 0xFE, 0x77])
_CMD_BASIC = bytes([0xDD, 0xA5, 0x03, 0x00, 0xFF, 0xFD, 0x77])
_CMD_CELL  = bytes([0xDD, 0xA5, 0x04, 0x00, 0xFF, 0xFC, 0x77])

_BMS_LIST = [
    ("bms1", "A4:C1:38:87:10:5D"),
    ("bms2", "A4:C1:38:6A:28:92"),
]

_FAST_POLL        = 5.0   # 持続接続ポーリング間隔[s]
_CELL_OV_V        = 3.65  # デフォルト過電圧停止閾値[V]（settings_storeで上書き可）
_CELL_OV_RESUME_V = 3.60  # デフォルト過電圧復帰閾値[V]

# オフライン時も保持するフィールド
_STALE_KEYS = (
    "cells", "pack_v", "pack_a", "pack_w",
    "cell_min", "cell_max", "cell_delta",
    "soc", "remain_ah", "full_ah", "temps", "fet", "prot",
)

_lock          = threading.Lock()
_latest: dict  = {}
_ov_alerted: set = set()   # 過電圧アラート済みBMS名（解消までcallback抑制）
_alert_callback = None

# BLE監視on/offスイッチ（デフォルトON = 従来の常時監視動作を維持）。
# OFFにするとBLE切断しスマホ等から直接BMSへ接続できる状態になる。
# サービス再起動時は常にONへ戻る（フェイルセーフ: 過電圧保護を有効に保つ）。
_enabled = threading.Event()
_enabled.set()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_status() -> dict:
    with _lock:
        return dict(_latest)


def set_alert_callback(fn):
    """cell over-voltage検出時に呼ばれるコールバックを登録する。

    fn(bms_name: str, reason: str) の形式で呼ばれる。
    """
    global _alert_callback
    _alert_callback = fn


def is_ov_active() -> bool:
    """いずれかのBMSでセル過電圧が検出中かどうか。"""
    with _lock:
        return len(_ov_alerted) > 0


def is_polling_enabled() -> bool:
    return _enabled.is_set()


def enable_polling():
    """BLE監視を再開する。"""
    _enabled.set()
    logger.info("BMS polling enabled")


def disable_polling():
    """BLE監視を停止しBMSから切断する（スマホ等から直接アクセスするため）。

    過電圧アラート状態(_ov_alerted)は解除しない（フェイルセーフ:
    Tracerの充電停止はそのまま維持される）。
    """
    _enabled.clear()
    logger.info("BMS polling disabled")


# ---------------------------------------------------------------------------
# BLE フレーム組み立て
# ---------------------------------------------------------------------------

class _Assembler:
    """JBD BLE分割パケットをJBDフレームに結合する。

    BASIC応答は34バイト（MTU20で2分割）、CELL応答は15バイト（1パケット）。
    """

    def __init__(self):
        self._buf: bytearray = bytearray()
        self._frames: list = []

    def reset(self):
        self._buf.clear()
        self._frames.clear()

    def feed(self, data: bytes):
        if not any(data):   # all-zerosはBLEキャッシュ値なので無視
            return
        self._buf.extend(data)
        while len(self._buf) >= 4:
            if self._buf[0] != 0xDD:
                del self._buf[0]
                continue
            if self._buf[2] != 0x00:
                del self._buf[0]
                continue
            length = self._buf[3]
            total = 4 + length + 3
            if len(self._buf) < total:
                break
            frame = bytes(self._buf[:total])
            if frame[-1] == 0x77:
                self._frames.append(frame)
            self._buf = self._buf[total:]

    def pop_frames(self) -> list:
        out = self._frames[:]
        self._frames.clear()
        return out


# ---------------------------------------------------------------------------
# フレーム解析
# ---------------------------------------------------------------------------

def _parse_basic(frame: bytes) -> Optional[dict]:
    """CMD_BASIC(0x03)レスポンスをパース。パスワード解除後に取得可能。"""
    if len(frame) < 7 or frame[1] != 0x03:
        return None
    d = frame[4:]
    raw_a = int.from_bytes(d[2:4], 'big')
    pack_a = round((raw_a - 65536 if raw_a > 32767 else raw_a) / 100.0, 2)
    pack_v = round(int.from_bytes(d[0:2], 'big') / 100.0, 2)
    pack_w = round(pack_v * pack_a, 1)
    ntc = d[22] if len(d) > 22 else 0
    temps = []
    for i in range(ntc):
        off = 23 + i * 2
        if off + 2 <= len(d):
            temps.append(round((int.from_bytes(d[off:off + 2], 'big') - 2731) / 10.0, 1))
    return {
        "pack_v":    pack_v,
        "pack_a":    pack_a,
        "pack_w":    pack_w,
        "remain_ah": round(int.from_bytes(d[4:6], 'big') / 100.0, 1) if len(d) > 5 else None,
        "full_ah":   round(int.from_bytes(d[6:8], 'big') / 100.0, 1) if len(d) > 7 else None,
        "soc":       d[19] if len(d) > 19 else None,
        "temps":     temps,
        "fet":       d[20] if len(d) > 20 else None,
        "prot":      int.from_bytes(d[16:18], 'big') if len(d) > 17 else 0,
    }


def _parse_cell(frame: bytes) -> Optional[dict]:
    """CMD_CELL(0x04)レスポンスをパース。"""
    if len(frame) < 7 or frame[1] != 0x04:
        return None
    n = frame[3] // 2
    cells = [round(int.from_bytes(frame[4 + i * 2:6 + i * 2], 'big') / 1000.0, 3)
             for i in range(n)]
    if not cells:
        return None
    return {
        "cells":      cells,
        "cell_min":   round(min(cells), 3),
        "cell_max":   round(max(cells), 3),
        "cell_delta": round(max(cells) - min(cells), 3),
    }


# ---------------------------------------------------------------------------
# OV検出・アラート
# ---------------------------------------------------------------------------

def _check_and_alert(name: str, result: dict):
    """over-voltage検出時にcallbackを呼ぶ。解消時はアラート状態をリセット。"""
    if not result.get("online"):
        return
    cfg = settings_store.get()
    ov_stop_v   = cfg.get("bms_ov_stop_v",   _CELL_OV_V)
    ov_resume_v = cfg.get("bms_ov_resume_v",  _CELL_OV_RESUME_V)

    prot  = result.get("prot") or 0
    cells = result.get("cells") or []
    ov_prot = bool(prot & 0x0001)
    ov_cell = bool(cells and max(cells) >= ov_stop_v)

    if ov_prot or ov_cell:
        with _lock:
            if name in _ov_alerted:
                return  # 既にアラート済み: Tracerは停止中
            _ov_alerted.add(name)
        reasons = []
        if ov_prot:
            reasons.append(f"prot_bit0=1 (0x{prot:04X})")
        if ov_cell:
            reasons.append(f"cell_max={max(cells):.3f}V >= {ov_stop_v}V")
        logger.warning("BMS %s cell OV detected: %s", name, ", ".join(reasons))
        if _alert_callback:
            _alert_callback(name, ", ".join(reasons))
    else:
        # cellデータなしの場合はOV状態を維持（不確実なデータでクリアしない）
        if not cells:
            return
        # 復帰閾値を下回った場合のみクリア（ヒステリシス）
        if max(cells) < ov_resume_v:
            with _lock:
                if name in _ov_alerted:
                    logger.info("BMS %s cell OV cleared (cell_max=%.3fV < %.3fV)",
                                name, max(cells), ov_resume_v)
                _ov_alerted.discard(name)


# ---------------------------------------------------------------------------
# stale data統合
# ---------------------------------------------------------------------------

def _merge_result(name: str, result: dict, now: str):
    """poll結果をstale dataと統合して_latestに保存する。_lockを保持した状態で呼ぶ。"""
    prev = _latest.get(name, {})
    if result.get("online") and result.get("cells"):
        result["last_seen"] = now
    else:
        result["last_seen"] = prev.get("last_seen")
        for key in _STALE_KEYS:
            if key in prev:
                result[key] = prev[key]
    _latest[name] = result


# ---------------------------------------------------------------------------
# 持続BLE監視ループ（asyncio.Lockで全BLE操作をシリアライズ）
# ---------------------------------------------------------------------------

async def _monitor_one(name: str, mac: str, shutdown: threading.Event,
                       ble_lock: asyncio.Lock):
    """1台のBMSに持続接続してポーリング。ble_lockで他タスクとシリアライズ。"""
    from bleak import BleakClient

    while not shutdown.is_set():
        if not _enabled.is_set():
            # 監視OFF中: オフライン扱いにして再度ONになるまで待機（接続は試みない）
            now = datetime.now().isoformat(timespec="seconds")
            with _lock:
                _merge_result(name, {"name": name, "mac": mac, "online": False}, now)
            while not _enabled.is_set() and not shutdown.is_set():
                await asyncio.sleep(1.0)
            continue

        asm = _Assembler()
        got_data = asyncio.Event()

        def on_notify(_, data):
            b = bytes(data)
            if any(b):
                asm.feed(b)
                got_data.set()

        client = BleakClient(mac, timeout=15.0)
        disabled_exit = False
        try:
            # 接続・setup はロックして行う（InProgress回避）
            async with ble_lock:
                await client.connect()
                await client.start_notify(_NOTIFY, on_notify)
                await asyncio.sleep(1.5)
                await client.write_gatt_char(_WRITE, _CMD_PWD, response=False)
                await asyncio.sleep(0.5)

            logger.info("BMS %s connected (%s)", name, mac)

            while not shutdown.is_set() and client.is_connected and _enabled.is_set():
                # CMD_BASIC + CMD_CELL もロックして行う
                async with ble_lock:
                    asm.reset()
                    result = {"name": name, "mac": mac, "online": True}

                    # CMD_BASIC（2パケット分割: 1枚目受信後0.5s待ちで2枚目を収集）
                    got_data.clear()
                    await client.write_gatt_char(_WRITE, _CMD_BASIC, response=False)
                    try:
                        await asyncio.wait_for(got_data.wait(), timeout=3.5)
                        await asyncio.sleep(0.5)
                    except asyncio.TimeoutError:
                        logger.debug("BMS %s CMD_BASIC timeout", name)

                    # CMD_CELL
                    got_data.clear()
                    await client.write_gatt_char(_WRITE, _CMD_CELL, response=False)
                    try:
                        await asyncio.wait_for(got_data.wait(), timeout=3.0)
                    except asyncio.TimeoutError:
                        logger.debug("BMS %s CMD_CELL timeout", name)

                # ロック外でパース・チェック・ログ
                for frame in asm.pop_frames():
                    if frame[1] == 0x03:
                        p = _parse_basic(frame)
                        if p:
                            result.update(p)
                    elif frame[1] == 0x04:
                        p = _parse_cell(frame)
                        if p:
                            result.update(p)

                if "cells" in result and "pack_v" not in result:
                    result["pack_v"] = round(sum(result["cells"]), 2)

                now = datetime.now().isoformat(timespec="seconds")
                with _lock:
                    _merge_result(name, result, now)

                _check_and_alert(name, result)

                logger.info(
                    "BMS %s online=%s pack_v=%s pack_a=%s soc=%s temps=%s cells=%s",
                    name, result.get("online"), result.get("pack_v"),
                    result.get("pack_a"), result.get("soc"),
                    result.get("temps"), result.get("cells"),
                )

                # 次のポーリングまで1秒刻みで待機（shutdown/OFFに即応）
                for _ in range(int(_FAST_POLL)):
                    if shutdown.is_set() or not client.is_connected or not _enabled.is_set():
                        break
                    await asyncio.sleep(1.0)

            if not shutdown.is_set() and not _enabled.is_set():
                disabled_exit = True
                logger.info("BMS %s polling disabled, disconnecting", name)
                now = datetime.now().isoformat(timespec="seconds")
                with _lock:
                    _merge_result(name, {"name": name, "mac": mac, "online": False}, now)

        except Exception as e:
            logger.warning("BMS %s (%s): %s → reconnect in 10s", name, mac, e)
            now = datetime.now().isoformat(timespec="seconds")
            with _lock:
                _merge_result(name, {"name": name, "mac": mac, "online": False}, now)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

        if disabled_exit:
            # bluetoothctlレベルでも切断しスマホ等が即座に接続できる状態にする
            # (blocking呼び出しなのでexecutorへ逃がし他タスクをブロックしない)
            await asyncio.get_event_loop().run_in_executor(None, _bt_disconnect, mac)
        elif not shutdown.is_set():
            # ジッターで同時再接続によるInProgressを回避
            await asyncio.sleep(10.0 + random.uniform(0.0, 3.0))


async def _run_loop(shutdown: threading.Event):
    ble_lock = asyncio.Lock()   # 全BLE操作をシリアライズ
    # BMS1を先に起動し、3s待ってBMS2を起動（初回接続のタイミングをずらす）
    task1 = asyncio.create_task(_monitor_one(*_BMS_LIST[0], shutdown, ble_lock))
    await asyncio.sleep(3.0)
    task2 = asyncio.create_task(_monitor_one(*_BMS_LIST[1], shutdown, ble_lock))
    await asyncio.gather(task1, task2, return_exceptions=True)


def _bt_disconnect(mac: str):
    """bluetoothctlでスタレBLE接続をクリアする。プロセス再起動後に前回接続が残る場合に必要。"""
    try:
        r = subprocess.run(
            ["bluetoothctl", "disconnect", mac],
            capture_output=True, text=True, timeout=8,
        )
        if "Disconnection successful" in r.stdout:
            logger.info("Cleared stale BLE connection: %s", mac)
        else:
            logger.debug("bt_disconnect %s: %s", mac, r.stdout.strip())
    except Exception as e:
        logger.debug("bt_disconnect %s: %s", mac, e)


def start_polling(shutdown: threading.Event) -> threading.Thread:
    # 起動前にスタレ接続をクリア（前回のプロセスが接続を残したまま終了した場合の対策）
    for _, mac in _BMS_LIST:
        _bt_disconnect(mac)
    time.sleep(1.0)

    def _thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run_loop(shutdown))
        finally:
            loop.close()

    t = threading.Thread(target=_thread, daemon=True, name="bms-poll")
    t.start()
    cfg = settings_store.get()
    logger.info(
        "BMS persistent monitoring started: %s (poll=%.0fs, OV_stop=%.2fV, OV_resume=%.2fV)",
        [m for _, m in _BMS_LIST], _FAST_POLL,
        cfg.get("bms_ov_stop_v", _CELL_OV_V),
        cfg.get("bms_ov_resume_v", _CELL_OV_RESUME_V),
    )
    return t
