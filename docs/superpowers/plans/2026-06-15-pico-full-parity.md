# tapayoka_pi_pico Full-Parity Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `tapayoka_pi_pico` to full functional parity with `tapayoka_pi` — real Ethereum crypto (keccak-256 + secp256k1), the `EXECUTE`/`{data,signing}`/`offeringType` protocol, multi-pin sequential signal execution, and run-to-completion on disconnect — all MicroPython-compatible.

**Architecture:** Pure-Python `keccak.py` and `secp256k1.py` provide hashing and ECDSA sign/recover (MicroPython has arbitrary-precision ints + `os.urandom`). `eth_wallet.py` builds pi's signed `{data,signing}` envelope and verifies server signatures via ecrecover. A transport-agnostic `CommandHandler` mirrors pi; `RelayController` gains multi-pin async sequences. Tests run on CPython with `eth_account`/`eth-hash` as correctness oracles.

**Tech Stack:** MicroPython (Pico W), aioble/asyncio, `machine.Pin`/`machine.Timer`; pytest + eth-account (CPython test oracle).

---

## Test environment

pico targets MicroPython but tests run on CPython. Create a throwaway venv once:

```bash
cd /Users/johnhuang/projects/tapayoka_pi_pico
python3 -m venv .venv && .venv/bin/pip install -q pytest eth-account
```

Run tests with `.venv/bin/python -m pytest tests/ -q`. `.venv/` is git-ignored in Task 1.

Baseline: existing tests target the OLD protocol (`ON/OFF/STATUS/AUTHORIZE`) and the stub wallet; Tasks 4 and 7 replace them.

## File Structure

| Module | Status | Responsibility |
|---|---|---|
| `requirements-dev.txt` | new | pytest + eth-account (CI + local test oracle) |
| `.github/workflows/ci-cd.yml` | modify | install requirements-dev.txt |
| `src/keccak.py` | new | pure-Python keccak-256 |
| `src/secp256k1.py` | new | ECDSA sign/recover, pubkey→address |
| `src/eth_wallet.py` | rewrite | real address, EIP-191 sign_challenge, verify_signed_payload |
| `src/command_handler.py` | new | validate_signals + CommandHandler |
| `src/gpio_control.py` | rewrite | multi-pin RelayController + async run_sequence |
| `src/ble_peripheral.py` | modify | {data,signing} envelope, delegate to CommandHandler, disconnect guard |
| `src/main.py` | modify | construct CommandHandler |
| `tests/*` | add/replace | crypto-oracle, relay, handler, peripheral |

---

## Task 1: Test deps + gitignore + CI

**Files:**
- Create: `requirements-dev.txt`
- Modify: `.github/workflows/ci-cd.yml`
- Modify: `.gitignore`

- [ ] **Step 1: Create requirements-dev.txt**

```
pytest
eth-account
```

- [ ] **Step 2: Update CI install step**

In `.github/workflows/ci-cd.yml`, replace the line `run: pip install pytest` with:

```yaml
        run: pip install -r requirements-dev.txt
```

- [ ] **Step 3: Ignore the local venv**

Append to `.gitignore`:

```
.venv/
__pycache__/
*.pyc
```

- [ ] **Step 4: Create the venv and confirm the oracle imports**

```bash
cd /Users/johnhuang/projects/tapayoka_pi_pico
python3 -m venv .venv && .venv/bin/pip install -q pytest eth-account
.venv/bin/python -c "import eth_account, eth_hash.auto as h; print('oracle ok')"
```
Expected: `oracle ok`.

- [ ] **Step 5: Commit**

```bash
git add requirements-dev.txt .github/workflows/ci-cd.yml .gitignore
git commit -m "chore: add eth-account test oracle and ignore venv"
```

---

## Task 2: keccak-256 (`src/keccak.py`)

**Files:**
- Create: `src/keccak.py`
- Test: `tests/test_keccak.py`

- [ ] **Step 1: Write the failing test (oracle: eth-hash)**

Create `tests/test_keccak.py`:

```python
from eth_hash.auto import keccak as keccak_oracle

from src.keccak import keccak256


def test_empty():
    assert keccak256(b"") == keccak_oracle(b"")


def test_known_vectors():
    for msg in [b"abc", b"hello world", b"\x19Ethereum Signed Message:\n5hello", bytes(range(200))]:
        assert keccak256(msg) == keccak_oracle(msg)


def test_returns_32_bytes():
    assert len(keccak256(b"x")) == 32
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_keccak.py -q`
Expected: FAIL — no module `src.keccak`.

- [ ] **Step 3: Implement keccak.py**

Create `src/keccak.py`:

```python
"""Pure-Python Keccak-256 (Ethereum variant). MicroPython-compatible."""

_RC = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)

# Rotation offsets indexed [x][y].
_R = (
    (0, 36, 3, 41, 18),
    (1, 44, 10, 45, 2),
    (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56),
    (27, 20, 39, 8, 14),
)

_MASK = (1 << 64) - 1


def _rol(value, shift):
    return ((value << shift) | (value >> (64 - shift))) & _MASK


def _keccak_f(lanes):
    for rnd in range(24):
        # theta
        C = [lanes[x] ^ lanes[x + 5] ^ lanes[x + 10] ^ lanes[x + 15] ^ lanes[x + 20] for x in range(5)]
        D = [C[(x + 4) % 5] ^ _rol(C[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(0, 25, 5):
                lanes[x + y] ^= D[x]
        # rho + pi
        B = [0] * 25
        for x in range(5):
            for y in range(5):
                B[y + 5 * ((2 * x + 3 * y) % 5)] = _rol(lanes[x + 5 * y], _R[x][y])
        # chi
        for x in range(5):
            for y in range(0, 25, 5):
                lanes[x + y] = B[x + y] ^ ((~B[(x + 1) % 5 + y]) & B[(x + 2) % 5 + y]) & _MASK
        # iota
        lanes[0] ^= _RC[rnd]
    return lanes


def keccak256(data):
    rate = 136  # bytes (1088 bits) for 256-bit output
    msg = bytearray(data)
    msg.append(0x01)
    while len(msg) % rate != 0:
        msg.append(0x00)
    msg[-1] ^= 0x80

    state = bytearray(200)
    for off in range(0, len(msg), rate):
        for i in range(rate):
            state[i] ^= msg[off + i]
        lanes = [int.from_bytes(state[8 * j:8 * j + 8], "little") for j in range(25)]
        lanes = _keccak_f(lanes)
        for j in range(25):
            state[8 * j:8 * j + 8] = lanes[j].to_bytes(8, "little")
    return bytes(state[:32])
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_keccak.py -q`
Expected: PASS (3 tests). If any vector mismatches, the `_R`/pi indexing is the place to check against the oracle.

- [ ] **Step 5: Commit**

```bash
git add src/keccak.py tests/test_keccak.py
git commit -m "feat: pure-Python keccak-256 (validated against eth-hash)"
```

---

## Task 3: secp256k1 (`src/secp256k1.py`)

**Files:**
- Create: `src/secp256k1.py`
- Test: `tests/test_secp256k1.py`

- [ ] **Step 1: Write the failing test (oracle: eth_account)**

Create `tests/test_secp256k1.py`:

```python
import os

from eth_account import Account
from eth_account.messages import encode_defunct

from src.secp256k1 import sign, recover, privkey_to_pubkey, pubkey_to_address
from src.keccak import keccak256


def _eip191_hash(message: str) -> bytes:
    msg = message.encode()
    return keccak256(b"\x19Ethereum Signed Message:\n" + str(len(msg)).encode() + msg)


def test_address_matches_eth_account():
    priv = bytes.fromhex("4c0883a69102937d6231471b5dbb6204fe512961708279f1f3f6f0b4b3d7c2a1")
    acct = Account.from_key(priv)
    x, y = privkey_to_pubkey(priv)
    assert pubkey_to_address(x, y).lower() == acct.address.lower()


def test_sign_recover_roundtrip():
    priv = os.urandom(32)
    x, y = privkey_to_pubkey(priv)
    addr = pubkey_to_address(x, y)
    digest = keccak256(b"some message digest padding..")
    r, s, v = sign(digest, priv)
    rx, ry = recover(digest, r, s, v)
    assert pubkey_to_address(rx, ry).lower() == addr.lower()


def test_recover_matches_eth_account_signature():
    """A signature produced by eth_account (the server side) recovers correctly here."""
    acct = Account.create()
    message = "authorize-payload-json"
    signed = acct.sign_message(encode_defunct(text=message))
    r, s, v = signed.r, signed.s, signed.v
    digest = _eip191_hash(message)
    rx, ry = recover(digest, r, s, v)
    assert pubkey_to_address(rx, ry).lower() == acct.address.lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_secp256k1.py -q`
Expected: FAIL — no module `src.secp256k1`.

- [ ] **Step 3: Implement secp256k1.py**

Create `src/secp256k1.py`:

```python
"""Minimal secp256k1 ECDSA (sign + recover) for MicroPython.

Uses Python arbitrary-precision ints and modular pow for inverses.
"""

import os

from .keccak import keccak256

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


def _inv(a, m):
    return pow(a % m, m - 2, m)


def _add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if x1 == x2 and y1 == y2:
        m = (3 * x1 * x1) * _inv(2 * y1, P) % P
    else:
        m = (y2 - y1) * _inv((x2 - x1) % P, P) % P
    x3 = (m * m - x1 - x2) % P
    y3 = (m * (x1 - x3) - y1) % P
    return (x3, y3)


def _mul(k, point):
    result = None
    addend = point
    while k:
        if k & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        k >>= 1
    return result


def privkey_to_pubkey(priv):
    d = int.from_bytes(priv, "big")
    return _mul(d, (GX, GY))


def _hex(b):
    return "".join("{:02x}".format(x) for x in b)


def pubkey_to_address(x, y):
    pub = x.to_bytes(32, "big") + y.to_bytes(32, "big")
    return "0x" + _hex(keccak256(pub)[-20:])


def sign(msg_hash, priv):
    z = int.from_bytes(msg_hash, "big")
    d = int.from_bytes(priv, "big")
    while True:
        k = int.from_bytes(os.urandom(32), "big") % N
        if k == 0:
            continue
        rp = _mul(k, (GX, GY))
        r = rp[0] % N
        if r == 0:
            continue
        s = (_inv(k, N) * (z + r * d)) % N
        if s == 0:
            continue
        rec = (rp[1] & 1) | (2 if rp[0] >= N else 0)
        if s > N // 2:
            s = N - s
            rec ^= 1
        return (r, s, 27 + rec)


def recover(msg_hash, r, s, v):
    z = int.from_bytes(msg_hash, "big")
    rec = v - 27
    x = r + (N if (rec & 2) else 0)
    y2 = (pow(x, 3, P) + 7) % P
    y = pow(y2, (P + 1) // 4, P)
    if (y & 1) != (rec & 1):
        y = P - y
    rp = (x, y)
    r_inv = _inv(r, N)
    u1 = (-z * r_inv) % N
    u2 = (s * r_inv) % N
    return _add(_mul(u1, (GX, GY)), _mul(u2, rp))
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_secp256k1.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/secp256k1.py tests/test_secp256k1.py
git commit -m "feat: secp256k1 sign/recover validated against eth_account"
```

---

## Task 4: Real eth_wallet (`src/eth_wallet.py`)

**Files:**
- Rewrite: `src/eth_wallet.py`
- Replace test: `tests/test_eth_wallet.py`

- [ ] **Step 1: Write the failing test**

Replace `tests/test_eth_wallet.py` with:

```python
import json
from unittest.mock import patch

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from src.eth_wallet import EthWallet


@pytest.fixture
def temp_wallet_dir(tmp_path):
    with (
        patch("src.eth_wallet.WALLET_KEY_FILE", str(tmp_path / "device_key.json")),
        patch("src.eth_wallet.SERVER_WALLET_FILE", str(tmp_path / "server_wallet.txt")),
    ):
        yield tmp_path


def test_wallet_address_is_valid_and_persistent(temp_wallet_dir):
    w1 = EthWallet()
    assert w1.address.startswith("0x") and len(w1.address) == 42
    w2 = EthWallet()
    assert w1.address == w2.address  # loaded from file


def test_sign_challenge_envelope_recovers_to_device(temp_wallet_dir):
    w = EthWallet()
    env = w.sign_challenge()
    assert set(env.keys()) == {"data", "signing"}
    msg = env["signing"]["message"]
    sig = env["signing"]["signature"]
    # The app/server verify with eth_account; recovered signer == device address.
    recovered = Account.recover_message(encode_defunct(text=msg), signature=sig)
    assert recovered.lower() == w.address.lower()
    assert json.loads(msg) == env["data"]


def _server_execute_envelope(server_account, data: dict) -> dict:
    message = json.dumps(data)
    signed = server_account.sign_message(encode_defunct(text=message))
    return {
        "data": data,
        "signing": {
            "walletAddress": server_account.address,
            "message": message,
            "signature": signed.signature.hex()
            if signed.signature.hex().startswith("0x")
            else "0x" + signed.signature.hex(),
        },
    }


def test_verify_signed_payload_accepts_valid_server_sig(temp_wallet_dir):
    w = EthWallet()
    server = Account.create()
    env = _server_execute_envelope(server, {"orderId": "o1", "seconds": 5})
    assert w.verify_signed_payload(env) is True
    assert w.verify_signed_payload(env, expected_signer=server.address) is True


def test_verify_signed_payload_rejects_wrong_signer(temp_wallet_dir):
    w = EthWallet()
    server = Account.create()
    other = Account.create()
    env = _server_execute_envelope(server, {"orderId": "o1", "seconds": 5})
    assert w.verify_signed_payload(env, expected_signer=other.address) is False


def test_verify_signed_payload_rejects_tampered_data(temp_wallet_dir):
    w = EthWallet()
    server = Account.create()
    env = _server_execute_envelope(server, {"orderId": "o1", "seconds": 5})
    env["data"]["seconds"] = 9999  # message no longer matches data
    assert w.verify_signed_payload(env) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eth_wallet.py -q`
Expected: FAIL (old wallet API / behavior differs).

- [ ] **Step 3: Rewrite eth_wallet.py**

Replace `src/eth_wallet.py` with:

```python
"""Ethereum wallet for MicroPython using real keccak-256 + secp256k1."""

import json
import os
import time

from .config import WALLET_KEY_FILE, SERVER_WALLET_FILE
from .keccak import keccak256
from .secp256k1 import privkey_to_pubkey, pubkey_to_address, sign, recover


def _random_bytes(n):
    try:
        return os.urandom(n)
    except AttributeError:
        import random
        return bytes([random.getrandbits(8) for _ in range(n)])


def _hex(b):
    return "".join("{:02x}".format(x) for x in b)


def _eip191_hash(message):
    msg = message.encode()
    return keccak256(b"\x19Ethereum Signed Message:\n" + str(len(msg)).encode() + msg)


class EthWallet:
    def __init__(self):
        self._private_key = b""
        self._address = ""
        self._load_or_create()

    def _load_or_create(self):
        try:
            with open(WALLET_KEY_FILE, "r") as f:
                data = json.load(f)
                self._private_key = bytes.fromhex(data["private_key"])
                self._address = data["address"]
                print("[Wallet] Loaded:", self._address[:10])
                return
        except (OSError, KeyError, ValueError):
            pass

        self._private_key = _random_bytes(32)
        x, y = privkey_to_pubkey(self._private_key)
        self._address = pubkey_to_address(x, y)
        with open(WALLET_KEY_FILE, "w") as f:
            json.dump({"private_key": _hex(self._private_key), "address": self._address}, f)
        print("[Wallet] Generated:", self._address[:10])

    @property
    def address(self):
        return self._address

    @property
    def address_short(self):
        return self._address[2:10].lower()

    def _sign_message(self, message):
        r, s, v = sign(_eip191_hash(message), self._private_key)
        return "0x" + _hex(r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([v]))

    def sign_challenge(self):
        data = {
            "walletAddress": self._address,
            "firmwareVersion": "0.1.0-pico",
            "hasServerWallet": bool(EthWallet.load_server_wallet()),
            "timestamp": int(time.time()),
            "nonce": _hex(_random_bytes(16)),
        }
        message = json.dumps(data)
        signing = {
            "walletAddress": self._address,
            "message": message,
            "signature": self._sign_message(message),
        }
        return {"data": data, "signing": signing}

    def verify_signed_payload(self, envelope, expected_signer=None, max_age_s=30.0):
        data = envelope.get("data")
        signing = envelope.get("signing")
        if not data or not signing:
            return False
        try:
            message = signing["message"]
            decoded = json.loads(message)
            ts = decoded.pop("signing_timestamp", None)
            if ts is not None:
                age = abs(time.time() - float(ts))
                if age > max_age_s:
                    return False
            if json.dumps(decoded) != json.dumps(data):
                return False
            sig = signing["signature"]
            raw = bytes.fromhex(sig[2:] if sig.startswith("0x") else sig)
            if len(raw) != 65:
                return False
            r = int.from_bytes(raw[0:32], "big")
            s = int.from_bytes(raw[32:64], "big")
            v = raw[64]
            if v < 27:
                v += 27
            x, y = recover(_eip191_hash(message), r, s, v)
            signer = pubkey_to_address(x, y)
            if expected_signer and signer.lower() != expected_signer.lower():
                return False
            return True
        except (ValueError, KeyError, TypeError):
            return False

    @staticmethod
    def load_server_wallet():
        try:
            with open(SERVER_WALLET_FILE, "r") as f:
                return f.read().strip()
        except OSError:
            return ""

    @staticmethod
    def save_server_wallet(address):
        with open(SERVER_WALLET_FILE, "w") as f:
            f.write(address)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_eth_wallet.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/eth_wallet.py tests/test_eth_wallet.py
git commit -m "feat: real eth_wallet (EIP-191 sign + ecrecover verify), replace stub"
```

---

## Task 5: Multi-pin async RelayController (`src/gpio_control.py`)

**Files:**
- Rewrite: `src/gpio_control.py`
- Replace test: `tests/test_gpio_control.py`

- [ ] **Step 1: Write the failing test**

Replace `tests/test_gpio_control.py` with:

```python
import asyncio

import pytest

from src.gpio_control import RelayController


def test_starts_inactive():
    r = RelayController()
    assert not r.is_active
    assert not r.is_sequence_running


def test_activate_deactivate():
    r = RelayController()
    r.activate()
    assert r.is_active
    r.deactivate()
    assert not r.is_active


def test_run_sequence_drives_pins_in_order(monkeypatch):
    r = RelayController()
    calls = []
    monkeypatch.setattr(r, "_set_pin", lambda pin, high: calls.append((pin, high)))

    async def fake_sleep(_s):
        return None

    monkeypatch.setattr("src.gpio_control.asyncio.sleep", fake_sleep)

    async def drive():
        started = r.run_sequence([{"pinNumber": 23, "duration": 5}, {"pinNumber": 24, "duration": 30}])
        assert started is True
        await r._sequence_task

    asyncio.run(drive())

    assert [pin for pin, high in calls if high] == [23, 24]
    last = {}
    for pin, high in calls:
        last[pin] = high
    assert last == {23: False, 24: False}
    assert not r.is_sequence_running


def test_run_sequence_rejects_when_busy():
    r = RelayController()
    r._sequence_running = True
    assert r.run_sequence([{"pinNumber": 23, "duration": 1}]) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_gpio_control.py -q`
Expected: FAIL — no `run_sequence`/`is_sequence_running`/`_set_pin`.

- [ ] **Step 3: Rewrite gpio_control.py**

Replace `src/gpio_control.py` with:

```python
"""GPIO relay control for Pico W: single-pin timed + multi-pin async sequences."""

try:
    from machine import Pin, Timer
    MACHINE_AVAILABLE = True
except ImportError:
    MACHINE_AVAILABLE = False
    print("[GPIO] machine module not available - mock mode")

try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

from .config import DEFAULT_RELAY_PIN


class RelayController:
    def __init__(self, pin_num=DEFAULT_RELAY_PIN):
        self._pin_num = pin_num
        self._active = False
        self._timer = Timer() if MACHINE_AVAILABLE else None
        self._pins = {}
        self._sequence_running = False
        self._sequence_task = None
        self._ensure_pin(pin_num)
        print("[GPIO] Initialized pin", pin_num if MACHINE_AVAILABLE else "(mock)")

    @property
    def is_active(self):
        return self._active

    @property
    def is_sequence_running(self):
        return self._sequence_running

    def _ensure_pin(self, pin_num):
        if pin_num in self._pins:
            return
        if MACHINE_AVAILABLE:
            self._pins[pin_num] = Pin(pin_num, Pin.OUT, value=0)
        else:
            self._pins[pin_num] = None

    def _set_pin(self, pin_num, high):
        self._ensure_pin(pin_num)
        pin = self._pins.get(pin_num)
        if pin is not None:
            pin.value(1 if high else 0)

    def activate(self, duration_seconds=0):
        self._cancel_timer()
        self._set_pin(self._pin_num, True)
        self._active = True
        print("[GPIO] Relay ON")
        if duration_seconds > 0 and self._timer:
            self._timer.init(
                mode=Timer.ONE_SHOT,
                period=duration_seconds * 1000,
                callback=lambda t: self.deactivate(),
            )

    def deactivate(self, _timer=None):
        self._cancel_timer()
        self._set_pin(self._pin_num, False)
        self._active = False
        print("[GPIO] Relay OFF")

    def run_sequence(self, signals):
        if self._sequence_running:
            return False
        self._sequence_running = True
        self._sequence_task = asyncio.create_task(self._run_sequence(list(signals)))
        return True

    async def _run_sequence(self, signals):
        touched = []
        try:
            for sig in signals:
                pin_num = int(sig["pinNumber"])
                duration = float(sig["duration"])
                if pin_num not in touched:
                    touched.append(pin_num)
                self._set_pin(pin_num, True)
                await asyncio.sleep(duration)
                self._set_pin(pin_num, False)
        finally:
            for pin_num in touched:
                self._set_pin(pin_num, False)
            self._sequence_running = False
            print("[GPIO] Sequence complete")

    def _cancel_timer(self):
        if self._timer and MACHINE_AVAILABLE:
            try:
                self._timer.deinit()
                self._timer = Timer()
            except Exception:
                pass

    def cleanup(self):
        self.deactivate()
        for pin_num in self._pins:
            self._set_pin(pin_num, False)
        if self._timer and MACHINE_AVAILABLE:
            self._timer.deinit()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_gpio_control.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/gpio_control.py tests/test_gpio_control.py
git commit -m "feat: multi-pin RelayController with async run_sequence"
```

---

## Task 6: CommandHandler (`src/command_handler.py`)

**Files:**
- Create: `src/command_handler.py`
- Test: `tests/test_command_handler.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_command_handler.py`:

```python
import json
from unittest.mock import patch

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from src.command_handler import CommandHandler, validate_signals
from src.eth_wallet import EthWallet
from src.gpio_control import RelayController


@pytest.fixture
def temp_wallet_dir(tmp_path):
    with (
        patch("src.eth_wallet.WALLET_KEY_FILE", str(tmp_path / "device_key.json")),
        patch("src.eth_wallet.SERVER_WALLET_FILE", str(tmp_path / "server_wallet.txt")),
    ):
        yield tmp_path


@pytest.fixture
def handler(temp_wallet_dir):
    return CommandHandler(EthWallet(), RelayController())


def _execute(server, data):
    message = json.dumps(data)
    signed = server.sign_message(encode_defunct(text=message))
    sig = signed.signature.hex()
    return {
        "command": "EXECUTE",
        "data": data,
        "signing": {
            "walletAddress": server.address,
            "message": message,
            "signature": sig if sig.startswith("0x") else "0x" + sig,
        },
    }


def _setup(server):
    data = {"walletAddress": server.address}
    message = json.dumps(data)
    signed = server.sign_message(encode_defunct(text=message))
    sig = signed.signature.hex()
    return {
        "command": "SETUP_SERVER",
        "data": data,
        "signing": {
            "walletAddress": server.address,
            "message": message,
            "signature": sig if sig.startswith("0x") else "0x" + sig,
        },
    }


class TestValidateSignals:
    def test_valid(self):
        assert validate_signals([{"pinNumber": 23, "duration": 5}]) == [{"pinNumber": 23, "duration": 5}]

    def test_invalid(self):
        assert validate_signals([]) is None
        assert validate_signals([{"pinNumber": 99, "duration": 5}]) is None
        assert validate_signals([{"pinNumber": 5, "duration": 0}]) is None


class TestHandle:
    def test_setup_server_then_execute_timed(self, handler, monkeypatch):
        server = Account.create()
        assert handler.handle(_setup(server))["status"] == "OK"
        seen = {}
        monkeypatch.setattr(handler._relay, "activate", lambda duration_seconds=0: seen.setdefault("d", duration_seconds))
        resp = handler.handle(_execute(server, {"orderId": "o1", "offeringType": "TIMED", "seconds": 600,
                                                "nonce": "n", "exp": 9999999999}))
        assert resp["status"] == "OK"
        assert seen["d"] == 600

    def test_execute_fixed_runs_sequence(self, handler, monkeypatch):
        server = Account.create()
        handler.handle(_setup(server))
        called = {}
        monkeypatch.setattr(handler._relay, "run_sequence", lambda signals: called.setdefault("s", signals) or True)
        data = {"orderId": "o1", "offeringType": "FIXED", "seconds": 35,
                "signals": [{"pinNumber": 23, "duration": 5}, {"pinNumber": 24, "duration": 30}],
                "nonce": "n", "exp": 9999999999}
        assert handler.handle(_execute(server, data))["status"] == "OK"
        assert called["s"] == data["signals"]

    def test_execute_fixed_busy(self, handler, monkeypatch):
        server = Account.create()
        handler.handle(_setup(server))
        monkeypatch.setattr(handler._relay, "run_sequence", lambda signals: False)
        data = {"orderId": "o1", "offeringType": "FIXED", "seconds": 5,
                "signals": [{"pinNumber": 23, "duration": 5}], "nonce": "n", "exp": 9999999999}
        assert handler.handle(_execute(server, data))["status"] == "BUSY"

    def test_execute_no_server_wallet(self, handler):
        server = Account.create()
        resp = handler.handle(_execute(server, {"orderId": "o1", "offeringType": "TIMED", "seconds": 1,
                                                "nonce": "n", "exp": 9999999999}))
        assert resp["status"] == "ERROR"

    def test_execute_bad_signature(self, handler):
        server = Account.create()
        handler.handle(_setup(server))
        other = Account.create()
        resp = handler.handle(_execute(other, {"orderId": "o1", "offeringType": "TIMED", "seconds": 1,
                                               "nonce": "n", "exp": 9999999999}))
        assert resp["status"] == "UNAUTHORIZED"

    def test_unknown_command(self, handler):
        assert handler.handle({"command": "BOGUS"})["status"] == "ERROR"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_command_handler.py -q`
Expected: FAIL — no module `src.command_handler`.

- [ ] **Step 3: Implement command_handler.py**

Create `src/command_handler.py`:

```python
"""Transport-agnostic command handling for the Pico BLE peripheral."""

from .eth_wallet import EthWallet

MAX_SIGNAL_SECONDS = 3600
MIN_BCM_PIN = 0
MAX_BCM_PIN = 27


def validate_signals(signals):
    if not isinstance(signals, list) or not signals:
        return None
    result = []
    for sig in signals:
        if not isinstance(sig, dict):
            return None
        pin = sig.get("pinNumber")
        duration = sig.get("duration")
        if not isinstance(pin, int) or isinstance(pin, bool):
            return None
        if pin < MIN_BCM_PIN or pin > MAX_BCM_PIN:
            return None
        if not isinstance(duration, (int, float)) or isinstance(duration, bool):
            return None
        if duration <= 0 or duration > MAX_SIGNAL_SECONDS:
            return None
        result.append({"pinNumber": pin, "duration": duration})
    return result


class CommandHandler:
    def __init__(self, wallet, relay):
        self._wallet = wallet
        self._relay = relay
        self._server_wallet = EthWallet.load_server_wallet()

    def handle(self, msg):
        command = str(msg.get("command", "")).upper()
        print("[CMD]", command)
        if command == "SETUP_SERVER":
            return self._setup_server(msg)
        if command == "EXECUTE":
            return self._execute(msg)
        return {"status": "ERROR", "message": "Unknown command: " + command}

    def _setup_server(self, msg):
        if not self._wallet.verify_signed_payload(msg):
            return {"status": "UNAUTHORIZED", "message": "Invalid server signature"}
        address = msg.get("signing", {}).get("walletAddress", "")
        if not address or not address.startswith("0x"):
            return {"status": "ERROR", "message": "Invalid server wallet address"}
        EthWallet.save_server_wallet(address)
        self._server_wallet = address
        return {"status": "OK", "message": "Server wallet configured"}

    def _execute(self, msg):
        if not self._server_wallet:
            return {"status": "ERROR", "message": "No server wallet configured"}
        if not self._wallet.verify_signed_payload(msg, expected_signer=self._server_wallet):
            return {"status": "UNAUTHORIZED", "message": "Invalid server signature"}

        data = msg.get("data", {})
        seconds = data.get("seconds", 0)
        offering_type = data.get("offeringType", "TRIGGER")

        if offering_type == "FIXED" and data.get("signals"):
            signals = validate_signals(data.get("signals"))
            if signals is None:
                return {"status": "ERROR", "message": "Invalid signals"}
            if not self._relay.run_sequence(signals):
                return {"status": "BUSY", "message": "Device is busy"}
            total = int(sum(s["duration"] for s in signals))
            return {"status": "OK", "message": "Sequence started ({}s)".format(total)}

        if offering_type == "TRIGGER":
            self._relay.activate(duration_seconds=1)
            return {"status": "OK", "message": "Activated for 1s"}

        self._relay.activate(duration_seconds=seconds)
        return {"status": "OK", "message": "Activated for {}s".format(seconds)}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_command_handler.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add src/command_handler.py tests/test_command_handler.py
git commit -m "feat: CommandHandler with envelope verify, sequences, signals validation"
```

---

## Task 7: Wire peripheral + main; replace stale peripheral tests

**Files:**
- Modify: `src/ble_peripheral.py`
- Modify: `src/main.py`
- Replace test: `tests/test_ble_peripheral.py`

- [ ] **Step 1: Rewrite ble_peripheral.py**

Replace `src/ble_peripheral.py` with:

```python
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
from .command_handler import CommandHandler
from .gpio_control import RelayController


def _uuid(s):
    if AIOBLE_AVAILABLE:
        return bluetooth.UUID(s)
    return s


class TapayokaPicoBle:
    def __init__(self, wallet, relay):
        self._wallet = wallet
        self._relay = relay
        self._handler = CommandHandler(wallet, relay)

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

                device_info_char.write(json.dumps(self._wallet.sign_challenge()).encode())

                while connection.is_connected():
                    try:
                        _, data = await asyncio.wait_for(command_char.written(), timeout=30)
                        response = self._handle_command(data)
                        response_char.write(json.dumps(response).encode())
                        response_char.notify(connection)
                    except asyncio.TimeoutError:
                        pass

                print("[BLE] Disconnected")
                if self._relay.is_active and not self._relay.is_sequence_running:
                    self._relay.deactivate()
            except Exception as e:
                print("[BLE] Error:", e)
                await asyncio.sleep(1)

    def _handle_command(self, data):
        try:
            return self._handler.handle(json.loads(data.decode()))
        except (ValueError, KeyError) as e:
            return {"status": "ERROR", "message": str(e)}
```

- [ ] **Step 2: main.py — no functional change needed, confirm construction**

`src/main.py` already constructs `TapayokaPicoBle(wallet, relay)`, which now builds the handler internally. No edit required. Confirm by reading it; leave as-is.

- [ ] **Step 3: Replace tests/test_ble_peripheral.py**

Replace `tests/test_ble_peripheral.py` with:

```python
"""Tests for Pico BLE peripheral command dispatch (mock mode)."""

import json
from unittest.mock import patch

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from src.eth_wallet import EthWallet
from src.gpio_control import RelayController


@pytest.fixture
def temp_wallet_dir(tmp_path):
    with (
        patch("src.eth_wallet.WALLET_KEY_FILE", str(tmp_path / "device_key.json")),
        patch("src.eth_wallet.SERVER_WALLET_FILE", str(tmp_path / "server_wallet.txt")),
    ):
        yield tmp_path


@pytest.fixture
def ble(temp_wallet_dir):
    from src.ble_peripheral import TapayokaPicoBle
    return TapayokaPicoBle(EthWallet(), RelayController())


def test_invalid_json(ble):
    assert ble._handle_command(b"not json")["status"] == "ERROR"


def test_unknown_command(ble):
    assert ble._handle_command(json.dumps({"command": "BOGUS"}).encode())["status"] == "ERROR"


def test_execute_without_server_wallet(ble):
    server = Account.create()
    data = {"orderId": "o1", "offeringType": "TIMED", "seconds": 1, "nonce": "n", "exp": 9999999999}
    message = json.dumps(data)
    signed = server.sign_message(encode_defunct(text=message))
    sig = signed.signature.hex()
    env = {
        "command": "EXECUTE",
        "data": data,
        "signing": {"walletAddress": server.address, "message": message,
                    "signature": sig if sig.startswith("0x") else "0x" + sig},
    }
    assert ble._handle_command(json.dumps(env).encode())["status"] == "ERROR"


def test_device_info_envelope_recovers_to_device(ble):
    env = ble._wallet.sign_challenge()
    recovered = Account.recover_message(
        encode_defunct(text=env["signing"]["message"]),
        signature=env["signing"]["signature"],
    )
    assert recovered.lower() == ble._wallet.address.lower()
```

- [ ] **Step 4: Run the full pico suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS — all tests across keccak, secp256k1, eth_wallet, gpio_control, command_handler, ble_peripheral.

- [ ] **Step 5: Commit**

```bash
git add src/ble_peripheral.py tests/test_ble_peripheral.py
git commit -m "refactor: peripheral uses CommandHandler + signed envelope; sequences survive disconnect"
```

---

## Task 8: Update README, merge to main, deploy

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Correct README architecture note**

In `README.md`, replace the `- **Crypto**: Lightweight secp256k1 + keccak256 (no eth-account, runs on constrained hardware)` line with:

```markdown
- **Crypto**: Pure-Python keccak-256 + secp256k1 (sign + ecrecover), EIP-191; no eth-account on device
- **Protocol**: `EXECUTE`/`{data,signing}` envelope with `offeringType`; signal sequences for FIXED tiers (parity with `tapayoka_pi`)
```

- [ ] **Step 2: Full suite once more**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all green.

- [ ] **Step 3: Commit README + merge to main**

```bash
git add README.md
git commit -m "docs: update README for real crypto + EXECUTE protocol"
git checkout main && git merge --no-ff feature/full-parity-signal-sequences -m "Merge: MicroPython full-parity port with real crypto + signal sequences"
.venv/bin/python -m pytest tests/ -q
git branch -d feature/full-parity-signal-sequences
```
Expected: merge clean, all tests green.

- [ ] **Step 4: Deploy (git push — push_all skips pico)**

```bash
git push origin main
```
Expected: pushed to `github.com:johnqh/tapayoka_pi_pico.git`. No `tapayoka_types`/`tapayoka_api` changes are needed (pico consumes the existing protocol), so `push_all.sh` is not required.

---

## Self-Review

**Spec coverage:**
- keccak-256 pure-Python → Task 2. ✔
- secp256k1 sign/recover/address → Task 3. ✔
- eth_wallet real address + EIP-191 sign_challenge + verify_signed_payload → Task 4. ✔
- Multi-pin async run_sequence + is_sequence_running → Task 5. ✔
- CommandHandler EXECUTE/SETUP_SERVER + validate_signals + dispatch table (FIXED→sequence, FIXED-no-signals→activate, TIMED→activate, TRIGGER→1s; no-wallet/bad-sig/busy/invalid errors) → Task 6. ✔
- {data,signing} device-info + delegate + run-to-completion on disconnect → Task 7. ✔
- Drop ON/OFF/STATUS/AUTHORIZE; replace stale tests → Tasks 4,5,7. ✔
- Oracle tests via eth_account/eth-hash; requirements-dev.txt + CI → Tasks 1–4,6,7. ✔
- BLE-only (no WS); deploy via git push → Task 8. ✔

**Placeholder scan:** No `TODO`/`TBD`/no-op placeholders; every code step is complete and self-contained.

**Type/name consistency:** `keccak256`, `privkey_to_pubkey`/`pubkey_to_address`/`sign`/`recover`, `EthWallet.sign_challenge`/`verify_signed_payload`/`save_server_wallet`/`load_server_wallet`, `RelayController.run_sequence`/`is_sequence_running`/`_set_pin`/`_sequence_task`, `CommandHandler.handle`/`validate_signals` are consistent across tasks. Signature format (0x + r32‖s32‖v) consistent between `eth_wallet._sign_message`, `verify_signed_payload`, and tests. `validate_signals` bounds (pin 0–27, 0<dur≤3600) match the spec and pi.
