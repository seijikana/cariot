# ハードウェア配線・設定リファレンス

## GPIO ピン配置（Raspi Zero 2W）

```
                    [Raspi Zero 2W]

GPIO2  (SDA) ──────→ MPU-6050 SDA
GPIO3  (SCL) ──────→ MPU-6050 SCL
GPIO14 (TXD) ──────→ Neo-8M GPS RX
GPIO15 (RXD) ──────→ Neo-8M GPS TX
3.3V         ──────→ MPU-6050 VCC
5V           ──────→ Neo-8M GPS VCC（5V対応品の場合）
GND          ──────→ MPU-6050 GND / Neo-8M GND

USB OTG → OTG USBハブ（4ポート）
    ├─ Port1: USB-RS485アダプター → Tracer RJ45
    ├─ Port2: ELP IR USBカメラ（5m延長）
    └─ Port3: Samsung FIT Plus 128GB
```

## Tracer 3210A RS-485 RJ45 配線

```
Tracer RJ45（COM端子）     USB-RS485アダプター
Pin3,4 (RS-485 B D-)  ──→ B端子
Pin5,6 (RS-485 A D+)  ──→ A端子
Pin7,8 (GND)          ──→ GND
Pin1,2 (+5V)          ──  【絶対接続禁止】

ケーブル: イーサネット（ストレート）
```

## Modbus レジスタ一覧（Tracer 3210A）

### 読み取り（Input Registers）

| アドレス | 内容 | 倍率 | 単位 |
|---|---|---|---|
| 0x3100 | PV電圧 | /100 | V |
| 0x3101 | PV電流 | /100 | A |
| 0x3102 | PV電力 | /100 | W |
| 0x310C | バッテリー電圧 | /100 | V |
| 0x310D | バッテリー電流 | /100 | A |
| 0x3110 | **バッテリー温度（RTS）** | /100 | ℃ |
| 0x311A | バッテリーSOC | /100 | % |
| 0x330C | 今日の発電量 | /100 | kWh |
| 0x330E | 累積発電量 | /100 | kWh |

### 書き込み（Holding Registers）

| アドレス | 内容 | 備考 |
|---|---|---|
| 0x9002 | **充電上限電圧** | 通常0x0EB8（37.84V）・停止時0x0960に下げる |
| 0x906B | Load ON/OFF | 0x0000:OFF 0x0001:ON |

## JBD BMS BLE プロトコル

```
Notify UUID: 0000ff01-0000-1000-8000-00805f9b34fb
Write UUID:  0000ff02-0000-1000-8000-00805f9b34fb

コマンド:
  基本情報: DD A5 03 00 FF FD 77
  セル電圧: DD A5 04 00 FF FC 77

基本情報レスポンス（主要オフセット）:
  [4:6]   総電圧    /100 → V
  [6:8]   電流      /100 → A（符号あり）
  [19]    SOC       直値 → %
  [23:25] 温度1    -2731/10 → ℃
```

## MPU-6050

```
I2Cアドレス: 0x68
電源管理レジスタ: 0x6B（0x00で起動）
加速度レジスタ: 0x3B〜0x40（X/Y/Z 各2byte）
スケール: ±2g → 生データ/16384.0 = g値
衝撃判定: sqrt(ax² + ay² + az²) > 閾値
  走行中: 2.5G
  停車中: 1.5G
```

## 電源配線

```
LiFePO4 12V
    ├─ [ヒューズ 3A] → [DC-DC 12V→5V 3A] → [OTGハブ] → Raspi等
    └─ [5.5mm DCジャック センタープラス] → ZTR01（12V 2A）

消費電力目安:
    Raspi Zero 2W: 0.5〜2.5W
    ZTR01:         最大30W
    GPS・IMU:      0.2W
    IRカメラ:      0.5W
    合計待機:      約5W（ZTR01込み）
```

## WiFi設定（/etc/wpa_supplicant/wpa_supplicant.conf）

```
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=JP

network={
    ssid="カナサトのiPhone"    # 実際のSSIDに変更
    psk="テザリングPW"         # 実際のPWに変更
    priority=10
    id_str="iphone"
}

network={
    ssid="SPWH_L11_183D74"
    psk="****"
    priority=1
    id_str="ztr01"
}
```

## ZTR01 APN設定

```
管理画面: http://192.168.0.1 / PW: ****
APN: povo.jp
ユーザー名・パスワード: 空白
```
