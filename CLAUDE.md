# iot-pvcontrol プロジェクト

## プロジェクト概要

トヨタ・ヴェルファイア（AYH30）に搭載したソーラー＋LiFePO4バッテリーシステムを、
Raspberry Pi Zero 2W + ZTR01（povo2.0）+ Tailscale で遠隔監視・制御するシステム。

クラウド不使用。Tailscale VPN で自宅サーバーに直結する構成。

---

## システム構成図

```
[ソーラーパネル 100W]
        ↓
[Tracer 3210A MPPT] ← RTS温度センサー（RTS300R47K3.81A）
        ↓ RS-485 RJ45
[USB-RS485アダプター CH340互換]
        ↓ USB
[Raspi Zero 2W] ← MPU-6050 IMU（I2C GPIO2/3）
    ├─ BLE（内蔵）→ JBD BMS Bluetooth
    ├─ UART（GPIO14/15）→ Neo-8M GPS
    ├─ OTG USBハブ
    │   ├─ ELP IR USBカメラ（5m延長）
    │   ├─ USB-RS485（Tracer接続）
    │   └─ Samsung FIT Plus 128GB（録画・ログ保存）
    └─ WiFi → ZTR01（povo2.0 128kbps）→ Tailscale → 自宅PC
        ↓ 12V
[LiFePO4バッテリー + JBD BMS]
        ↓ DC12V
[ZTR01] + [Raspi Zero 2W（DC-DC 5V経由）]
```

---

## 実装フェーズ

| フェーズ | 内容 | ステータス |
|---|---|---|
| ⓪ | Raspiセットアップ + Tailscale環境整備 | ✅ 完了 |
| ① | Tracer MPPT 温度制御・発電充電監視 + Flask WebUI基盤 | 🔲 未着手 |
| ② | JBD BMS Bluetooth ミラーリング | 🔲 未着手 |
| ③ | カメラ・GPS・IMU監視 | 🔲 未着手 |
| ④ | ZTR01経由データ吸出し（WebUI /files） | 🔲 未着手 |

---

## ハードウェア仕様

### Raspberry Pi Zero 2W
- OS: Raspberry Pi OS Lite 64bit
- ホスト名: RasberryPiZero2WHLite
- Tailscale IP: 100.126.231.82
- WiFi接続先（優先順）:
  1. pr500m-889e37-1（自宅ルーター）priority=10
  2. SPWH_L11_183D74（ZTR01）priority=1

### ZTR01（Speed Wi-Fi HOME 5G L11）
- Model: ZTR01
- SIM: povo2.0 nanoSIM（2回線目）
- APN: povo.jp / ユーザー名・PW空白
- 管理画面: http://192.168.0.1 / PW: 4599
- 給電: DC12V 2A（5.5mmジャック センタープラス）

### Tracer 3210A MPPT
- 通信: RS-485 Modbus RTU
- RJ45ピン配置:
  - Pin1,2: +5V（**絶対接続禁止**）
  - Pin3,4: RS-485 B（D-）
  - Pin5,6: RS-485 A（D+）
  - Pin7,8: GND
- Baudrate: 115200
- Slave ID: 1

### JBD BMS
- 接続: BLE 4.x
- Notify UUID: 0000ff01-0000-1000-8000-00805f9b34fb
- Write UUID:  0000ff02-0000-1000-8000-00805f9b34fb
- CMD_BASIC: bytes([0xDD, 0xA5, 0x03, 0x00, 0xFF, 0xFD, 0x77])
- CMD_CELL:  bytes([0xDD, 0xA5, 0x04, 0x00, 0xFF, 0xFC, 0x77])
- MAC: （起動後 bluetoothctl scan で確認・config.pyに記入）

### Neo-8M GPS
- 接続: UART（GPIO14=TX, GPIO15=RX）
- Baudrate: 9600
- ライブラリ: gpsd + python-gps

### MPU-6050 IMU
- 接続: I2C（GPIO2=SDA, GPIO3=SCL）
- アドレス: 0x68
- 用途: 衝撃検知（走行中2.5G・停車中1.5G）

### ELP IR USBカメラ
- 接続: USB（OTGハブ経由）
- 延長: 5mUSBケーブル
- 用途: 動体検知JPEG（停車中のみ）+ 衝撃動画（常時）

### ストレージ（2.5インチ HDD 465.7GB）
- デバイス: /dev/sda1（UUID=40B0-BF8B exFAT）
- マウント先: /mnt/storage
- ディレクトリ構成:
  - /mnt/storage/events/      衝撃動画（前後2分）
  - /mnt/storage/motion_jpg/  動体検知JPEG（停車中のみ）
  - /mnt/storage/gps_log/     GPS軌跡CSV
  - /mnt/storage/tracer_log/  充電・温度ログCSV
  - /mnt/storage/bms_log/     BMSデータログCSV
  - /mnt/storage/buffer/      循環バッファ一時領域（2GB）

---

## ソフトウェア構成

### 自宅側
- Tailscale（ノード）のみ
- ブラウザでアクセスするだけ（Mosquitto・Home Assistant不要）

### 車載Raspi側
- Tailscale クライアント
- Python 3.x メインスクリプト（systemdサービス）
- Flask HTTPサーバー（port 5000）
  - Tailscale経由: スマホ・自宅PCからダッシュボード閲覧
  - ZTR01経由ローカル: iPhoneをZTR01のWiFiに接続してデータ吸出し
- motion（動体検知・停車中のみ起動）
- gpsd（GPS デーモン）

### 主要Pythonライブラリ
```
pymodbus               # Tracer RS-485 Modbus
bleak                  # JBD BMS BLE
python-gps             # GPS
smbus2                 # MPU-6050 I2C
flask                  # HTTPサーバー・ダッシュボード・ファイルDL
flask-httpauth         # Basic認証
opencv-python-headless # 循環バッファ録画
```

---

## Flask HTTPエンドポイント構成

| エンドポイント | 内容 | 用途 |
|---|---|---|
| GET / | ダッシュボードHTML | スマホ・PC・自宅からリアルタイム確認 |
| GET /api/status | 全センサーデータ JSON | 自動更新ポーリング用 |
| GET /files | ファイル一覧 | テザリング時データ吸出し |
| GET /files/dl/<path> | ファイルDL | 動画・JPEG・ログDL |

### アクセス方法
```
【Tailscale経由（どこからでも）】
http://100.x.x.x:5000
→ スマホブラウザでダッシュボード確認
→ 自宅PCからも同じURLでOK

【ZTR01ローカル経由（大容量転送時）】
iPhoneをZTR01のWiFiに接続
http://ZTR01配下のRaspi IP:5000
→ Tailscale不要・モバイル回線不使用・大容量ファイル転送に最適
```

---

## 温度制御ロジック（Tracer充電停止）

```
バッテリー温度（RTS → Modbusレジスタ 0x3110）
  > 45℃ → 充電停止（Charging Limit Voltage を下げる）
  < 40℃ → 充電再開（ヒステリシス制御）

Tracerの内蔵過温度保護は65℃（LiFePO4には高すぎる）
→ Raspiによる45℃制御が必要
```

---

## 走行/停車判定ロジック

```
GPS速度 < 1.0km/h が 30秒継続 → 停車モード
  - motion 起動（動体検知JPEG ON）
  - 衝撃閾値: 1.5G

GPS速度 >= 1.0km/h → 走行モード
  - motion 停止（動体検知JPEG OFF）
  - 衝撃閾値: 2.5G

GPS消失60秒以上 → フェイルセーフ: 停車モードへ
```

---

## 衝撃検知・循環バッファ録画

```
常時: 30fps で循環バッファに録画（直近2分保持）
衝撃検知時:
  1. 現在のバッファ（過去2分）を確定保存
  2. さらに2分録画継続
  3. /mnt/storage/events/shock_YYYYMMDD_HHMMSS.mp4 として保存
  4. 通常の循環バッファに戻る
```

---

## データ吸出し（ZTR01ローカル経由）

```
1. iPhoneをZTR01のWiFi（SPWH_L11_183D74）に接続
2. RaspiもZTR01配下（常時接続済み）
3. iPhoneブラウザで http://ZTR01配下のRaspi IP:5000 にアクセス
4. Basic認証（ID: pi / PW: config.pyで設定）
5. ファイル選択してDL
   → Tailscale不要・モバイル回線不使用
   → ZTR01のWiFi速度でDL可能
```

### ZTR01配下でのRaspi IPアドレス確認方法
```bash
# ZTR01に接続後
ip addr show wlan0
# または ZTR01管理画面 http://192.168.0.1 で確認
```

---

## 注意事項

- RJ45のPin1,2（+5V）は絶対に接続しない（Tracer破損）
- Tracer内蔵過温度保護は65℃（高すぎるため45℃ソフト制御必須）
- povo2.0 SIMは180日以内にトッピング購入が必要（期限: 2025-11-13）
- BLE/WiFi干渉が出た場合はUSB Bluetoothドングルを追加
- 夏の車内は70℃超→グローブボックス内設置・ヒートシンク必須
