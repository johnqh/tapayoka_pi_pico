"""WebSocket transport for the Tapayoka Pico (local development only).

CPython-only. main.py imports this only under TRANSPORT=ws, which is
unreachable on the Pico (MicroPython has no os.getenv), so websockets / the
kiosk modules are never imported on-device.
"""

import asyncio
import json
import os
import time

from tapayoka_pi_core import build_device_info_data

from .command_handler import CommandHandler
from .config import BLE_DEVICE_NAME_PREFIX, DEFAULT_RELAY_PIN
from .eth_wallet import _hex, _random_bytes
from .kiosk_state import generate_deep_link, update_kiosk_state


class TapayokaPicoWs:
    """WebSocket server that mirrors the Pico BLE peripheral semantics."""

    def __init__(self, wallet, relay, kiosk_state_dir):
        self._wallet = wallet
        self._relay = relay
        self._kiosk_state_dir = kiosk_state_dir
        self._handler = CommandHandler(wallet, relay)
        # Cache the QR deep link so the QR view can be restored on disconnect.
        # The PNG is written once at startup by main.py (state_dir set there);
        # here state_dir=None so we only need the URL string.
        self._deep_link = generate_deep_link(
            transport="ws",
            wallet_address=wallet.address,
            device_name=self.device_name,
            state_dir=None,
        )

    @property
    def device_name(self):
        return BLE_DEVICE_NAME_PREFIX + self._wallet.address_short

    def _state_file(self):
        return os.path.join(self._kiosk_state_dir, "state.json")

    def _build_device_info(self):
        data = build_device_info_data(
            self._wallet.address,
            "0.1.0-pico",
            bool(self._wallet.load_server_wallet()),
            int(time.time()),
            _hex(_random_bytes(16)),
        )
        return {"data": data, "signing": self._wallet.sign_response(data)}

    def _show_running(self, cmd_env):
        """Emit a RUNNING kiosk state derived from an EXECUTE command envelope."""
        data = cmd_env.get("data", {})
        offering = data.get("offeringType", "TRIGGER")
        signals = data.get("signals")
        if offering == "FIXED" and signals:
            pin = int(signals[0]["pinNumber"])
            duration = int(sum(s["duration"] for s in signals))
        elif offering == "TRIGGER":
            pin = DEFAULT_RELAY_PIN
            duration = 1
        else:
            pin = DEFAULT_RELAY_PIN
            duration = int(data.get("seconds", 0))
        update_kiosk_state(
            self._state_file(),
            status="RUNNING",
            pin=pin,
            duration_seconds=duration,
            started_at=int(time.time()),
        )

    async def _handle_connection(self, ws):
        from websockets.exceptions import ConnectionClosed

        remote = ws.remote_address
        print("[WS] Client connected:", remote)
        update_kiosk_state(self._state_file(), status="CONNECTED", message="Connected")

        await ws.send(json.dumps({
            "type": "announce",
            "data": {
                "deviceName": self.device_name,
                "walletAddress": self._wallet.address,
            },
        }))

        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except (ValueError, TypeError) as e:
                    await ws.send(json.dumps({
                        "type": "response",
                        "data": {"status": "ERROR", "message": str(e)},
                    }))
                    continue

                msg_type = msg.get("type", "")
                if msg_type == "read_device_info":
                    await ws.send(json.dumps({
                        "type": "device_info",
                        "data": self._build_device_info(),
                    }))
                elif msg_type == "command":
                    cmd_env = msg.get("data", {})
                    result = self._handler.handle(cmd_env)
                    await ws.send(json.dumps({"type": "response", "data": result}))
                    if result.get("status") == "NOT_CONFIGURED":
                        print("[WS] Closing connection: device not configured")
                        await ws.close()
                        break
                    if (result.get("status") == "OK"
                            and str(cmd_env.get("command", "")).upper() == "EXECUTE"):
                        self._show_running(cmd_env)
                else:
                    await ws.send(json.dumps({
                        "type": "response",
                        "data": {"status": "ERROR", "message": "Unknown type: " + msg_type},
                    }))
        except ConnectionClosed:
            pass
        finally:
            print("[WS] Client disconnected:", remote)
            update_kiosk_state(self._state_file(), status="QR",
                               qr_url=self._deep_link, message="Scan to connect")
            if self._relay.is_active and not self._relay.is_sequence_running:
                print("[WS] Safety deactivation on disconnect")
                self._relay.deactivate()

    def start(self, host="0.0.0.0", port=8765):
        print("[WS] Starting WebSocket peripheral on ws://{}:{}".format(host, port))
        asyncio.run(self._serve(host, port))

    async def _serve(self, host, port):
        import websockets

        async with websockets.serve(self._handle_connection, host, port):
            print("[WS] Peripheral published:", self.device_name)
            await asyncio.Future()  # run forever

    def stop(self):
        self._relay.cleanup()
        print("[WS] Peripheral stopped")
