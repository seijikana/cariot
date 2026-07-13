#!/usr/bin/env python3
"""CarIoT メインループ (Phase ②: Tracer監視 + BMS + Flask WebUI)

systemd から起動する。SIGTERM/SIGINT で graceful shutdown。
"""
import logging
import os
import signal
import threading
import time
from datetime import datetime

import config
import history_store
import settings_store
import tracer as tracer_module
import bms as bms_module
import webui
import wifi_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_shutdown = threading.Event()


def _handle_signal(*_):
    logger.info("Shutdown signal received")
    _shutdown.set()


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ---------------------------------------------------------------------------
# 制御ループ（温度ヒステリシス）
# ---------------------------------------------------------------------------

def control_loop(tracer) -> dict:
    data = tracer.read_all()
    cfg = settings_store.get()

    temp = data.get("bat_temp")
    if temp is not None:
        if temp >= cfg["temp_high"] and not data.get("charge_stopped"):
            ok = tracer.stop_charging(cfg["boost_voltage_stop_v"])
            if ok:
                data["charge_stopped"] = True
            else:
                logger.error("stop_charging failed (Modbus write error)")
        elif temp <= cfg["temp_low"] and data.get("charge_stopped"):
            if not bms_module.is_ov_active():
                tracer.resume_charging(cfg["boost_voltage_normal_v"])
                data["charge_stopped"] = False
            else:
                logger.info("resume_charging skipped: BMS cell OV still active")

    data["bms"] = bms_module.get_status()
    webui.set_status(data)
    return data


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

def main():
    logger.info("=== CarIoT starting (Phase ②) ===")

    settings_store.load()
    history_store.init_db()

    tracer = tracer_module.create_tracer()

    def on_bms_ov(bms_name: str, reason: str):
        logger.warning("BMS OV alert [%s]: %s → stopping Tracer charging", bms_name, reason)
        ok = tracer.stop_charging()
        if ok:
            logger.warning("Tracer charging stopped by BMS OV protection [%s]", bms_name)
        else:
            logger.error("Tracer stop_charging FAILED after BMS OV alert [%s]!", bms_name)

    bms_module.set_alert_callback(on_bms_ov)
    bms_module.start_polling(_shutdown)
    logger.info("BMS persistent monitoring started")

    # APモード自動起動は無効化（車載HDMI+マウスで手動Wi-Fi設定する運用のため不要。
    # 散歩中のテザリング切替時など、わずかな切断でAPモードに入って復帰できなくなる問題があった）
    logger.info("WiFi AP auto-fallback disabled (manual control only)")

    flask_thread = threading.Thread(
        target=lambda: webui.app.run(
            host=config.WEBUI_HOST,
            port=config.WEBUI_PORT,
            debug=False,
            use_reloader=False,
            threaded=True,
        ),
        daemon=True,
        name="flask",
    )
    flask_thread.start()
    logger.info("Flask WebUI → http://%s:%d", config.WEBUI_HOST, config.WEBUI_PORT)

    # 起動時に過去7日分の欠損ロールアップを補完
    try:
        history_store.backfill_rollups()
    except Exception as e:
        logger.error("backfill_rollups error: %s", e)

    try:
        data = control_loop(tracer)
        logger.info("Initial read OK: PV=%.1fW Bat=%.2fV/%.1f°C/%d%%",
                    data.get("pv_power", 0), data.get("bat_voltage", 0),
                    data.get("bat_temp", 0), data.get("bat_soc", 0))
    except Exception as e:
        logger.warning("Initial read failed: %s", e)

    next_poll = time.monotonic()
    next_log = time.monotonic()

    # 毎時ロールアップ・日次バッチの重複実行防止
    _last_hour_ts = (int(time.time()) // 3600) * 3600
    _last_daily_ts = 0

    while not _shutdown.is_set():
        now = time.monotonic()
        now_wall = time.time()

        if now >= next_poll:
            next_poll = now + config.TRACER_POLL_SEC
            try:
                data = control_loop(tracer)
                logger.debug("PV=%.1fW Bat=%.2fV/%.1f°C/%d%% [%s]%s",
                             data.get("pv_power", 0), data.get("bat_voltage", 0),
                             data.get("bat_temp", 0), data.get("bat_soc", 0),
                             data.get("charge_status", ""),
                             " MOCK" if data.get("mock") else "")
            except Exception as e:
                logger.error("Tracer read error: %s", e)

        if now >= next_log:
            next_log = now + config.DATA_COLLECT_SEC
            status = webui.get_status()
            if status:
                try:
                    history_store.record(status)
                    logger.info("Logged: PV=%.1fW Bat=%.2fV/%.1f°C/%d%%",
                                status.get("pv_power", 0), status.get("bat_voltage", 0),
                                status.get("bat_temp", 0), status.get("bat_soc", 0))
                except Exception as e:
                    logger.error("history_store.record error: %s", e)

        # 毎時ロールアップ（時刻が次の時間帯に入ったら前の時間を集計）
        cur_hour_ts = (int(now_wall) // 3600) * 3600
        if cur_hour_ts > _last_hour_ts:
            try:
                history_store.rollup_hour(cur_hour_ts - 3600)
            except Exception as e:
                logger.error("rollup_hour error: %s", e)
            _last_hour_ts = cur_hour_ts

        # 日次バッチ（毎日 00:05 に前日分を HDD へ書き出し・prune）
        now_dt = datetime.now()
        today_0005 = int(
            datetime(now_dt.year, now_dt.month, now_dt.day, 0, 5).timestamp()
        )
        if now_wall >= today_0005 and _last_daily_ts < today_0005:
            try:
                history_store.rollup_day()
                history_store.daily_export_and_prune()
            except Exception as e:
                logger.error("daily_batch error: %s", e)
            _last_daily_ts = today_0005

        _shutdown.wait(timeout=1.0)

    logger.info("Shutting down...")
    tracer.close()
    logger.info("Done.")


if __name__ == "__main__":
    main()
