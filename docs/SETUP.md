# 車載 Zero 2 W セットアップ・復旧手順

SD カードの故障・交換、OS の入れ直しのときに、この手順で元の状態に戻す。
自動化できる部分は `setup/setup_zero.sh` にまとめてある（何度実行しても同じ状態になる）。

> このリポジトリは公開。Wi-Fi のパスワードなどの秘密の情報は書かない・コミットしない。

## 構成（2026-11 時点）

| 項目 | 内容 |
|---|---|
| 機体 | Raspberry Pi Zero 2 W（ホスト名 `RasberryPiZero2WHLite`、ユーザー `pi`） |
| OS | Raspberry Pi OS Lite 64bit（Debian 13 trixie） |
| Tailscale | `rasberrypizero2whlite`（100.126.231.82）、鍵の期限なし |
| ネットワーク | Wi-Fi: 自宅（優先度10）、ZTR01 `SPWH_L11_183D74`（優先度1）。有線: USB-Ethernet（ASIX AX88179）→ ZTR01 の LAN 端子 |
| USB（ハブ経由） | Tracer の USB-RS485（CH9102 → `/dev/ttyTracer`）、GPS u-blox 7（`/dev/ttyGPS`）、USB カメラ（MJPEG `/dev/video0`）、RTL-SDR |
| BLE | JBD BMS ×2（MAC は `bms.py` の `_BMS_LIST`） |
| アプリ | `/home/pi/cariot`、`cariot.service`、Web UI ポート 5000 |
| データ | `history.db`（直近の履歴）、`settings.json`（画面で変えた設定）、`/mnt/storage/tracer_log`（USB HDD） |

## 1. SD カードに OS を書く

Raspberry Pi Imager で次のように設定して書き込む。

- OS: Raspberry Pi OS Lite (64-bit)
- ホスト名: `RasberryPiZero2WHLite`
- ユーザー名: `pi`
- Wi-Fi: 自宅の SSID とパスワード、国 `JP`
- SSH: 有効。**公開鍵認証のみ**にして、Raspi5 の `~/.ssh/id_ed25519_raspizero.pub` の中身を登録する
- タイムゾーン: `Asia/Tokyo`

## 2. 初回起動とリポジトリの取得

自宅の Wi-Fi に繋がったら、Raspi5 から LAN 経由で入る（Tailscale はまだ無い）。

```bash
ssh -i ~/.ssh/id_ed25519_raspizero pi@RasberryPiZero2WHLite.local   # 名前で引けなければルーターでIPを確認
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/seijikana/cariot ~/cariot
```

## 3. バックアップの書き戻し（あれば）

Raspi5 にバックアップがあれば、セットアップの前に戻す（取り方は「6. バックアップ」）。

```bash
# Raspi5 で実行
B=~/zero2-backup/<日付>
scp -i ~/.ssh/id_ed25519_raspizero $B/settings.json pi@<ZeroのIP>:cariot/
scp -i ~/.ssh/id_ed25519_raspizero $B/history.db    pi@<ZeroのIP>:cariot/   # 履歴を残したい場合のみ
```

`settings.json` が無くても動く（温度・電圧のしきい値などがデフォルトに戻るので、画面の「設定」で直す）。

## 4. セットアップスクリプトの実行

```bash
cd ~/cariot
cp setup/secrets.env.example setup/secrets.env   # 省略可。省略すると実行中にパスワードを聞かれる
nano setup/secrets.env                            # Wi-Fi のパスワードを記入
./setup/setup_zero.sh
sudo reboot
```

スクリプトがやること:

1. APT パッケージ（gpsd、ffmpeg、v4l-utils、bluez、log2ram、exfat-fuse、hdparm など）
2. Python ライブラリ（`requirements.txt` のバージョンに固定。pymodbus は版で API が変わるので固定が必須）
3. `pi` を `dialout`、`bluetooth`、`video` グループに追加
4. udev ルール（`/dev/ttyTracer`、`/dev/ttyGPS`、HDD のスピンダウン）
5. sudo 設定（cariot の再起動をパスワードなしで許可）
6. journald の上限（50MB）、log2ram、gpsd の設定
7. `/mnt/storage` の作成と fstab への追加（USB HDD、`nofail`）
8. Wi-Fi プロファイル（自宅=優先度10、ZTR01=優先度1）と有線 LAN の再試行無制限
9. `cariot.service` の登録と起動
10. Tailscale の導入と `tailscale up --accept-routes=false`（表示された URL をブラウザで開いてログイン）

`setup/secrets.env` は作業が終わったら消してよい（`.gitignore` 済みでコミットはされない）。

## 5. Tailscale の後始末

- 新しく入れ直した場合、Tailscale の IP が変わる。管理画面（https://login.tailscale.com/admin/machines）で、**古い `rasberrypizero2whlite` を削除**してから新しい端末の名前を `rasberrypizero2whlite` に直す。
- 新しい端末の「…」メニューから **Disable key expiry** を設定する（しないと約半年で遠隔から見えなくなる）。
- 同じ IP（100.126.231.82）を保ちたい場合は、バックアップした `/var/lib/tailscale/tailscaled.state` を `tailscale up` の**前**に戻す（「6. バックアップ」）。古いカードと同時に起動しないこと。

## 6. バックアップ（Raspi5 で定期的に実行）

秘密の情報を含むので GitHub には置かず、Raspi5 に保存する。

```bash
B=~/zero2-backup/$(date +%Y%m%d); mkdir -p $B && chmod 700 $B
Z="ssh -i ~/.ssh/id_ed25519_raspizero pi@100.126.231.82"
scp -i ~/.ssh/id_ed25519_raspizero pi@100.126.231.82:'cariot/settings.json cariot/history.db' $B/
$Z 'sudo tar -C / -czf - var/lib/tailscale etc/NetworkManager/system-connections' > $B/zero-secrets.tgz
chmod 600 $B/*
```

SD カードを丸ごと複製しておく方法もある（USB カードリーダーが必要）。`rpi-clone` で動作中の Zero から別カードへ複製できる。

## 7. 動作確認

再起動後、Raspi5 から次を確認する。

```bash
ssh -i ~/.ssh/id_ed25519_raspizero pi@100.126.231.82 '
  systemctl is-active cariot gpsd.socket tailscaled
  ls -l /dev/ttyTracer /dev/ttyGPS
  journalctl -u cariot -b -o cat | grep -E "Tracer connected|mock|BMS bms[12] (connected|online)" | tail -5
  vcgencmd get_throttled'
```

| 確認項目 | 期待する結果 |
|---|---|
| Tracer | `Tracer connected on /dev/ttyTracer`（`mock mode` なら Tracer 未接続） |
| BMS | `bms1`、`bms2` とも `connected` / `online=True` |
| GPS | ダッシュボードの GPS カードに 3D 測位と地図 |
| カメラ | ダッシュボードのカメラカードに画像 |
| 電源 | `throttled=0x0` |
| Web UI | `http://100.126.231.82:5000/` |

## 8. OS を更新するとき

```bash
sudo apt-get update && sudo apt-get full-upgrade -y
sudo reboot
```

- 更新後に「7. 動作確認」を行う。
- Python ライブラリは `pip --user` で入れていて、apt では更新されない。上げるときは `requirements.txt` のバージョンを変えて自宅で試してからにする（特に pymodbus と bleak）。
- 大きな OS の更新（Debian のメジャーバージョンが変わるもの）は、上書き更新より新しい SD に入れ直す方が安全。この手順書の 1〜7 をやる。

## 9. よくある問題

| 症状 | 原因と対処 |
|---|---|
| 画面に `MOCK` と出る | 起動時に Tracer が無かった。USB を確認して `sudo systemctl restart cariot` |
| BMS が `not found` | BMS の Bluetooth モジュールを交換すると MAC が変わる。cariot を止めて BLE をスキャンし（`python3 -c "import asyncio,bleak;print(asyncio.run(bleak.BleakScanner.discover(10)))"`、名前が `xiaoxiang` のもの）、`bms.py` の `_BMS_LIST` を直す |
| ZTR01 に繋がらない | Wi-Fi のパスワード違い。`sudo nmcli connection modify SPWH_L11_183D74 wifi-sec.psk '<新しいパスワード>'`。有線 LAN を ZTR01 に挿せば Wi-Fi 無しでも繋がる |
| Tailscale で見えない | 鍵の期限切れ、または ZTR01 の回線断。管理画面で端末の状態を確認 |
| `/dev/ttyTracer` が無い | USB-RS485 の VID:PID が変わった可能性。`lsusb` で確認して `setup/files/99-serial-fixed.rules` を直す |
