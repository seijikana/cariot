# 実装フェーズ別手順書

## ⓪ Raspiセットアップ + Tailscale環境整備 ✅ 完了

### 完了済み内容

```
✅ Raspberry Pi OS Lite 64bit インストール
✅ 必要パッケージインストール
✅ Pythonライブラリインストール
✅ I2C・UART有効化
✅ Tailscaleインストール・認証（100.126.231.82）
✅ WiFi自動切替設定
   優先度10: pr500m-889e37-1（自宅ルーター）
   優先度 1: SPWH_L11_183D74（ZTR01）
✅ 2.5インチHDD マウント（/mnt/storage UUID=40B0-BF8B）
✅ 自動マウント設定（/etc/fstab）
✅ ストレージディレクトリ作成
```

### 実機情報

```
ホスト名: RasberryPiZero2WHLite
Tailscale IP: 100.126.231.82
SSH: ssh pi@100.126.231.82
ストレージ: /dev/sda1 → /mnt/storage（465.7GB exFAT）
```

---

## ① Tracer MPPT 温度制御・発電充電監視 + Flask WebUI基盤

### 目標

- RS-485 Modbus経由でTracer 3210Aのデータを取得
- バッテリー温度（RTS）に応じてヒステリシス充電制御
- Flask WebUIダッシュボード基盤を構築（①で土台・以降のフェーズで拡張）
- Tailscale経由でスマホ・自宅PCからアクセス可能

### 接続確認

```bash
# USB-RS485アダプター認識確認
ls /dev/ttyUSB*
# → /dev/ttyUSB0 が表示されればOK

# ユーザーをdialoutグループに追加
sudo usermod -aG dialout pi
```

### 実装内容

```
tracer.py    # Tracer Modbusモジュール（読み取り・充電制御）
webui.py     # Flask WebUI（ダッシュボード・/api/status・/files）
main.py      # メインループ（データ収集・制御）
```

### Flask WebUI エンドポイント（①で実装）

| エンドポイント | 内容 |
|---|---|
| GET / | ダッシュボードHTML（Tracer情報表示） |
| GET /api/status | 全センサーデータ JSON |
| GET /files | ファイル一覧（DL用） |
| GET /files/dl/<path> | ファイルDL |

### 確認チェックリスト ①

- [ ] RTS300R47K3.81A 購入・バッテリーに取り付け
- [ ] USB-RS485アダプター接続・/dev/ttyUSB0認識
- [ ] test_tracer.pyでバッテリー温度・PV電圧取得確認
- [ ] 充電停止・再開ヒステリシス制御動作確認
- [ ] Flask WebUI起動確認
- [ ] http://100.126.231.82:5000 でダッシュボード表示確認
- [ ] /api/status でJSONデータ取得確認
- [ ] systemdサービス自動起動確認

---

## ② JBD BMS Bluetooth ミラーリング

### 目標

- JBD BMSからBLE経由でセル電圧・電流・SOC・温度を取得
- WebUIダッシュボードにBMSデータを追加表示

### BMS MAC アドレス確認

```bash
sudo bluetoothctl
scan on
# JBD または SmartBMS という名前のデバイスを探す
# MACアドレスをメモ → config.pyに記入
```

### 確認チェックリスト ②

- [ ] BMS MACアドレス確認・config.pyに記入
- [ ] test_bms.pyでBLEスキャン確認
- [ ] 基本情報取得確認（電圧・電流・SOC）
- [ ] セル電圧取得確認
- [ ] WebUIダッシュボードにBMSデータ追加表示確認
- [ ] WiFi+BLE干渉有無確認
- [ ] （干渉時）USB Bluetoothドングル追加

---

## ③ カメラ・GPS・IMU監視

### 目標

- GPS位置追跡・走行/停車自動判定
- 停車中のみ動体検知JPEG保存
- 衝撃検知時に前後2分の動画保存（循環バッファ）
- WebUIダッシュボードにGPS情報追加

### GPS確認

```bash
sudo gpsd /dev/ttyAMA0 -F /var/run/gpsd.sock
cgps -s   # 車外・開空地で確認
```

### IMU確認

```bash
i2cdetect -y 1   # 0x68 が表示されればOK
```

### カメラ確認

```bash
ls /dev/video*
sudo motion -c /etc/motion/motion.conf
```

### 確認チェックリスト ③

- [ ] Neo-8M UART接続・gpsd動作確認
- [ ] GPS位置情報取得確認
- [ ] MPU-6050 I2C認識確認（0x68）
- [ ] 加速度読み取り確認
- [ ] IRカメラ USB認識確認
- [ ] motion動体検知JPEG保存確認
- [ ] 走行/停車自動切替確認
- [ ] 循環バッファ録画確認
- [ ] 衝撃検知→動画保存確認

---

## ④ ZTR01経由データ吸出し

### 目標

- iPhoneをZTR01のWiFiに接続してWebUIの/filesにアクセス
- 動画・JPEG・ログをDL
- Tailscale不要・モバイル回線不使用

### アクセス手順

```
1. iPhoneをSPWH_L11_183D74（ZTR01）のWiFiに接続
2. ZTR01管理画面（http://192.168.0.1）でRaspiのIPを確認
3. iPhoneブラウザで http://RaspiIP:5000/files にアクセス
4. Basic認証入力（ID: pi / PW: config.pyで設定）
5. ファイル選択してDL
   → Tailscale不要・モバイル回線不使用
   → ZTR01のWiFi速度でDL可能
```

### 確認チェックリスト ④

- [ ] iPhoneをZTR01のWiFiに接続
- [ ] ZTR01管理画面でRaspiのIP確認
- [ ] iPhoneブラウザから/filesにアクセス確認
- [ ] Basic認証動作確認
- [ ] 動画・JPEG・CSVのDL動作確認
