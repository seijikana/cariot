#!/usr/bin/env python3
"""
Tracer 3210A MPPT 接続テストスクリプト
実行: python3 test_tracer.py
"""

from pymodbus.client import ModbusSerialClient
import sys

def test_tracer():
    client = ModbusSerialClient(
        port='/dev/ttyUSB0',
        baudrate=115200,
        bytesize=8,
        parity='N',
        stopbits=1,
        timeout=3
    )

    if not client.connect():
        print("❌ Tracer接続失敗 - /dev/ttyUSB0を確認してください")
        sys.exit(1)

    print("✅ Tracer接続成功")

    try:
        # バッテリー温度（RTSセンサー）
        r = client.read_input_registers(0x3110, 1, slave=1)
        if not r.isError():
            temp = r.registers[0] / 100.0
            print(f"🌡  バッテリー温度: {temp}℃")
        else:
            print("❌ バッテリー温度読み取り失敗")

        # PV電圧
        r = client.read_input_registers(0x3100, 1, slave=1)
        if not r.isError():
            print(f"☀️  PV電圧: {r.registers[0]/100.0}V")

        # バッテリー電圧
        r = client.read_input_registers(0x310C, 1, slave=1)
        if not r.isError():
            print(f"🔋 バッテリー電圧: {r.registers[0]/100.0}V")

        # SOC
        r = client.read_input_registers(0x311A, 1, slave=1)
        if not r.isError():
            print(f"📊 SOC: {r.registers[0]/100.0}%")

        print("\n✅ 全データ取得成功")

    except Exception as e:
        print(f"❌ エラー: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    test_tracer()
