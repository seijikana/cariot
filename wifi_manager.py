"""WiFi管理モジュール

NetworkManager経由でWiFiを制御する。
接続先不在が続くとAPモードを起動し、WebUIからWiFi設定を変更できる。
"""
import subprocess
import threading
import time
import logging

import config

logger = logging.getLogger(__name__)

AP_CON_NAME = "cariot-hotspot"

_lock = threading.Lock()
_ap_active = False


def _nmcli(*args, sudo=False):
    cmd = (["sudo"] if sudo else []) + ["nmcli"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True)


def _sync_ap_state():
    global _ap_active
    r = _nmcli("-t", "-f", "name", "connection", "show", "--active")
    _ap_active = any(AP_CON_NAME == line.strip() for line in r.stdout.splitlines())


def get_wifi_status() -> dict:
    """現在のWiFi状態を返す"""
    r = _nmcli("-t", "-f", "active,ssid", "dev", "wifi")
    connected_ssid = None
    for line in r.stdout.splitlines():
        parts = line.split(":", 1)
        if len(parts) == 2 and parts[0] == "yes" and parts[1]:
            connected_ssid = parts[1]
            break

    r2 = _nmcli("-t", "-f", "IP4.ADDRESS", "dev", "show", "wlan0")
    local_ip = None
    for line in r2.stdout.splitlines():
        if "IP4.ADDRESS" in line:
            val = line.split(":", 1)[-1].strip()
            local_ip = val.split("/")[0] if val else None
            break

    ap = _ap_active
    return {
        "connected_ssid": connected_ssid,
        "ap_mode": ap,
        "ap_ssid": config.AP_SSID if ap else None,
        "ap_ip": config.AP_IP if ap else None,
        "ap_password": config.AP_PASSWORD if ap else None,
        "local_ip": local_ip,
    }


def get_networks() -> list:
    """保存済みWiFiネットワーク一覧（APホットスポット除く）"""
    r = _nmcli("-t", "-f", "name,type,autoconnect-priority", "connection", "show")
    networks = []
    for line in r.stdout.splitlines():
        # name にコロンが含まれる場合に備えて後ろから分割
        parts = line.rsplit(":", 2)
        if len(parts) == 3 and parts[1] == "wifi" and parts[0] != AP_CON_NAME:
            try:
                priority = int(parts[2])
            except ValueError:
                priority = 0
            networks.append({"name": parts[0], "priority": priority})
    networks.sort(key=lambda x: -x["priority"])
    return networks


def scan_networks() -> list:
    """周囲のWiFiネットワークをスキャンして返す（SSID一覧）"""
    r = _nmcli("-t", "-f", "ssid,signal", "dev", "wifi", "list")
    seen = set()
    results = []
    for line in r.stdout.splitlines():
        parts = line.rsplit(":", 1)
        if len(parts) == 2 and parts[0] and parts[0] not in seen:
            seen.add(parts[0])
            try:
                signal = int(parts[1])
            except ValueError:
                signal = 0
            results.append({"ssid": parts[0], "signal": signal})
    results.sort(key=lambda x: -x["signal"])
    return results


def add_network(ssid: str, password: str, priority: int = 10) -> tuple:
    """WiFiネットワークを追加・更新する。戻り値: (ok, error_msg)"""
    r = _nmcli("connection", "show", ssid)
    if r.returncode == 0:
        r2 = _nmcli("connection", "modify", ssid,
                    "wifi-sec.psk", password,
                    "connection.autoconnect-priority", str(priority),
                    sudo=True)
        if r2.returncode != 0:
            return False, r2.stderr.strip() or r2.stdout.strip()
    else:
        r2 = _nmcli("connection", "add",
                    "type", "wifi",
                    "con-name", ssid,
                    "ifname", "wlan0",
                    "ssid", ssid,
                    "wifi-sec.key-mgmt", "wpa-psk",
                    "wifi-sec.psk", password,
                    "connection.autoconnect", "yes",
                    "connection.autoconnect-priority", str(priority),
                    sudo=True)
        if r2.returncode != 0:
            return False, r2.stderr.strip() or r2.stdout.strip()
    return True, ""


def delete_network(name: str) -> tuple:
    r = _nmcli("connection", "delete", name, sudo=True)
    if r.returncode != 0:
        return False, r.stderr.strip() or r.stdout.strip()
    return True, ""


def connect_to(name: str) -> tuple:
    """指定ネットワークへ接続（APモードを先に停止）"""
    _do_stop_ap()
    r = _nmcli("connection", "up", name, sudo=True)
    if r.returncode != 0:
        return False, r.stderr.strip() or r.stdout.strip()
    return True, ""


def _do_stop_ap():
    global _ap_active
    _nmcli("connection", "down", AP_CON_NAME, sudo=True)
    _nmcli("connection", "delete", AP_CON_NAME, sudo=True)
    _ap_active = False


def start_ap() -> tuple:
    global _ap_active
    with _lock:
        if _ap_active:
            return True, ""
        logger.info("APモード起動: SSID=%s IP=%s", config.AP_SSID, config.AP_IP)
        _nmcli("connection", "delete", AP_CON_NAME, sudo=True)

        # オープンネットワーク（パスワードなし）＋カスタムIPでAP作成
        r = _nmcli("connection", "add",
                   "type", "wifi",
                   "con-name", AP_CON_NAME,
                   "ifname", "wlan0",
                   "ssid", config.AP_SSID,
                   "mode", "ap",
                   "ipv4.method", "shared",
                   "ipv4.addresses", f"{config.AP_IP}/24",
                   "ipv6.method", "disabled",
                   sudo=True)
        if r.returncode != 0:
            err = r.stderr.strip() or r.stdout.strip()
            logger.error("AP接続プロファイル作成失敗: %s", err)
            return False, err

        r2 = _nmcli("connection", "up", AP_CON_NAME, sudo=True)
        if r2.returncode != 0:
            _nmcli("connection", "delete", AP_CON_NAME, sudo=True)
            err = r2.stderr.strip() or r2.stdout.strip()
            logger.error("APモード起動失敗: %s", err)
            return False, err

        _ap_active = True
        logger.info("APモード起動完了")
        return True, ""


def stop_ap() -> tuple:
    global _ap_active
    with _lock:
        if not _ap_active:
            return True, ""
        _do_stop_ap()
        logger.info("APモード停止完了")
        return True, ""


def monitor_loop(shutdown_event: threading.Event):
    """WiFi接続監視ループ。未接続が AP_WAIT_SEC 秒続くとAPモードを自動起動する。"""
    _sync_ap_state()
    disconnected_since = None

    while not shutdown_event.is_set():
        try:
            if _ap_active:
                disconnected_since = None
            else:
                st = get_wifi_status()
                if st["connected_ssid"]:
                    disconnected_since = None
                else:
                    if disconnected_since is None:
                        disconnected_since = time.monotonic()
                        logger.warning("WiFi未接続を検出（%ds後にAPモード起動）", config.AP_WAIT_SEC)
                    elif time.monotonic() - disconnected_since >= config.AP_WAIT_SEC:
                        logger.warning("%.0fs間未接続 → APモード自動起動", config.AP_WAIT_SEC)
                        start_ap()
                        disconnected_since = None
        except Exception as e:
            logger.error("WiFiモニター例外: %s", e)

        shutdown_event.wait(10)
