# config.py - 車載IoTシステム設定ファイル
# このファイルを実際の値で編集してから使用すること

# ============================================================
# Tracer MPPT RS-485 Modbus 設定
# ============================================================
TRACER_PORT     = "/dev/ttyTracer"
TRACER_BAUDRATE = 115200
TRACER_SLAVE_ID = 1

# 温度制御閾値（LiFePO4推奨）
TEMP_HIGH = 45.0    # ℃ 充電停止温度
TEMP_LOW  = 40.0    # ℃ 充電再開温度（ヒステリシス）

# Modbusレジスタ（読み取り専用 0x3xxx）- EPSolar Tracer AN プロトコル準拠
# Input registers: function code 0x04 (read_input_registers)
REG_PV_VOLTAGE    = 0x3100   # PV入力電圧 ×0.01V
REG_PV_CURRENT    = 0x3101   # PV入力電流 ×0.01A
REG_PV_POWER_L    = 0x3102   # PV入力電力 L ×0.01W
REG_PV_POWER_H    = 0x3103   # PV入力電力 H
REG_BAT_VOLTAGE   = 0x3104   # バッテリー電圧 ×0.01V  ※旧configの0x310Cは負荷電圧(誤り)
REG_BAT_CURRENT   = 0x3105   # 充電電流 ×0.01A
REG_BAT_POWER_L   = 0x3106   # 充電電力 L ×0.01W
REG_BAT_POWER_H   = 0x3107   # 充電電力 H
REG_LOAD_VOLTAGE  = 0x310C   # 負荷電圧 ×0.01V
REG_LOAD_CURRENT  = 0x310D   # 負荷電流 ×0.01A
REG_LOAD_POWER_L  = 0x310E   # 負荷電力 L ×0.01W
REG_BAT_TEMP      = 0x3110   # バッテリー温度（RTSセンサー）×0.01°C 符号付き
REG_BAT_SOC       = 0x311A   # SOC % (0-100、÷100不要)
REG_TODAY_KWH     = 0x330C   # 今日の発電量
REG_TOTAL_KWH     = 0x330E   # 累積発電量
REG_CHARGE_STATUS = 0x3201   # 充電状態（D3-D2: 00無充電 01フロート 02ブースト 03均等化）

# Modbusレジスタ（書き込み 0x9xxx）
# ⚠️ EEPROM書き込み → 状態変化時のみ書き込む（年180回以内に収める）
REG_BOOST_VOLTAGE = 0x9007   # Boost充電電圧

# 充電制御電圧設定値（12Vシステム）
# ヒステリシス制御：変化時のみ書き込み → 最悪1,000回で5.5年
BOOST_VOLTAGE_NORMAL = 0x0578   # 14.00V（通常充電）
BOOST_VOLTAGE_STOP   = 0x04B0   # 12.00V（充電停止・バッテリー電圧以下）
FLOAT_VOLTAGE_NORMAL = 0x0532   # 13.30V（LiFePO4静止電圧付近: 実質Float停止）
# ※ 実機で事前にTracerの現在値を読み取って確認すること

# ============================================================
# JBD BMS BLE 設定
# ============================================================
BMS_MAC_ADDRESS = "XX:XX:XX:XX:XX:XX"   # 要設定: bluetoothctlで確認
BMS_LOAD_THRESHOLD_W = 15.0       # BMS負荷がこの値未満は無視（Tracer経由の小電力二重計上防止）

BMS_NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
BMS_WRITE_UUID  = "0000ff02-0000-1000-8000-00805f9b34fb"
BMS_CMD_BASIC   = bytes([0xDD, 0xA5, 0x03, 0x00, 0xFF, 0xFD, 0x77])
BMS_CMD_CELL    = bytes([0xDD, 0xA5, 0x04, 0x00, 0xFF, 0xFC, 0x77])

# ============================================================
# GPS 設定
# ============================================================
GPS_HOST = "localhost"
GPS_PORT = 2947

SPEED_THRESHOLD_KMH = 1.0    # km/h 停車判定速度
PARK_DELAY_SEC      = 30     # 秒   停車判定ディレイ（信号待ち除外）
GPS_TIMEOUT_SEC     = 60     # 秒   GPS消失タイムアウト

# ============================================================
# IMU（MPU-6050）設定
# ============================================================
IMU_I2C_BUS     = 1
IMU_I2C_ADDRESS = 0x68

SHOCK_THRESHOLD_DRIVING = 2.5   # G 走行中衝撃閾値
SHOCK_THRESHOLD_PARKED  = 1.5   # G 停車中衝撃閾値

# ============================================================
# 録画・バッファ設定
# ============================================================
STORAGE_BASE   = "/mnt/storage"
EVENTS_DIR     = "/mnt/storage/events"
MOTION_DIR     = "/mnt/storage/motion_jpg"
GPS_LOG_DIR    = "/mnt/storage/gps_log"
TRACER_LOG_DIR = "/mnt/storage/tracer_log"
BMS_LOG_DIR    = "/mnt/storage/bms_log"
BUFFER_DIR     = "/mnt/storage/buffer"

CAMERA_FPS        = 30
PRE_SHOCK_SEC     = 120   # 秒 衝撃前バッファ長
POST_SHOCK_SEC    = 120   # 秒 衝撃後録画長
BUFFER_MAX_FRAMES = CAMERA_FPS * PRE_SHOCK_SEC

# ============================================================
# Flask HTTP サーバー設定
# Tailscale経由（スマホ・自宅PC）および
# iPhoneテザリング時（ローカル）の両方で使用
# ============================================================
WEBUI_HOST     = "0.0.0.0"
WEBUI_PORT     = 5000
WEBUI_USERNAME = "pi"
WEBUI_PASSWORD = "changeme"   # 要変更

# データ更新間隔
POLLING_INTERVAL_SEC = 30    # ダッシュボード自動更新間隔（秒）
TRACER_POLL_SEC      = 10    # Tracerデータ収集間隔（秒）- Modbus読み取りのみ、EEPROM無影響
DATA_COLLECT_SEC     = 60    # SQLiteログ記録間隔（秒）

# 電力履歴 SQLite DB（SDカード上）
HISTORY_DB_PATH = "/home/pi/cariot/history.db"

# ============================================================
# WiFi APモード設定（接続先不在時のフォールバック）
# ============================================================
AP_SSID     = "CarIoT-AP"
AP_PASSWORD = ""             # 空文字 = オープンネットワーク（パスワードなし）
AP_IP       = "192.168.1.1" # APモード時のRaspi IPアドレス
AP_WAIT_SEC = 60             # 未接続からAPモード起動までの秒数
