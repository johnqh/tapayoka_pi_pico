# Pico WebSocket + Kiosk Dev Harness — Design

**Date:** 2026-06-26
**Status:** Approved
**Repo:** `tapayoka_pi_pico`

## Problem

`tapayoka_pi_pico` is BLE-only MicroPython firmware. Its `main.py` instantiates
`TapayokaPicoBle` and calls `asyncio.run(ble.start())` with no transport switch,
and it depends on `aioble` / `bluetooth` (BLE) and `machine.Pin` (GPIO) — none of
which exist on macOS/CPython. There is therefore no way to run or drive the
firmware logic on a developer laptop.

`tapayoka_pi` solves the same problem with a `TRANSPORT=ws` WebSocket transport
(`TapayokaWsPeripheral`) plus a browser kiosk display. This spec ports that
capability to `tapayoka_pi_pico` so the Pico firmware logic can be exercised
end-to-end on a Mac, with the same wire protocol the buyer app already speaks.

## Goals

- Run the Pico firmware logic on CPython over WebSocket via `TRANSPORT=ws`, with
  parity to `tapayoka_pi`'s ws message protocol.
- Provide a browser kiosk (QR → Connected → Running job countdown) for visual
  testing, at full parity with the pi kiosk UX.
- Keep **all** CPython-only / dev-only code behind the `ws`-mode branch so nothing
  new is ever imported on the real Pico W.
- Do not alter on-device BLE behavior.

## Non-goals

- Real WebSockets on Pico W hardware over WiFi (that would be a firmware feature,
  not a dev harness).
- Any LED service / `AppConfig` abstraction (the pico has neither; it uses a
  `RelayController` and flat `config.py` constants).
- Refactoring the shared firmware command handler or crypto.

## Key design decisions

### 1. Transport switch in `main.py`

Mirror `tapayoka_pi`: `main.py` reads `TRANSPORT` (default `ble`). In `ws` mode it
runs the new WebSocket peripheral; otherwise it runs the existing BLE path
unchanged.

MicroPython has no `os.getenv`, so the switch uses a guarded accessor:

```python
_getenv = getattr(os, "getenv", lambda k, d=None: d)
_TRANSPORT = _getenv("TRANSPORT", "ble").lower()
```

On the Pico, `getenv` is absent → the lambda returns the default `"ble"`, so the
`ws` branch (and every CPython-only import inside it) is unreachable on-device.

### 2. Dev paths default under `./dev_state/`

The firmware writes its wallet to `/wallet_key.json` and server wallet to
`/server_wallet.txt` (absolute root paths — correct on a Pico, but on a Mac they
require root and pollute `/`). In `ws` mode, `main.py` sets these (and the kiosk
state dir) to default under `./dev_state/` **before** importing the `src` modules
that read `config.py`:

```python
if _TRANSPORT == "ws":
    os.environ.setdefault("WALLET_KEY_FILE", "./dev_state/wallet_key.json")
    os.environ.setdefault("SERVER_WALLET_FILE", "./dev_state/server_wallet.txt")
    os.environ.setdefault("KIOSK_STATE_DIR", "./dev_state")
    os.makedirs(os.environ["KIOSK_STATE_DIR"], exist_ok=True)
```

This block only runs when `_TRANSPORT == "ws"`, which is unreachable on the Pico,
so `os.environ` (also absent in MicroPython) is never referenced there.

### 3. `config.py` becomes env-aware (MicroPython-safe)

```python
_getenv = getattr(os, "getenv", lambda k, d=None: d)
WALLET_KEY_FILE    = _getenv("WALLET_KEY_FILE",    "/wallet_key.json")
SERVER_WALLET_FILE = _getenv("SERVER_WALLET_FILE", "/server_wallet.txt")
```

On-device behavior is unchanged: with no `getenv`, the defaults are identical to
the current hardcoded constants.

### 4. `RUNNING` kiosk wiring lives in `ws_peripheral`, not `CommandHandler`

In `tapayoka_pi`, `CommandHandler` itself calls `update_kiosk_state(..., "RUNNING")`.
That cannot be replicated here: the pico's `CommandHandler` is **shared firmware**
that runs on the real Pico, where there is no kiosk and `http.server` / `qrcode`
do not exist. Keeping the firmware handler pure, the `RUNNING` update is emitted by
the dev-only `ws_peripheral` after a successful `EXECUTE`, deriving pin + duration
from the command data:

- `offeringType == "FIXED"` with `signals` → `pin = signals[0]["pinNumber"]`,
  `duration = sum(s["duration"] for s in signals)`
- `offeringType == "TRIGGER"` → `pin = DEFAULT_RELAY_PIN`, `duration = 1`
- otherwise → `pin = DEFAULT_RELAY_PIN`, `duration = int(seconds)`

The `RUNNING` state is emitted only when the handler returns `status == "OK"`.

## Components

### `src/ws_peripheral.py` (new, CPython-only)

`class TapayokaPicoWs(wallet, relay, kiosk_state_dir)`:

- `device_name` → `BLE_DEVICE_NAME_PREFIX + wallet.address_short`.
- Builds and caches the deep link via `generate_deep_link(transport="ws", ...)` so
  the QR view can be restored on disconnect (PNG itself is written once at startup
  by `main.py`; here `state_dir=None`).
- `_build_device_info()` → `{data, signing}` with firmware `"0.1.0-pico"`, mirroring
  `ble_peripheral._build_device_info` (uses `build_device_info_data`, `_hex`,
  `_random_bytes`, `wallet.sign_response`).
- `async _handle_connection(ws)`:
  - On connect: print, `update_kiosk_state(CONNECTED)`, send
    `{"type":"announce","data":{deviceName, walletAddress}}`.
  - Per message: parse JSON; dispatch by `type`:
    - `read_device_info` → `{"type":"device_info","data":{data, signing}}`
    - `command` → `result = handler.handle(data)`;
      `{"type":"response","data":result}`; if `result["status"] == "OK"` and the
      command was `EXECUTE`, emit `RUNNING` (see decision 4).
    - unknown type → error `response`.
    - `json.JSONDecodeError` → error `response`.
  - On disconnect (`finally`): `update_kiosk_state(QR, qr_url=deep_link)`; if
    `relay.is_active and not relay.is_sequence_running`, `relay.deactivate()`.
- `start(host="0.0.0.0", port=8765)` → `asyncio.run(self._serve(...))`; `_serve`
  uses `websockets.serve` and runs forever.
- `stop()` → `relay.cleanup()`.

### `src/kiosk_server.py` (new, ported ~verbatim)

Stdlib `http.server` `HTTPServer` in a daemon thread. Serves the embedded
`KIOSK_HTML` page (QR / Connected / Running views, polling `state.json` each
second), `state.json`, and `qr.png`. **Drop** the `/qrcode.min.js` static route
from the pi version — the pico has no `static/` dir and the embedded HTML renders
the QR via the server-generated `qr.png`, not client-side JS.
`start_kiosk_server(state_dir, port=8026)` returns the server.

### `src/kiosk_state.py` (new, ported ~verbatim)

`_write_json_atomic`, `update_kiosk_state(state_file, *, status, qr_url, message,
duration_seconds, started_at, pin)`, `_get_local_ip`, and
`generate_deep_link(transport, wallet_address, device_name, ws_port=8765,
state_dir=None)` → `tapayokav://connect?...&wsUrl=ws://<ip>:8765` plus an optional
`qr.png` written to `state_dir`.

### `src/main.py` (edited)

- Top of file: `os` import + `_getenv` + `_TRANSPORT`; in `ws` mode set dev-path
  env defaults and `makedirs` the state dir (decision 2).
- `main()`: build `wallet` and `relay` as today. Then branch:
  - `ws`: read `KIOSK_PORT` (default `8026`); `start_kiosk_server(state_dir, port)`;
    compute `device_name`; `deep_link = generate_deep_link(transport="ws", ...,
    state_dir=state_dir)` (writes `qr.png`); `update_kiosk_state(QR,
    qr_url=deep_link, message="Scan to connect")`; run
    `TapayokaPicoWs(wallet, relay, state_dir).start()`; on `KeyboardInterrupt`,
    `relay.cleanup()`.
  - else: existing BLE path, unchanged.

### `requirements-dev.txt` (edited)

Add `websockets` and `qrcode[pil]`.

### `.gitignore` (edited)

Add `dev_state/`.

### `README.md` / `CLAUDE.md` (edited)

Document the `TRANSPORT=ws` dev mode: the run command, the two ports
(ws `8765`, kiosk `8026`), and that state/wallet live under `./dev_state/`.

## Wire protocol (parity with `tapayoka_pi`)

| Client sends | Server replies |
|---|---|
| (on connect) | `{"type":"announce","data":{deviceName, walletAddress}}` |
| `{"type":"read_device_info"}` | `{"type":"device_info","data":{data, signing}}` |
| `{"type":"command","data":{...}}` | `{"type":"response","data":<handler result>}` |
| unknown / bad JSON | `{"type":"response","data":{"status":"ERROR","message":...}}` |

## Testing

- `tests/test_ws_peripheral.py` — start `TapayokaPicoWs` on an ephemeral port,
  connect a real `websockets` client, and assert: `announce` shape; `device_info`
  envelope whose `signing.signature` recovers to the device address (via
  `eth_account`, matching `test_ble_peripheral.py` conventions); a `command`
  round-trip (`SETUP_SERVER` → `OK`, then `EXECUTE` → `OK`). Use `asyncio.run`
  around an async scenario — no new pytest plugin. Wallet files redirected to
  `tmp_path` via the same `patch` fixture pattern as `test_ble_peripheral.py`.
- `tests/test_kiosk.py` — `update_kiosk_state` writes the expected JSON keys for
  `QR` / `CONNECTED` / `RUNNING`; `generate_deep_link(transport="ws", ...)` returns
  a `tapayokav://` URL containing `wsUrl=ws://` and writes `qr.png` when
  `state_dir` is set.

All new dev-only modules are import-guarded behind `ws` mode, so the existing
MicroPython-oriented tests and on-device imports are unaffected.

## Known limitation (documented, not fixed)

The mock `RelayController` (CPython, `machine` absent) has `self._timer = None`, so
`activate(duration_seconds=...)` logs "Relay ON" but does not self-deactivate on a
timer. The kiosk `RUNNING` view still counts down correctly (the countdown is
client-side from `started_at` + `duration_seconds`), and disconnect-safety
deactivation still fires. This is a pre-existing characteristic of
`gpio_control.py`'s mock mode and is out of scope.

## Run

```bash
pip install -r requirements-dev.txt
TRANSPORT=ws python -m src.main
# WebSocket peripheral: ws://0.0.0.0:8765
# Kiosk display:        http://0.0.0.0:8026
# Wallet + kiosk state: ./dev_state/
```
