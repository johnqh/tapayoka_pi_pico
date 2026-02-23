"""Tapayoka Pico W - BLE peripheral entry point."""

try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

from .config import DEFAULT_RELAY_PIN
from .eth_wallet import EthWallet
from .gpio_control import RelayController
from .ble_peripheral import TapayokaPicoBle


def main():
    print("=" * 40)
    print("Tapayoka Pico W")
    print("=" * 40)

    wallet = EthWallet()
    relay = RelayController(pin_num=DEFAULT_RELAY_PIN)

    server_wallet = EthWallet.load_server_wallet()
    if server_wallet:
        print("[Config] Server wallet:", server_wallet[:10], "...")
    else:
        print("[Config] No server wallet (awaiting BLE setup)")

    ble = TapayokaPicoBle(wallet, relay)

    try:
        asyncio.run(ble.start())
    except KeyboardInterrupt:
        print("Shutting down...")
        relay.cleanup()


if __name__ == "__main__":
    main()
