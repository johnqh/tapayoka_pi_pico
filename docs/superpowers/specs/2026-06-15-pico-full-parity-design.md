# tapayoka_pi_pico full-parity MicroPython port

**Date:** 2026-06-15
**Repo:** `tapayoka_pi_pico` (MicroPython on Raspberry Pi Pico W)
**Status:** Approved design

## Problem

`tapayoka_pi_pico` is meant to be the constrained-hardware sibling of `tapayoka_pi` ("same BLE protocol"), but it has drifted and is non-functional against the live system:

- **Crypto is a stub.** `eth_wallet.py` uses `sha256` in place of keccak-256, "signs" the challenge as `sha256(private_key + payload)` (not a secp256k1 ECDSA signature), and `verify_server_signature` only checks the signature is 32/64/65 bytes — it accepts **any** signature of the right length. The device cannot interoperate with the server/app (which verify via `ethers.verifyMessage`) and is insecure.
- **Old protocol.** It handles `AUTHORIZE` with separate `payload`+`signature` and a `serviceType` field, plus `ON`/`OFF`/`STATUS`. Current `tapayoka_pi` uses `EXECUTE` with a `{data, signing}` envelope and `offeringType`, and `SETUP_SERVER` with a *signed* envelope.
- **No sequences.** `RelayController` drives a single pin; it cannot run a FIXED tier's `signals` sequence.

## Goal

Bring pico to full functional parity with current `tapayoka_pi`: real Ethereum crypto, the `EXECUTE`/`{data,signing}`/`offeringType` protocol, multi-pin sequential signal execution, and run-to-completion on disconnect — all MicroPython-compatible.

## MicroPython constraints

- No `RPi.GPIO` → `machine.Pin` / `machine.Timer`.
- No `threading` → `asyncio` (aioble runs on it). MicroPython has arbitrary-precision ints (so pure-Python 256-bit ECC works) and `os.urandom` (Pico W hardware RNG).
- `hashlib` has no keccak → keccak must be pure-Python.
- Tests run on CPython (`pytest`) with `machine`/`aioble` absent (mock mode).

## Design

### Module structure (`src/`)

| Module | Status | Responsibility |
|---|---|---|
| `keccak.py` | new | Pure-Python keccak-256 (Keccak-f[1600], rate 136 bytes) |
| `secp256k1.py` | new | Curve math: `sign(msg_hash, priv)→(r,s,v)`, `recover(msg_hash,r,s,v)→pubkey_bytes`, `privkey_to_pubkey`, `pubkey_to_address` |
| `eth_wallet.py` | rewrite | Real key/address; EIP-191 `sign_challenge()`; `verify_signed_payload(envelope, expected_signer=None)` |
| `command_handler.py` | new | `validate_signals` + `CommandHandler` (SETUP_SERVER/EXECUTE, envelope verify, dispatch) |
| `gpio_control.py` | rewrite | `RelayController`: multi-pin, `run_sequence` (async), `is_sequence_running`, `activate`/`deactivate` |
| `ble_peripheral.py` | update | `{data,signing}` device-info; delegate to `CommandHandler`; run-to-completion on disconnect |
| `main.py` | minor | wire `CommandHandler` into the peripheral |

### Crypto

**keccak.py** — standard Keccak-256 over bytes; pure-Python state array of 25 lanes, big-int/bytearray ops only (MicroPython-safe). `keccak256(data: bytes) -> bytes` (32 bytes).

**secp256k1.py** — curve constants (p, n, Gx, Gy, a=0, b=7). Jacobian or affine point add/double + double-and-add scalar mul. Functions:
- `privkey_to_pubkey(priv: bytes) -> (x, y)`
- `pubkey_to_address(x, y) -> str` = `"0x" + keccak256(x.to_bytes(32)+y.to_bytes(32))[-20:].hex()`
- `sign(msg_hash: bytes, priv: bytes) -> (r, s, v)` — ECDSA; nonce `k` from `os.urandom`, retry until `r != 0` and `s != 0`; low-`s` normalization; `v ∈ {27,28}` recovery id.
- `recover(msg_hash: bytes, r, s, v) -> (x, y)` — recover R from `r` + parity, `Q = r⁻¹ (s·R − z·G)`.

**eth_wallet.py** — rewrite around the two modules:
- Key load/create stays file-based (`/wallet_key.json`); address derived via `pubkey_to_address` (real keccak).
- `_eip191_hash(message: str) -> bytes` = `keccak256(b"\x19Ethereum Signed Message:\n" + str(len(msg_bytes)).encode() + msg_bytes)`.
- `sign_challenge()` → returns pi's envelope `{ "data": {walletAddress, firmwareVersion, hasServerWallet, timestamp, nonce}, "signing": {walletAddress, message, signature} }`, where `message = json.dumps(data)` and `signature` is the recoverable EIP-191 sig hex (`0x` + r(32)‖s(32)‖v(1)).
- `verify_signed_payload(envelope, expected_signer=None) -> bool`: read `data`/`signing`; recover signer from `_eip191_hash(signing["message"])` + signature; require `signing["message"] == json.dumps(data)` (after popping optional `signing_timestamp`, with freshness ≤ 30s if present); if `expected_signer`, require recovered == it. Mirrors `tapayoka_pi`'s `verify_signed_payload` semantics so the same server payloads verify identically.

### Execution — async sequences

`gpio_control.py` `RelayController`:
- `activate(duration_seconds=0)` / `deactivate()` — single default pin (`DEFAULT_RELAY_PIN=15`) via `machine.Timer` ONE_SHOT (unchanged behavior).
- `_ensure_pin(n)` — lazy `machine.Pin(n, OUT, value=0)`, tracked in a set for cleanup.
- `run_sequence(signals) -> bool` — if a sequence is running, return `False` (BUSY); else set `is_sequence_running`, `asyncio.create_task(self._run_sequence(signals))`, return `True`. `_run_sequence` iterates: `_ensure_pin(pin)`, `pin.value(1)`, `await asyncio.sleep(duration)`, `pin.value(0)`; `finally` forces all touched pins low and clears the flag.
- `is_sequence_running` property; `cleanup()` drives all touched pins low.

Async (not threads) is the idiomatic aioble model and makes **run-to-completion** natural: the sequence task is independent of the BLE connection and is never cancelled on disconnect.

### Protocol — `command_handler.py`

`validate_signals(signals)` — list of `{pinNumber:int in 0..27, duration: 0<n≤3600}`, else `None` (matches pi).

`CommandHandler(wallet, relay)` with `handle(msg) -> {status, message}`:
- `SETUP_SERVER`: `verify_signed_payload(msg)`; on success record `signing.walletAddress` as server wallet (via `EthWallet.save_server_wallet`); else UNAUTHORIZED/ERROR.
- `EXECUTE`: require stored server wallet (ERROR if none); `verify_signed_payload(msg, expected_signer=server_wallet)` (UNAUTHORIZED if not); then read `data.offeringType`/`seconds`/`signals`:
  - `FIXED` + non-empty valid signals → `run_sequence` (BUSY if running) → OK.
  - `FIXED` + no signals → `activate(seconds)` → OK (back-compat).
  - `TIMED` → `activate(seconds)`; `TRIGGER` → `activate(1)`.
- Unknown command → ERROR. Drops `ON`/`OFF`/`STATUS`.

### BLE peripheral (`ble_peripheral.py`)

- Device-info read writes the `{data, signing}` envelope from `wallet.sign_challenge()`.
- On command written → `CommandHandler.handle(json.loads(data))` → notify `{status, message}`.
- Disconnect: `if relay.is_active and not relay.is_sequence_running: relay.deactivate()`.
- `__init__` builds `CommandHandler(wallet, relay)`.

### Testing (pytest on CPython; `machine`/`aioble` mocked)

- **Crypto vs oracle** (dev-only `eth_account`/`eth-hash`):
  - `keccak256` matches `eth_hash` for known vectors.
  - `pubkey_to_address`/wallet address matches `eth_account.Account.from_key` for known private keys.
  - `sign`→`recover` round-trips; recovered address correct.
  - A signature produced by `eth_account` (the *server* side) verifies via `verify_signed_payload` and recovers to the signer; tampered `data`/wrong signer fail.
- **RelayController**: `run_sequence` drives pins in order (patch `asyncio.sleep` to a no-op; drive the task with `asyncio.run`/`get_event_loop`), all pins low at end, busy rejection.
- **CommandHandler**: FIXED→sequence, FIXED-no-signals→activate, TIMED→activate, TRIGGER→1s, no-wallet→ERROR, bad-sig→UNAUTHORIZED, invalid-signals→ERROR, SETUP_SERVER envelope verify.
- Replace the stale `ON/OFF/STATUS/AUTHORIZE` peripheral tests.
- Add `requirements-dev.txt` (`pytest`, `eth-account`) and update `.github/workflows/ci-cd.yml` to install it.

### Performance

Pure-Python ECC on the Pico: `sign` ≈ one scalar mult, `recover` ≈ two — on the order of seconds. Acceptable: device-info signs once per connection, verify runs once per command.

## Out of scope

- WebSocket transport (pico is real BLE hardware; WS was a `tapayoka_pi` dev-only fallback).
- RFC6979 deterministic nonces — v1 uses hardware `os.urandom`; deterministic nonce is a future hardening item.
- Changing TIMED/TRIGGER disconnect behavior (only sequences run to completion, matching pi).

## Shipping

pico has no npm package, so `push_all.sh` skips it. Deploy by committing and `git push` to `main` (as was done for `tapayoka_pi`). No `tapayoka_types`/`tapayoka_api` changes are needed — pico consumes the existing protocol.
