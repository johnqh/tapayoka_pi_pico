"""BLE GATT peripheral for Pico W using aioble."""

import json
import time

try:
    import aioble
    import bluetooth
    import asyncio
    AIOBLE_AVAILABLE = True
except ImportError:
    AIOBLE_AVAILABLE = False
    print("[BLE] aioble not available")

from .config import (
    BLE_CHAR_COMMAND_UUID, BLE_CHAR_DEVICE_INFO_UUID, BLE_CHAR_RESPONSE_UUID,
    BLE_DEVICE_NAME_PREFIX, BLE_SERVICE_UUID,
)
from .command_handler import CommandHandler
from .eth_wallet import _hex, _random_bytes
from tapayoka_pi_core import build_device_info_data


def _uuid(s):
    if AIOBLE_AVAILABLE:
        return bluetooth.UUID(s)
    return s


class TapayokaPicoBle:
    def __init__(self, wallet, relay):
        self._wallet = wallet
        self._relay = relay
        self._handler = CommandHandler(wallet, relay)

    def _build_device_info(self):
        data = build_device_info_data(
            self._wallet.address,
            "0.1.0-pico",
            bool(self._wallet.load_server_wallet()),
            int(time.time()),
            _hex(_random_bytes(16)),
        )
        return {"data": data, "signing": self._wallet.sign_response(data)}

    async def start(self):
        if not AIOBLE_AVAILABLE:
            print("[BLE] Cannot start - aioble not available")
            return

        device_name = BLE_DEVICE_NAME_PREFIX + self._wallet.address_short
        service = aioble.Service(_uuid(BLE_SERVICE_UUID))
        device_info_char = aioble.Characteristic(service, _uuid(BLE_CHAR_DEVICE_INFO_UUID), read=True)
        command_char = aioble.Characteristic(service, _uuid(BLE_CHAR_COMMAND_UUID), write=True, capture=True)
        response_char = aioble.Characteristic(service, _uuid(BLE_CHAR_RESPONSE_UUID), read=True, notify=True)
        aioble.register_services(service)

        print("[BLE] Starting as:", device_name)

        while True:
            try:
                connection = await aioble.advertise(250_000, name=device_name, services=[_uuid(BLE_SERVICE_UUID)])
                print("[BLE] Connected:", connection.device)

                device_info_char.write(json.dumps(self._build_device_info()).encode())

                while connection.is_connected():
                    try:
                        _, data = await asyncio.wait_for(command_char.written(), timeout=30)
                        response = self._handle_command(data)
                        response_char.write(json.dumps(response).encode())
                        response_char.notify(connection)
                    except asyncio.TimeoutError:
                        pass

                print("[BLE] Disconnected")
                if self._relay.is_active and not self._relay.is_sequence_running:
                    self._relay.deactivate()
            except Exception as e:
                print("[BLE] Error:", e)
                await asyncio.sleep(1)

    def _handle_command(self, data):
        try:
            return self._handler.handle(json.loads(data.decode()))
        except (ValueError, KeyError) as e:
            return {"status": "ERROR", "message": str(e)}
