"""Tapayoka Pico W - peripheral entry point (BLE on device, WS for local dev)."""

import os

# os.getenv is absent in MicroPython -> getattr default makes _TRANSPORT "ble"
# on-device, so the ws branch (and all CPython-only imports) is unreachable.
_getenv = getattr(os, "getenv", lambda k, d=None: d)
_TRANSPORT = _getenv("TRANSPORT", "ble").lower()

# In WS dev mode (CPython on a laptop) redirect wallet + kiosk storage off the
# filesystem root so we neither need root nor pollute "/". This block is only
# reachable under CPython, where os.environ exists.
if _TRANSPORT == "ws":
    os.environ.setdefault("WALLET_KEY_FILE", "./dev_state/wallet_key.json")
    os.environ.setdefault("SERVER_WALLET_FILE", "./dev_state/server_wallet.txt")
    os.environ.setdefault("KIOSK_STATE_DIR", "./dev_state")
    os.makedirs(os.environ["KIOSK_STATE_DIR"], exist_ok=True)

try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

from .config import BLE_DEVICE_NAME_PREFIX, DEFAULT_RELAY_PIN
from .eth_wallet import EthWallet
from .gpio_control import RelayController
from .ble_peripheral import TapayokaPicoBle


def main():
    print("=" * 40)
    print("Tapayoka Pico W -", _TRANSPORT.upper())
    print("=" * 40)

    wallet = EthWallet()
    relay = RelayController(pin_num=DEFAULT_RELAY_PIN)

    server_wallet = EthWallet.load_server_wallet()
    if server_wallet:
        print("[Config] Server wallet:", server_wallet[:10], "...")
    else:
        print("[Config] No server wallet (awaiting setup via " + _TRANSPORT.upper() + ")")

    if _TRANSPORT == "ws":
        from .kiosk_server import start_kiosk_server
        from .kiosk_state import generate_deep_link, update_kiosk_state
        from .ws_peripheral import TapayokaPicoWs

        state_dir = os.environ["KIOSK_STATE_DIR"]
        kiosk_port = int(_getenv("KIOSK_PORT", "8026"))
        start_kiosk_server(state_dir, port=kiosk_port)

        device_name = BLE_DEVICE_NAME_PREFIX + wallet.address_short
        deep_link = generate_deep_link(
            transport="ws",
            wallet_address=wallet.address,
            device_name=device_name,
            state_dir=state_dir,
        )
        update_kiosk_state(os.path.join(state_dir, "state.json"),
                           status="QR", qr_url=deep_link, message="Scan to connect")

        peripheral = TapayokaPicoWs(wallet, relay, state_dir)
        try:
            peripheral.start()
        except KeyboardInterrupt:
            print("Shutting down...")
            relay.cleanup()
    else:
        ble = TapayokaPicoBle(wallet, relay)
        try:
            asyncio.run(ble.start())
        except KeyboardInterrupt:
            print("Shutting down...")
            relay.cleanup()


if __name__ == "__main__":
    main()
