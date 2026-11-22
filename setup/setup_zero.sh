#!/usr/bin/env bash
# CarIoT 車載 Zero 2 W のセットアップ（新しいSD・OS再インストール後に実行）
#
# 前提: Raspberry Pi OS Lite 64bit (trixie) をユーザー pi で起動し、
#       このリポジトリを /home/pi/cariot に clone 済みであること。
# 使い方:
#   cd ~/cariot && ./setup/setup_zero.sh              # すべて実行
#   ./setup/setup_zero.sh --skip-wifi --skip-tailscale # 一部を省略
# 何度実行しても同じ状態になるように作ってある（再実行して構わない）。
# 手順の詳細・確認方法は docs/SETUP.md を参照。
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
FILES="$REPO/setup/files"
SKIP_WIFI=0; SKIP_TS=0
for a in "$@"; do
  case "$a" in
    --skip-wifi) SKIP_WIFI=1 ;;
    --skip-tailscale) SKIP_TS=1 ;;
    *) echo "不明なオプション: $a"; exit 2 ;;
  esac
done

step() { echo; echo "=== $*"; }

[ "$(id -un)" = "pi" ] || { echo "ユーザー pi で実行してください"; exit 1; }
[ "$REPO" = "/home/pi/cariot" ] || { echo "リポジトリは /home/pi/cariot に置いてください（cariot.service がこのパスを前提にしている）"; exit 1; }

step "1/10 APT パッケージ"
sudo apt-get update
sudo apt-get install -y \
  git python3-pip python3-serial python3-gps \
  gpsd gpsd-clients gpsd-tools \
  ffmpeg v4l-utils bluez network-manager \
  exfat-fuse exfatprogs hdparm log2ram

step "2/10 Python ライブラリ（requirements.txt のバージョンに固定）"
pip3 install --user --break-system-packages -r "$REPO/requirements.txt"

step "3/10 ユーザーのグループ（シリアル・BLE・カメラ）"
sudo usermod -aG dialout,bluetooth,video pi

step "4/10 udev ルール（/dev/ttyTracer, /dev/ttyGPS, HDD スピンダウン）"
sudo install -m 644 "$FILES/99-serial-fixed.rules" /etc/udev/rules.d/99-serial-fixed.rules
sudo install -m 644 "$FILES/69-hdparm.rules"       /etc/udev/rules.d/69-hdparm.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=tty

step "5/10 sudo 設定（cariot の再起動をパスワードなしで許可）"
tmp=$(mktemp)
cp "$FILES/011_cariot-nopasswd" "$tmp"
sudo visudo -cf "$tmp" >/dev/null
sudo install -m 440 "$tmp" /etc/sudoers.d/011_cariot-nopasswd
rm -f "$tmp"

step "6/10 ログ（journald の上限、log2ram）・gpsd"
sudo install -d /etc/systemd/journald.conf.d
sudo install -m 644 "$FILES/50-persistent-storage.conf" /etc/systemd/journald.conf.d/50-persistent-storage.conf
sudo systemctl restart systemd-journald
sudo systemctl enable log2ram >/dev/null 2>&1 || true
sudo install -m 644 "$FILES/gpsd.default" /etc/default/gpsd
sudo systemctl enable --now gpsd.socket >/dev/null

step "7/10 ストレージ（/mnt/storage、USB HDD は nofail でマウント）"
sudo install -d -o pi -g pi /mnt/storage /mnt/storage/tracer_log /mnt/storage/bms_log
FSTAB_LINE='UUID=40B0-BF8B /mnt/storage exfat-fuse defaults,nofail,uid=1000,gid=1000,umask=022 0 0'
if ! grep -q '/mnt/storage' /etc/fstab; then
  echo "$FSTAB_LINE" | sudo tee -a /etc/fstab >/dev/null
  echo "fstab に /mnt/storage を追加（HDD の UUID が違う場合は /etc/fstab を修正）"
fi

step "8/10 ネットワーク（Wi-Fi: 自宅=優先度10、ZTR01=優先度1 / 有線LAN: 再試行無制限）"
if [ "$SKIP_WIFI" = 0 ]; then
  [ -f "$REPO/setup/secrets.env" ] && . "$REPO/setup/secrets.env"
  : "${WIFI_HOME_SSID:=pr500m-889e37-1}"
  : "${WIFI_ZTR01_SSID:=SPWH_L11_183D74}"
  [ -n "${WIFI_HOME_PSK:-}" ]  || { read -rsp "自宅 Wi-Fi ($WIFI_HOME_SSID) のパスワード: " WIFI_HOME_PSK; echo; }
  [ -n "${WIFI_ZTR01_PSK:-}" ] || { read -rsp "ZTR01 Wi-Fi ($WIFI_ZTR01_SSID) のパスワード: " WIFI_ZTR01_PSK; echo; }
  wifi_profile() {  # name ssid psk priority
    if nmcli -t -f NAME connection show | grep -qx "$1"; then
      sudo nmcli connection modify "$1" 802-11-wireless.ssid "$2" wifi-sec.key-mgmt wpa-psk \
        wifi-sec.psk "$3" connection.autoconnect yes connection.autoconnect-priority "$4"
    else
      sudo nmcli connection add type wifi con-name "$1" ifname wlan0 ssid "$2" \
        wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$3" \
        connection.autoconnect yes connection.autoconnect-priority "$4" >/dev/null
    fi
    echo "Wi-Fi プロファイル: $1（優先度 $4）"
  }
  # 自宅は Imager で作られたプロファイル名が違うことがあるため、SSID が同じものがあればそれを使う
  home_name=$(nmcli -t -f NAME,TYPE connection show | awk -F: '$2=="802-11-wireless"{print $1}' |
    while read -r n; do [ "$(nmcli -g 802-11-wireless.ssid connection show "$n")" = "$WIFI_HOME_SSID" ] && echo "$n"; done | head -1)
  wifi_profile "${home_name:-$WIFI_HOME_SSID}" "$WIFI_HOME_SSID" "$WIFI_HOME_PSK" 10
  wifi_profile "$WIFI_ZTR01_SSID" "$WIFI_ZTR01_SSID" "$WIFI_ZTR01_PSK" 1
else
  echo "（--skip-wifi のため Wi-Fi は変更しない）"
fi
# 有線LAN（USB-Ethernet を ZTR01 の LAN 端子へ）: ZTR01 の起動が遅れても繋がるまで再試行
nmcli -t -f NAME,TYPE connection show | awk -F: '$2=="802-3-ethernet"{print $1}' | while read -r n; do
  sudo nmcli connection modify "$n" connection.autoconnect yes connection.autoconnect-retries 0
  echo "有線LAN プロファイル: $n（再試行無制限）"
done

step "9/10 cariot サービス"
sudo install -m 644 "$REPO/cariot.service" /etc/systemd/system/cariot.service
sudo systemctl daemon-reload
sudo systemctl enable cariot >/dev/null
[ -f "$REPO/settings.json" ] || echo "settings.json がないのでデフォルト設定で起動する（バックアップがあれば $REPO/settings.json に置く）"
sudo systemctl restart cariot

step "10/10 Tailscale"
if [ "$SKIP_TS" = 0 ]; then
  if ! command -v tailscale >/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
  fi
  # 自宅LANのサブネットルーターは Raspi5 が担当。車載 Zero はルートを受け取らない。
  sudo tailscale up --accept-routes=false || true
  echo "Tailscale 管理画面で、この端末の Disable key expiry を設定すること（docs/SETUP.md 参照）"
else
  echo "（--skip-tailscale のため Tailscale は設定しない）"
fi

echo
echo "完了。グループの変更を反映するため一度再起動すること: sudo reboot"
echo "再起動後の確認項目は docs/SETUP.md の「動作確認」を参照。"
