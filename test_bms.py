#!/usr/bin/env python3
"""
JBD BMS BLE 接続テストスクリプト
実行: python3 test_bms.py
事前: config.pyのBMS_MAC_ADDRESSを設定すること
"""

import asyncio
from bleak import BleakClient, BleakScanner
import sys

NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
WRITE_UUID  = "0000ff02-0000-1000-8000-00805f9b34fb"
CMD_BASIC   = bytes([0xDD, 0xA5, 0x03, 0x00, 0xFF, 0xFD, 0x77])

async def scan_bms():
    """BMSデバイスをスキャンしてMACアドレスを表示"""
    print("🔍 BLEスキャン中（10秒）...")
    devices = await BleakScanner.discover(timeout=10.0)
    for d in devices:
        print(f"  {d.address}  {d.name}")
    print("\nJBD または SmartBMS という名前のデバイスのMACをconfig.pyに設定してください")

def parse_basic(data):
    voltage = int.from_bytes(data[4:6], 'big') / 100.0
    current = int.from_bytes(data[6:8], 'big') / 100.0
    soc     = data[19]
    temp    = (int.from_bytes(data[23:25], 'big') - 2731) / 10.0
    return voltage, current, soc, temp

async def test_bms(mac):
    print(f"🔗 BMS接続中: {mac}")
    try:
        async with BleakClient(mac, timeout=10.0) as client:
            print("✅ BMS接続成功")
            received = []
            def handler(_, data):
                received.append(bytes(data))

            await client.start_notify(NOTIFY_UUID, handler)
            await client.write_gatt_char(WRITE_UUID, CMD_BASIC)
            await asyncio.sleep(1.5)
            await client.stop_notify(NOTIFY_UUID)

            if received:
                v, i, soc, temp = parse_basic(received[0])
                print(f"🔋 電圧:    {v}V")
                print(f"⚡ 電流:    {i}A")
                print(f"📊 SOC:     {soc}%")
                print(f"🌡  温度:    {temp}℃")
                print("\n✅ BMSデータ取得成功")
            else:
                print("❌ データ受信なし")
    except Exception as e:
        print(f"❌ エラー: {e}")

async def main():
    import sys
    if len(sys.argv) < 2:
        await scan_bms()
    else:
        await test_bms(sys.argv[1])

if __name__ == "__main__":
    asyncio.run(main())
