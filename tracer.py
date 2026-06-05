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
        # 起動時にBoost電圧を読み取り保存（再開時に元値へ戻す）
        r = self._c.read_holding_registers(
            config.REG_BOOST_VOLTAGE, 1, slave=config.TRACER_SLAVE_ID
        )
        self._orig_boost = r.registers[0] if not r.isError() else config.BOOST_VOLTAGE_NORMAL
        logger.info("Tracer connected on %s  boost_voltage=%.2fV",
                    config.TRACER_PORT, self._orig_boost * 0.01)

    @staticmethod
    def _s16(v: int) -> int:
        """符号なし16bit → 符号付き16bit（温度レジスタ用）。"""
        return v - 65536 if v > 32767 else v

    def _ri(self, addr: int, count: int) -> list:
        r = self._c.read_input_registers(addr, count, slave=config.TRACER_SLAVE_ID)
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
        return {
            "pv_voltage":   round(r1[0] * 0.01, 2),
            "pv_current":   round(r1[1] * 0.01, 2),
            "pv_power":     round(((r1[3] << 16) | r1[2]) * 0.01, 1),
            "bat_voltage":  round(r1[4] * 0.01, 2),
            "bat_current":  round(r1[5] * 0.01, 2),
            "bat_power":    round(((r1[7] << 16) | r1[6]) * 0.01, 1),
            "load_voltage": round(r2[0] * 0.01, 2),
            "load_current": round(r2[1] * 0.01, 2),
            "load_power":   round(((r2[3] << 16) | r2[2]) * 0.01, 1),
            "bat_temp":     round(self._s16(r2[4]) * 0.01, 1),
            "bat_soc":      r3[0],   # 0-100 (%)
            "charge_status": _CHARGE_LABEL.get(charge_bits, f"0x{charge_bits:X}"),
            "bat_status":   r4[0],
            "charge_stopped": self._stopped,
            "mock": False,
        }

    def stop_charging(self, stop_v: float = None):
        """Boost電圧を下げて充電を停止（EEPROM書き込み）。stop_v=None で config デフォルト使用。"""
        if self._stopped:
            return
        raw = int(round(stop_v * 100)) if stop_v is not None else config.BOOST_VOLTAGE_STOP
        r = self._c.write_register(config.REG_BOOST_VOLTAGE, raw, slave=config.TRACER_SLAVE_ID)
        if not r.isError():
            self._stopped = True
            logger.warning("Charging STOPPED boost→%.2fV (bat_temp > %.1f°C)",
                           raw * 0.01, config.TEMP_HIGH)

    def resume_charging(self, normal_v: float = None):
        """Boost電圧を戻して充電を再開（EEPROM書き込み）。normal_v=None で起動時読み取り値使用。"""
        if not self._stopped:
            return
        raw = int(round(normal_v * 100)) if normal_v is not None else self._orig_boost
        r = self._c.write_register(config.REG_BOOST_VOLTAGE, raw, slave=config.TRACER_SLAVE_ID)
        if not r.isError():
            self._stopped = False
            logger.info("Charging RESUMED boost→%.2fV (bat_temp < %.1f°C)",
                        raw * 0.01, config.TEMP_LOW)

    def close(self):
        if self._stopped:
            self.resume_charging()
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
