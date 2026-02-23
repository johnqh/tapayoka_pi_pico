"""BLE GATT peripheral for Pico W using aioble."""

import json

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
from .eth_wallet import EthWallet
from .gpio_control import RelayController


def _uuid(s):
    if AIOBLE_AVAILABLE:
        return bluetooth.UUID(s)
    return s


class TapayokaPicoBle:
    def __init__(self, wallet, relay):
        self._wallet = wallet
        self._relay = relay
        self._server_wallet = EthWallet.load_server_wallet()

    async def start(self):
        if not AIOBLE_AVAILABLE:
            print("[BLE] Cannot start - aioble not available")
            return

        device_name = BLE_DEVICE_NAME_PREFIX + self._wallet.address_short
        service = aioble.Service(_uuid(BLE_SERVICE_UUID))
        device_info_char = aioble.Characteristic(service, _uuid(BLE_CHAR_DEVICE_INFO_UUID), read=True)
        command_char = aioble.Characteristic(service, _uuid(BLE_CHAR_COMMAND_UUID), write=True, capture=True)
        response_char = aioble.Characteristic(service, _uuid(BLE_CHAR_RESPONSE_UUID), notify=True)
        aioble.register_services(service)

        print("[BLE] Starting as:", device_name)

        while True:
            try:
                connection = await aioble.advertise(250_000, name=device_name, services=[_uuid(BLE_SERVICE_UUID)])
                print("[BLE] Connected:", connection.device)

                challenge = self._wallet.sign_challenge()
                info = {**challenge, "firmwareVersion": "0.1.0-pico", "hasServerWallet": bool(self._server_wallet)}
                device_info_char.write(json.dumps(info).encode())

                while connection.is_connected():
                    try:
                        _, data = await asyncio.wait_for(command_char.written(), timeout=30)
                        response = self._handle_command(data)
                        response_char.write(json.dumps(response).encode())
                        response_char.notify(connection)
                    except asyncio.TimeoutError:
                        pass

                print("[BLE] Disconnected")
                if self._relay.is_active:
                    self._relay.deactivate()
            except Exception as e:
                print("[BLE] Error:", e)
                await asyncio.sleep(1)

    def _handle_command(self, data):
        try:
            cmd = json.loads(data.decode())
            command = cmd.get("command", "").upper()

            if command == "SETUP_SERVER":
                address = cmd.get("payload", "")
                if not address or not address.startswith("0x"):
                    return {"status": "ERROR", "message": "Invalid address"}
                EthWallet.save_server_wallet(address)
                self._server_wallet = address
                return {"status": "OK", "message": "Server wallet configured"}
            elif command == "AUTHORIZE":
                payload = cmd.get("payload", "")
                signature = cmd.get("signature", "")
                if not self._server_wallet:
                    return {"status": "ERROR", "message": "No server wallet"}
                if not self._wallet.verify_server_signature(payload, signature, self._server_wallet):
                    return {"status": "UNAUTHORIZED", "message": "Invalid signature"}
                auth = json.loads(payload)
                seconds = auth.get("seconds", 0)
                service_type = auth.get("serviceType", "TRIGGER")
                self._relay.activate(duration_seconds=1 if service_type == "TRIGGER" else seconds)
                return {"status": "OK", "message": "Authorized for {}s".format(seconds)}
            elif command == "ON":
                self._relay.activate(duration_seconds=cmd.get("seconds", 0))
                return {"status": "OK", "message": "Activated"}
            elif command == "OFF":
                self._relay.deactivate()
                return {"status": "OK", "message": "Deactivated"}
            elif command == "STATUS":
                return {"status": "OK", "data": json.dumps({
                    "active": self._relay.is_active,
                    "walletAddress": self._wallet.address,
                    "hasServerWallet": bool(self._server_wallet),
                })}
            else:
                return {"status": "ERROR", "message": "Unknown command"}
        except (ValueError, KeyError) as e:
            return {"status": "ERROR", "message": str(e)}
