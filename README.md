# tapayoka_pi_pico

MicroPython BLE peripheral firmware for Raspberry Pi Pico W. Same protocol as `tapayoka_pi` but for constrained hardware.

## Shared core

This repo uses the same shared policy logic as `tapayoka_pi`, but it does not consume that logic from PyPI at runtime.

- `tapayoka_pi_core` is the source of truth for shared logic
- this repo vendors a local copy under `src/tapayoka_pi_core/`
- the Pico code imports `tapayoka_pi_core` locally from this repository
- update the vendored copy with `python scripts/sync_core.py`

## Why local copy

MicroPython targets are constrained and should not depend on PyPI installation flow at runtime. Keeping the shared package local makes the Pico firmware self-contained while still reusing the same logic.

## Setup

1. Flash MicroPython firmware to Pico W
2. Copy `src/` files to device, including the local `tapayoka_pi_core` package

## Architecture

- **BLE**: aioble (MicroPython BLE library)
- **Crypto**: Pure-Python keccak-256 + secp256k1 (sign + ecrecover), EIP-191; no eth-account on device
- **Protocol**: `EXECUTE`/`{data,signing}` envelope with `offeringType`; signal sequences for FIXED tiers (parity with `tapayoka_pi`)
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
