"""history_store.py - SQLite-based power history storage

SD card (/home/pi/cariot/history.db):
  minute  - per-minute raw samples, 48h rolling buffer
  rollup  - hour/day/week/month aggregates, permanent

HDD (/mnt/storage/tracer_log/tracer_YYYYMMDD.csv):
  daily batch export of minute rows, written once at 00:05
"""
import csv
import logging
import os
import sqlite3
import threading
from calendar import monthrange
from datetime import datetime, timedelta
from typing import Optional

import config
import settings_store

logger = logging.getLogger(__name__)

DB_PATH = getattr(config, "HISTORY_DB_PATH", "/home/pi/cariot/history.db")
_MINUTE_KEEP_SEC = 48 * 3600
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def _wh(rows, col):
    """Sum of column values / 60 → Wh (each row = 1-minute sample)."""
    return round(sum(r[col] for r in rows if r[col] is not None) / 60, 3)


def _avg(rows, col):
    vals = [r[col] for r in rows if r[col] is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def _min(rows, col):
    vals = [r[col] for r in rows if r[col] is not None]
    return round(min(vals), 3) if vals else None


def _max(rows, col):
    vals = [r[col] for r in rows if r[col] is not None]
    return round(max(vals), 3) if vals else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_db():
    """Create tables if they don't exist. Call once at startup."""
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    with _lock:
        with _conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS minute (
                    ts          INTEGER PRIMARY KEY,
                    pv_w        REAL,
                    chg_w       REAL,
                    load_tr_w   REAL,
                    load_bms_w  REAL,
                    bat_v       REAL,
                    bat_temp    REAL
                );
                CREATE TABLE IF NOT EXISTS rollup (
                    scale       TEXT,
                    ts          INTEGER,
                    pv_wh       REAL,
                    chg_wh      REAL,
                    load_tr_wh  REAL,
                    load_bms_wh REAL,
                    bat_v_avg   REAL,
                    bat_v_min   REAL,
                    bat_v_max   REAL,
                    temp_avg    REAL,
                    temp_min    REAL,
                    temp_max    REAL,
                    PRIMARY KEY (scale, ts)
                );
            """)
    logger.info("history_store: DB ready at %s", DB_PATH)


def record(status: dict):
    """Insert one per-minute sample. Idempotent (INSERT OR REPLACE)."""
    now = datetime.now()
    ts = int(datetime(now.year, now.month, now.day, now.hour, now.minute).timestamp())

    pv_w = float(status.get("pv_power") or 0)
    chg_w = float(status.get("bat_power") or 0)
    load_tr_w = float(status.get("load_power") or 0)

    load_bms_w = 0.0
    for b in (status.get("bms") or {}).values():
        pw = (b or {}).get("pack_w")
        if pw is not None and pw < 0:
            load_bms_w += abs(pw)
    bms_thr = settings_store.get().get("bms_load_threshold_w", config.BMS_LOAD_THRESHOLD_W)
    if load_bms_w < bms_thr:
        load_bms_w = 0.0

    bat_v = float(status.get("bat_voltage") or 0)
    bat_temp = status.get("bat_temp")

    with _lock:
        with _conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO minute VALUES (?,?,?,?,?,?,?)",
                (ts, round(pv_w, 2), round(chg_w, 2), round(load_tr_w, 2),
                 round(load_bms_w, 2), round(bat_v, 3), bat_temp),
            )


def rollup_hour(hour_ts: Optional[int] = None):
    """Aggregate minute rows for one hour into rollup scale='hour'.
    Defaults to the previous complete hour.
    """
    if hour_ts is None:
        prev = datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        hour_ts = int(prev.timestamp())
    end_ts = hour_ts + 3600

    with _lock:
        with _conn() as c:
            rows = c.execute(
                "SELECT pv_w,chg_w,load_tr_w,load_bms_w,bat_v,bat_temp "
                "FROM minute WHERE ts>=? AND ts<?",
                (hour_ts, end_ts),
            ).fetchall()

    if not rows:
        return

    with _lock:
        with _conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO rollup VALUES ('hour',?,?,?,?,?,?,?,?,?,?,?)",
                (hour_ts,
                 _wh(rows, 0), _wh(rows, 1), _wh(rows, 2), _wh(rows, 3),
                 _avg(rows, 4), _min(rows, 4), _max(rows, 4),
                 _avg(rows, 5), _min(rows, 5), _max(rows, 5)),
            )
    logger.info("history_store: hour rollup ts=%d n=%d rows", hour_ts, len(rows))


def _upsert_rollup_from_children(scale: str, period_ts: int,
                                  child_scale: str, child_start: int, child_end: int):
    """Aggregate child_scale rollup rows into (scale, period_ts)."""
    with _lock:
        with _conn() as c:
            rows = c.execute(
                "SELECT pv_wh,chg_wh,load_tr_wh,load_bms_wh,"
                "bat_v_avg,bat_v_min,bat_v_max,temp_avg,temp_min,temp_max "
                "FROM rollup WHERE scale=? AND ts>=? AND ts<?",
                (child_scale, child_start, child_end),
            ).fetchall()

    if not rows:
        return

    def s(col): return round(sum(r[col] for r in rows if r[col] is not None), 3)

    with _lock:
        with _conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO rollup VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (scale, period_ts,
                 s(0), s(1), s(2), s(3),
                 _avg(rows, 4), _min(rows, 5), _max(rows, 6),
                 _avg(rows, 7), _min(rows, 8), _max(rows, 9)),
            )
    logger.info("history_store: %s rollup ts=%d n=%d rows", scale, period_ts, len(rows))


def rollup_day(date: Optional[datetime] = None):
    """Roll up hour→day, then upsert the containing week and month."""
    if date is None:
        date = datetime.now() - timedelta(days=1)
    day_start = datetime(date.year, date.month, date.day)
    day_ts = int(day_start.timestamp())

    _upsert_rollup_from_children("day", day_ts, "hour", day_ts, day_ts + 86400)

    monday = day_start - timedelta(days=day_start.weekday())
    week_ts = int(monday.timestamp())
    _upsert_rollup_from_children("week", week_ts, "day", week_ts, week_ts + 7 * 86400)

    month_start = datetime(date.year, date.month, 1)
    month_ts = int(month_start.timestamp())
    _, days_in_month = monthrange(date.year, date.month)
    _upsert_rollup_from_children("month", month_ts, "day", month_ts,
                                  month_ts + days_in_month * 86400)


def daily_export_and_prune():
    """Export yesterday's minute rows to HDD CSV, then delete rows older than 48h."""
    yesterday = datetime.now() - timedelta(days=1)
    day_start = datetime(yesterday.year, yesterday.month, yesterday.day)
    day_ts = int(day_start.timestamp())
    day_end = day_ts + 86400

    os.makedirs(config.TRACER_LOG_DIR, exist_ok=True)
    fname = os.path.join(config.TRACER_LOG_DIR,
                         f"tracer_{yesterday.strftime('%Y%m%d')}.csv")
    try:
        with _lock:
            with _conn() as c:
                rows = c.execute(
                    "SELECT ts,pv_w,chg_w,load_tr_w,load_bms_w,bat_v,bat_temp "
                    "FROM minute WHERE ts>=? AND ts<? ORDER BY ts",
                    (day_ts, day_end),
                ).fetchall()

        if rows:
            with open(fname, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["timestamp", "pv_w", "chg_w", "load_tr_w",
                             "load_bms_w", "bat_v", "bat_temp"])
                for r in rows:
                    ts_str = datetime.fromtimestamp(r[0]).isoformat(timespec="seconds")
                    w.writerow([ts_str] + list(r[1:]))
            logger.info("history_store: exported %d rows → %s", len(rows), fname)
    except Exception as e:
        logger.error("history_store: export failed: %s", e)

    cutoff = int(datetime.now().timestamp()) - _MINUTE_KEEP_SEC
    with _lock:
        with _conn() as c:
            deleted = c.execute("DELETE FROM minute WHERE ts<?", (cutoff,)).rowcount
    logger.info("history_store: pruned %d old minute rows", deleted)


def query(scale: str, before: Optional[int] = None, limit: int = 0) -> dict:
    """Return up to `limit` points ending before `before` (epoch).
    Points are in chronological order.
    Returns {"scale", "points": [...], "has_more": bool}
    """
    defaults = {"minute": 120, "hour": 72, "day": 60, "week": 52, "month": 24}
    if limit <= 0:
        limit = defaults.get(scale, 120)
    limit = min(limit, 500)
    fetch = limit + 1

    if before is None:
        before = int(datetime.now().timestamp()) + 1

    with _lock:
        with _conn() as c:
            if scale == "minute":
                rows = c.execute(
                    "SELECT ts,pv_w,chg_w,load_tr_w,load_bms_w,bat_v,bat_temp "
                    "FROM minute WHERE ts<? ORDER BY ts DESC LIMIT ?",
                    (before, fetch),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT ts,pv_wh,chg_wh,load_tr_wh,load_bms_wh,bat_v_avg,temp_avg "
                    "FROM rollup WHERE scale=? AND ts<? ORDER BY ts DESC LIMIT ?",
                    (scale, before, fetch),
                ).fetchall()

    has_more = len(rows) > limit
    rows = list(reversed(rows[:limit]))

    if scale == "minute":
        def _pt(r):
            return {"t": r[0], "pv": r[1], "chg": r[2],
                    "load_tr": r[3], "load_bms": r[4],
                    "bat_v": r[5], "bat_temp": r[6]}
    else:
        def _pt(r):
            return {"t": r[0], "pv": r[1], "chg": r[2], "load_tr": r[3],
                    "load_bms": r[4], "bat_v": r[5], "bat_temp": r[6]}

    points = [_pt(r) for r in rows]
    return {"scale": scale, "points": points, "has_more": has_more}


def backfill_rollups():
    """Generate any missing hour/day/week/month rollups for the past 7 days.
    Called once on startup to recover from downtime.
    """
    now = datetime.now()
    for delta in range(1, 8):
        date = now - timedelta(days=delta)
        day_start = datetime(date.year, date.month, date.day)
        day_ts = int(day_start.timestamp())

        with _lock:
            with _conn() as c:
                exists = c.execute(
                    "SELECT 1 FROM rollup WHERE scale='day' AND ts=?", (day_ts,)
                ).fetchone()

        if not exists:
            for h in range(24):
                rollup_hour(day_ts + h * 3600)
            rollup_day(date)
            logger.info("history_store: backfilled rollup for %s", date.date())
