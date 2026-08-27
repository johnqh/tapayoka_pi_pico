# tapayoka_pi_pico

> **Git policy — never auto-commit or auto-push.** Leave your work in the working tree.
> Run `git commit`, `git push`, `gh pr create`, or `scripts/push_all.sh` **only when the user
> explicitly asks in that turn**. Approval for an earlier change does not carry forward, and
> finishing a task is not permission to commit it.

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

## Local dev (WebSocket, no BLE/GPIO)

`TRANSPORT=ws python -m src.main` runs a CPython WebSocket transport
(`TapayokaPicoWs`) + a browser kiosk instead of BLE, so the firmware logic can
be driven on a Mac. WS on `8765`, kiosk on `8026`, state under `./dev_state/`.
All ws-mode modules (`ws_peripheral`, `kiosk_server`, `kiosk_state`) are
CPython-only and are never imported on the Pico (the `ws` branch is unreachable
in MicroPython, which has no `os.getenv`).

## Deployment

Flash MicroPython firmware to Pico W, then copy src/ files to device.

## Git Workflow

- Do not use feature branches for code changes. Always stay on the current branch.
