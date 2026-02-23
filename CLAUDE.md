# tapayoka_pi_pico

MicroPython BLE peripheral firmware for Raspberry Pi Pico W. Same protocol as tapayoka_pi but for constrained hardware.

## Architecture

- **BLE**: aioble (MicroPython BLE library)
- **Crypto**: Lightweight secp256k1 + keccak256 (no eth-account)
- **GPIO**: MicroPython machine.Pin API
- **No Docker**: Firmware flashed directly to Pico W

## Commands

```bash
pip install pytest
pytest tests/ -v
```

## Deployment

Flash MicroPython firmware to Pico W, then copy src/ files to device.
