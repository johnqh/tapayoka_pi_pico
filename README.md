# tapayoka_pi_pico

MicroPython BLE peripheral firmware for Raspberry Pi Pico W. Same protocol as `tapayoka_pi` but for constrained hardware.

## Setup

1. Flash MicroPython firmware to Pico W
2. Copy `src/` files to device

## Architecture

- **BLE**: aioble (MicroPython BLE library)
- **Crypto**: Lightweight secp256k1 + keccak256 (no eth-account, runs on constrained hardware)
- **GPIO**: MicroPython `machine.Pin` API for relay control

## Development

```bash
pip install pytest
pytest tests/ -v
```

## Related Packages

- `tapayoka_pi` -- Full Raspberry Pi variant (Python, same BLE protocol)
- `tapayoka_api` -- Backend API server
- `tapayoka_buyer_app_rn` -- Buyer app that communicates via BLE

## License

BUSL-1.1
