"""実行時設定の永続化。config.pyのデフォルト値をベースにsettings.jsonで上書き。

main.py 起動時に load() を呼ぶ。
WebUI から update() で変更 → 即時反映 + settings.json に保存。
"""
import json
import logging
import os
import threading

import config

logger = logging.getLogger(__name__)

_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
_lock = threading.Lock()


def _defaults() -> dict:
    return {
        "temp_high":             config.TEMP_HIGH,
        "temp_low":              config.TEMP_LOW,
        "boost_voltage_normal_v": round(config.BOOST_VOLTAGE_NORMAL * 0.01, 2),
        "boost_voltage_stop_v":   round(config.BOOST_VOLTAGE_STOP   * 0.01, 2),
    }


_state: dict = _defaults()


def load():
    """settings.jsonが存在すれば読み込んでデフォルト値を上書きする。"""
    global _state
    _state = _defaults()
    if not os.path.exists(_FILE):
        return
    try:
        with open(_FILE) as f:
            saved = json.load(f)
        with _lock:
            for k in list(_state):
                if k in saved:
                    _state[k] = float(saved[k])
        logger.info("Settings loaded from %s: %s", _FILE, _state)
    except Exception as e:
        logger.warning("Settings load failed (%s), using defaults", e)


def get() -> dict:
    with _lock:
        return dict(_state)


def update(patch: dict):
    """設定を検証・更新・保存する。戻り値: (ok: bool, error_msg: str)"""
    try:
        th = float(patch["temp_high"])
        tl = float(patch["temp_low"])
        vn = float(patch["boost_voltage_normal_v"])
        vs = float(patch["boost_voltage_stop_v"])
    except (KeyError, ValueError, TypeError) as e:
        return False, f"パラメータエラー: {e}"

    if not (20.0 <= tl and th <= 65.0):
        return False, "温度は 20〜65°C の範囲で設定してください"
    if tl >= th:
        return False, f"充電再開温度({tl}°C) は停止温度({th}°C) より低くしてください"
    if th - tl < 2.0:
        return False, f"ヒステリシス不足: 停止({th}) − 再開({tl}) は 2°C 以上必要です"
    if not (10.0 <= vs and vn <= 15.5):
        return False, "電圧は 10〜15.5V の範囲で設定してください"
    if vs >= vn:
        return False, f"充電停止電圧({vs}V) は通常充電電圧({vn}V) より低くしてください"

    new = {
        "temp_high": th, "temp_low": tl,
        "boost_voltage_normal_v": round(vn, 2),
        "boost_voltage_stop_v":   round(vs, 2),
    }
    with _lock:
        _state.update(new)
        try:
            with open(_FILE, "w") as f:
                json.dump(_state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Settings save failed: %s", e)
            return False, f"保存エラー: {e}"

    logger.info("Settings saved: TEMP %.1f/%.1f°C  BOOST %.2f/%.2fV", tl, th, vs, vn)
    return True, ""
