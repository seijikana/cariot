# CarIoT（車載 Zero 2 W）

- セットアップ・復旧手順: [docs/SETUP.md](docs/SETUP.md)（自動化スクリプト `setup/setup_zero.sh`）
- 依存ライブラリ: `requirements.txt`（動作確認済みバージョンに固定）

---

iot-pvcontrol/
├── CLAUDE.md          # Claude Code向けプロジェクト概要（このファイルを最初に読む）
├── README.md          # このファイル
├── config.py          # 設定ファイル（MACアドレス・IPアドレス等を要編集）
├── hardware.md        # ハードウェア配線・Modbusレジスタ・BLE UUIDリファレンス
├── phases.md          # フェーズ別実装手順書（チェックリスト付き）
├── test_tracer.py     # Tracer MPPT 接続テスト
├── test_bms.py        # JBD BMS BLE 接続テスト
│
├── tracer.py          # [未作成] Tracer制御モジュール
├── bms.py             # [未作成] JBD BMS BLEモジュール
├── gps_tracker.py     # [未作成] GPS追跡モジュール
├── imu.py             # [未作成] IMU衝撃検知モジュール
├── camera.py          # [未作成] カメラ・録画モジュール
├── webui.py           # [未作成] Flask WebUI（データ吸出し）
└── main.py            # [未作成] メインスクリプト（各モジュール統合）

solar-controller-tracer-a-series-manual.pdf  # Tracer公式マニュアル
