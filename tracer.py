"""Tracer 3210A MPPT Modbusモジュール

USB-RS485未接続時はTracerMockを返す。
温度制御はEEPROM書き込みを伴うため状態変化時のみ実行する（ヒステリシス）。
"""
import os
import math
import time
import logging

import config

logger = logging.getLogger(__name__)

# 0x3201 D3:D2 bits → 充電状態ラベル
_CHARGE_LABEL = {0: "No charging", 1: "Float", 2: "Boost", 3: "Equalization"}


class TracerMock:
    """USB-RS485未接続時のモック。ダッシュボード確認・開発用。"""

    def __init__(self):
        self._stopped = False
        self._t0 = time.monotonic()

    def read_all(self) -> dict:
        age = time.monotonic() - self._t0
        temp = 28.0 + 5 * math.sin(age / 600)
        soc = int(70 + 20 * math.sin(age / 3600))
        pv_w = max(0.0, 60.0 + 30 * math.sin(age / 300))
        return {
            "pv_voltage":   round(18.5 + 2 * math.sin(age / 400), 2),
            "pv_current":   round(pv_w / 18.5, 2),
            "pv_power":     round(pv_w, 1),
            "bat_voltage":  round(13.0 + 0.3 * math.sin(age / 3600), 2),
            "bat_current":  round(pv_w / 13.2, 2),
            "bat_power":    round(pv_w, 1),
            "load_voltage": round(12.9 + 0.3 * math.sin(age / 3600), 2),
            "load_current": 1.20,
            "load_power":   round(12.9 * 1.2, 1),
            "bat_temp":     round(temp, 1),
            "bat_soc":      max(0, min(100, soc)),
            "charge_status": "No charging" if self._stopped else "Boost",
            "bat_status":   0,
            "charge_stopped": self._stopped,
            "mock": True,
        }

    def stop_charging(self, stop_v: float = None):
        if not self._stopped:
            self._stopped = True
            v = stop_v if stop_v is not None else config.BOOST_VOLTAGE_STOP * 0.01
            logger.warning("[MOCK] Charging STOPPED boost→%.2fV (temp > %.1f°C)", v, config.TEMP_HIGH)

    def resume_charging(self, normal_v: float = None):
        if self._stopped:
            self._stopped = False
            v = normal_v if normal_v is not None else config.BOOST_VOLTAGE_NORMAL * 0.01
            logger.info("[MOCK] Charging RESUMED boost→%.2fV (temp < %.1f°C)", v, config.TEMP_LOW)

    def close(self):
        pass


class TracerModbus:
    """実機 Tracer 3210A (pymodbus 3.x)。"""

    # 0x9000ブロック内のインデックス
    _IDX_BATT_TYPE        = 0   # 0x9000
    _IDX_CHARGING_LIMIT   = 4   # 0x9004
    _IDX_OV_RECONNECT     = 5   # 0x9005 Over Voltage Reconnect (≤ Charging Limit)
    _IDX_EQUALIZE         = 6   # 0x9006
    _IDX_BOOST            = 7   # 0x9007
    _IDX_FLOAT            = 8   # 0x9008
    _IDX_BOOST_RECONNECT  = 9   # 0x9009
    _IDX_LOW_V_RECONNECT  = 10  # 0x900A (変更しない)

    _REG_BOOST_DURATION = 0x906C  # Boost充電タイマー（分）単独書き込み可

    def __init__(self):
        from pymodbus.client import ModbusSerialClient
        self._c = ModbusSerialClient(
            port=config.TRACER_PORT,
            baudrate=config.TRACER_BAUDRATE,
            bytesize=8, parity='N', stopbits=1, timeout=1,
        )
        if not self._c.connect():
            raise ConnectionError(f"Cannot connect to {config.TRACER_PORT}")

        self._stopped = False
        # 起動時に全パラメータブロックを保存（復元用）
        r = self._c.read_holding_registers(0x9000, count=15, device_id=config.TRACER_SLAVE_ID)
        if r.isError():
            raise IOError("Cannot read 0x9000 parameter block")
        self._orig_params = list(r.registers)

        # Boost充電タイマー（0x906C）を保存
        rd = self._c.read_holding_registers(self._REG_BOOST_DURATION, count=1, device_id=config.TRACER_SLAVE_ID)
        self._orig_boost_duration = rd.registers[0] if not rd.isError() else 120

        logger.info("Tracer connected on %s  boost=%.2fV float=%.2fV batttype=%d boost_duration=%dmin",
                    config.TRACER_PORT,
                    self._orig_params[self._IDX_BOOST] * 0.01,
                    self._orig_params[self._IDX_FLOAT] * 0.01,
                    self._orig_params[self._IDX_BATT_TYPE],
                    self._orig_boost_duration)

    @staticmethod
    def _s16(v: int) -> int:
        """符号なし16bit → 符号付き16bit（温度レジスタ用）。"""
        return v - 65536 if v > 32767 else v

    def _ri(self, addr: int, count: int) -> list:
        r = self._c.read_input_registers(addr, count=count, device_id=config.TRACER_SLAVE_ID)
        if r.isError():
            raise IOError(f"Modbus read_input_registers error @ 0x{addr:04X}")
        return r.registers

    def read_all(self) -> dict:
        # PV電圧/電流/電力 + バッテリー電圧/電流/電力 (0x3100-0x3107)
        r1 = self._ri(0x3100, 8)
        # 負荷電圧/電流/電力 + バッテリー温度 (0x310C-0x3110)
        r2 = self._ri(0x310C, 5)
        # SOC (0x311A)
        r3 = self._ri(0x311A, 1)
        # バッテリーステータス + 充電ステータス (0x3200-0x3201)
        r4 = self._ri(0x3200, 2)

        charge_bits = (r4[1] >> 2) & 0x03  # D3:D2
        pv_v  = round(r1[0] * 0.01, 2)
        pv_a  = round(r1[1] * 0.01, 2)
        bat_v = round(r1[4] * 0.01, 2)
        bat_a = round(r1[5] * 0.01, 2)
        pv_w  = round(pv_v * pv_a, 1)
        load_v = round(r2[0] * 0.01, 2)
        load_a = round(r2[1] * 0.01, 2)
        load_w = round(load_v * load_a, 1)
        return {
            "pv_voltage":   pv_v,
            "pv_current":   pv_a,
            "pv_power":     pv_w,
            "bat_voltage":  bat_v,
            "bat_current":  bat_a,
            "bat_power":    round(pv_w - load_w, 1),  # PV - 負荷 = 実充電電力
            "load_voltage": load_v,
            "load_current": load_a,
            "load_power":   load_w,
            "bat_temp":     round(self._s16(r2[4]) * 0.01, 1),
            "bat_soc":      r3[0],   # 0-100 (%)
            "charge_status": _CHARGE_LABEL.get(charge_bits, f"0x{charge_bits:X}"),
            "bat_status":   r4[0],
            "charge_stopped": self._stopped,
            "mock": False,
        }

    def _write_params(self, params: list, force_user: bool = True) -> bool:
        """0x9000から15レジスタをブロック書き込み。force_user=Trueで先頭をUSER(0)に設定。"""
        vals = list(params)
        if force_user:
            vals[self._IDX_BATT_TYPE] = 0  # カスタム電圧書き込みにはUSERが必要
        r = self._c.write_registers(0x9000, vals, device_id=config.TRACER_SLAVE_ID)
        if r.isError():
            logger.error("write_registers(0x9000) failed: %s", r)
            return False
        return True

    def stop_charging(self, stop_v: float = None) -> bool:
        """充電電圧を全体的に下げて充電を停止（ブロック書き込み）。戻り値: 成否。

        階層制約: OVReconnect <= ChargingLimit >= Equalize >= Boost >= Float >= BoostReconnect >= LowVoltReconnect
        注意: Tracerは現在の充電サイクルを継続するため即時停止ではない。
              次のサイクル（バッテリーがBoostReconnect以下に下がった後）から新目標が適用される。
        """
        if self._stopped:
            return True
        low_vr = self._orig_params[self._IDX_LOW_V_RECONNECT]  # 0x900A 変更しない
        br = low_vr + 10              # BoostReconnect > LowVoltReconnect (厳密な大小関係が必要)
        fl = br + 10                  # Float      = BoostReconnect + 0.10V
        bv = fl + 10                  # Boost      = Float      + 0.10V
        eq = bv + 10                  # Equalize   = Boost      + 0.10V
        cl = eq + 10                  # ChargingLimit = Equalize + 0.10V
        ovr = cl                      # OVReconnect = ChargingLimit (制約: OVReconnect <= ChargingLimit)

        vals = list(self._orig_params)
        vals[self._IDX_CHARGING_LIMIT]  = cl
        vals[self._IDX_OV_RECONNECT]    = ovr
        vals[self._IDX_EQUALIZE]        = eq
        vals[self._IDX_BOOST]           = bv
        vals[self._IDX_FLOAT]           = fl
        vals[self._IDX_BOOST_RECONNECT] = br

        if self._write_params(vals):
            self._stopped = True
            # Boost充電タイマーを0に → 現在のBoostサイクルを即時終了させる
            self._c.write_registers(self._REG_BOOST_DURATION, [0], device_id=config.TRACER_SLAVE_ID)
            # 書き込み直後に読み返して実際にレジスタが変わったか確認
            rb = self._c.read_holding_registers(0x9007, count=2, device_id=config.TRACER_SLAVE_ID)
            actual_bv = rb.registers[0] * 0.01 if not rb.isError() else -1
            actual_fl = rb.registers[1] * 0.01 if not rb.isError() else -1
            logger.warning(
                "Charging STOPPED: boost→%.2fV float→%.2fV (readback: boost=%.2fV float=%.2fV)",
                bv * 0.01, fl * 0.01, actual_bv, actual_fl)
            return True
        return False

    def resume_charging(self, normal_v: float = None) -> bool:
        """元のパラメータブロックを復元して充電を再開。戻り値: 成否。"""
        if not self._stopped:
            return True
        # force_user=False: orig_params[0]の元のbatttypeをそのまま復元する
        if self._write_params(self._orig_params, force_user=False):
            self._stopped = False
            # Boost充電タイマーを元の値に戻す
            self._c.write_registers(self._REG_BOOST_DURATION, [self._orig_boost_duration],
                                    device_id=config.TRACER_SLAVE_ID)
            logger.info("Charging RESUMED boost→%.2fV (bat_temp < %.1f°C)",
                        self._orig_params[self._IDX_BOOST] * 0.01, config.TEMP_LOW)
            return True
        logger.error("resume_charging failed (Modbus write error)")
        return False

    def close(self):
        if self._stopped:
            self.resume_charging()
        else:
            self._c.write_registers(0x9000, self._orig_params, device_id=config.TRACER_SLAVE_ID)
            self._c.write_registers(self._REG_BOOST_DURATION, [self._orig_boost_duration],
                                    device_id=config.TRACER_SLAVE_ID)
        self._c.close()


def create_tracer():
    """実機接続を試み、失敗したらモックを返す。"""
    if not os.path.exists(config.TRACER_PORT):
        logger.warning("%s not found → mock mode", config.TRACER_PORT)
        return TracerMock()
    try:
        return TracerModbus()
    except Exception as e:
        logger.warning("Tracer init failed (%s) → mock mode", e)
        return TracerMock()
