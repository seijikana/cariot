# Raspberry Pi SSH セットアップメモ

## 接続情報

| 項目 | 値 |
|---|---|
| ホスト名 | `RasberryPiZero2WHLite.local` |
| ユーザー名 | `pi` |
| 接続コマンド | `ssh pi@RasberryPiZero2WHLite.local` |
| 認証方式 | SSH公開鍵認証（パスワード不要） |
| OS | Raspberry Pi OS Bookworm（64bit / aarch64） |

---

## セットアップの手順（やったこと）

### 1. Pi 側で SSH を有効化

Pi の初回セットアップ時（Raspberry Pi Imager）に SSH を有効化した、または：

```bash
# Pi に直接ログインして有効化
sudo systemctl enable ssh
sudo systemctl start ssh
```

または `raspi-config` → `Interface Options` → `SSH` → `Enable`

### 2. Windows 側で SSH 鍵ペアを生成

PowerShell で実行：

```powershell
ssh-keygen -t ed25519 -C "seiiiji0210@gmail.com"
# 保存先: C:\Users\SEIJI\.ssh\id_ed25519
# パスフレーズは空エンターでOK（省略可）
```

生成されるファイル：

| ファイル | 説明 |
|---|---|
| `~\.ssh\id_ed25519` | 秘密鍵（絶対に外に出さない） |
| `~\.ssh\id_ed25519.pub` | 公開鍵（Pi に登録するもの） |

### 3. 公開鍵を Pi に登録

```powershell
# Windows から Pi へ公開鍵をコピー
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh pi@RasberryPiZero2WHLite.local "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

または Pi に直接ログインして：

```bash
mkdir -p ~/.ssh
nano ~/.ssh/authorized_keys
# 公開鍵の内容を貼り付けて保存
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
```

### 4. 接続確認

```powershell
ssh pi@RasberryPiZero2WHLite.local
```

パスワードなしで入れれば成功。

---

## よく使うコマンド

### SSH接続

```powershell
# 接続
ssh pi@RasberryPiZero2WHLite.local

# コマンドをリモートで1行実行（接続してすぐ終了）
ssh pi@RasberryPiZero2WHLite.local "sudo systemctl status doll-ai"
```

### ファイル転送（SCP）

```powershell
# PC → Pi（単一ファイル）
scp C:\Users\SEIJI\Documents\doll-ai\main.py pi@RasberryPiZero2WHLite.local:/home/pi/doll-ai/main.py

# PC → Pi（複数ファイル）
scp main.py setup.sh requirements.txt pi@RasberryPiZero2WHLite.local:/home/pi/doll-ai/

# Pi → PC（ログ一括取得）
scp "pi@RasberryPiZero2WHLite.local:/home/pi/doll-ai/logs/*.txt" "C:\Users\SEIJI\Documents\doll-ai\logs\"
```

---

## 用語集

| 用語 | 意味 |
|---|---|
| **SSH** | ネットワーク越しに別のPCをコマンド操作するしくみ。通信は暗号化されている |
| **公開鍵認証** | パスワードの代わりに「鍵のペア」で認証する方式。パスワードより安全で便利 |
| **秘密鍵** | 手元（Windows PC）だけに置く鍵。絶対に人に渡さない |
| **公開鍵** | Pi に登録する鍵。流出しても問題ない |
| **authorized_keys** | Pi 側に置く「入っていい公開鍵のリスト」ファイル |
| **mDNS（.local）** | IPアドレスを調べなくても `ホスト名.local` で接続できる仕組み |
| **SCP** | SSH を使ったファイルコピーコマンド。暗号化されて転送される |

---

## ホスト名（.local）が解決できないとき

`.local` のホスト名解決には mDNS（Bonjour）が必要。

```powershell
# 原因1: 同じWiFiに繋がっていない → 接続を確認
# 原因2: Bonjourサービスが止まっている
Get-Service "Bonjour Service" | Start-Service

# 解決しない場合はIPアドレスを直接使う
# Pi側でIPを調べる（HDMIまたはルーターの管理画面で確認）
ssh pi@192.168.x.x
```

## Pi のIPアドレスを調べる方法

Pi 側のターミナルで：

```bash
hostname -I
# 例: 192.168.1.42
```

または Pi に画面を繋いでいればログイン時に表示される。

---

## Pi の基本操作（SSHログイン後）

```bash
# doll-aiサービス操作
sudo systemctl start   doll-ai    # 起動
sudo systemctl stop    doll-ai    # 停止
sudo systemctl restart doll-ai    # 再起動
sudo systemctl status  doll-ai    # 状態確認
journalctl -u doll-ai -f          # ログをリアルタイム表示

# WiFi変更（Bookworm）
sudo nmcli device wifi connect "SSID名" password "パスワード"

# 再起動 / シャットダウン
sudo reboot
sudo shutdown -h now
```
