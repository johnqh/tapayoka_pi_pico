# Pico WS + Kiosk Dev Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CPython `TRANSPORT=ws` WebSocket transport plus a browser kiosk to `tapayoka_pi_pico` so the firmware logic can be run and driven on a Mac without Pico W / BLE hardware.

**Architecture:** A new dev-only WebSocket peripheral (`TapayokaPicoWs`) reuses the existing pure-Python `EthWallet`, `CommandHandler`, and `RelayController` (its mock mode when `machine` is absent). A ported stdlib kiosk (`kiosk_server` + `kiosk_state`) renders QR → Connected → Running views. Everything CPython-only is gated behind a `TRANSPORT=ws` branch in `main.py` that is unreachable on the Pico (MicroPython has no `os.getenv`).

**Tech Stack:** Python 3.10+ (dev), `websockets`, `qrcode[pil]`, stdlib `http.server`, `eth_account` (tests), `pytest`.

## Global Constraints

- New CPython-only modules (`ws_peripheral.py`, `kiosk_server.py`, `kiosk_state.py`) MUST NOT be imported except inside the `TRANSPORT=ws` branch — they cannot import on a Pico.
- `config.py` MUST stay MicroPython-safe: use `getattr(os, "getenv", lambda k, d=None: d)`; on-device defaults remain `"/wallet_key.json"` and `"/server_wallet.txt"`.
- Do NOT modify on-device BLE behavior (`ble_peripheral.py`) or the shared firmware `command_handler.py` / crypto.
- The ws `command` message nests the full command envelope under `data`: `{"type":"command","data":{"command":..,"data":{..},"signing":{..}}}`. The `RUNNING` derivation reads the inner `data["data"]`.
- Firmware version string in device info is `"0.1.0-pico"`.
- Default ports: WebSocket `8765`, kiosk HTTP `8026`. Dev state dir: `./dev_state/`.
- Test style follows `tests/test_command_handler.py`: `eth_account` signing via `_signed(server, command, data)`, wallet paths patched onto `src.eth_wallet.WALLET_KEY_FILE` / `SERVER_WALLET_FILE`.

---

### Task 1: Dev dependencies + env-aware config

**Files:**
- Modify: `requirements-dev.txt`
- Modify: `src/config.py`
- Test: `tests/test_config.py` (create)

**Interfaces:**
- Produces: `src.config.WALLET_KEY_FILE`, `src.config.SERVER_WALLET_FILE` (module-level strings, overridable via env vars of the same name).

- [ ] **Step 1: Add dev dependencies**

Replace the contents of `requirements-dev.txt` with:

```
pytest
eth-account
websockets
qrcode[pil]
../tapayoka_pi_core
```

- [ ] **Step 2: Install dev dependencies**

Run: `pip install -r requirements-dev.txt`
Expected: installs `websockets` and `qrcode` (plus Pillow) with no errors.

- [ ] **Step 3: Write the failing test**

Create `tests/test_config.py`:

```python
"""Tests for env-aware configuration."""

import importlib


def test_wallet_paths_default():
    import src.config as config
    importlib.reload(config)
    assert config.WALLET_KEY_FILE == "/wallet_key.json"
    assert config.SERVER_WALLET_FILE == "/server_wallet.txt"


def test_wallet_paths_read_env(monkeypatch):
    monkeypatch.setenv("WALLET_KEY_FILE", "/tmp/custom_key.json")
    monkeypatch.setenv("SERVER_WALLET_FILE", "/tmp/custom_server.txt")
    import src.config as config
    importlib.reload(config)
    assert config.WALLET_KEY_FILE == "/tmp/custom_key.json"
    assert config.SERVER_WALLET_FILE == "/tmp/custom_server.txt"
    monkeypatch.delenv("WALLET_KEY_FILE")
    monkeypatch.delenv("SERVER_WALLET_FILE")
    importlib.reload(config)  # restore defaults for other tests
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL on `test_wallet_paths_read_env` (current `config.py` hardcodes the paths, ignoring env).

- [ ] **Step 5: Make config.py env-aware**

Replace the contents of `src/config.py` with:

```python
"""Configuration for Tapayoka Pico."""

import os

# os.getenv is absent in MicroPython; the getattr default keeps on-device
# behavior identical (the "/"-rooted constants below). In CPython dev mode
# (TRANSPORT=ws) the wallet paths can be redirected via env so storage stays
# off the filesystem root.
_getenv = getattr(os, "getenv", lambda k, d=None: d)

BLE_SERVICE_UUID = "000088F4-0000-1000-8000-00805f9b34fb"
BLE_CHAR_DEVICE_INFO_UUID = "00000E32-0000-1000-8000-00805f9b34fb"
BLE_CHAR_COMMAND_UUID = "00000E33-0000-1000-8000-00805f9b34fb"
BLE_CHAR_RESPONSE_UUID = "00000E34-0000-1000-8000-00805f9b34fb"
BLE_DEVICE_NAME_PREFIX = "tapayoka-"

DEFAULT_RELAY_PIN = 15

WALLET_KEY_FILE = _getenv("WALLET_KEY_FILE", "/wallet_key.json")
SERVER_WALLET_FILE = _getenv("SERVER_WALLET_FILE", "/server_wallet.txt")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (both tests).

- [ ] **Step 7: Run the full suite to confirm no regressions**

Run: `pytest tests/ -v`
Expected: all existing tests PASS (config change is backward compatible).

- [ ] **Step 8: Commit**

```bash
git add requirements-dev.txt src/config.py tests/test_config.py
git commit -m "feat: make config wallet paths env-aware (MicroPython-safe)"
```

---

### Task 2: Port kiosk state + deep-link helpers

**Files:**
- Create: `src/kiosk_state.py`
- Test: `tests/test_kiosk.py` (create)

**Interfaces:**
- Produces:
  - `update_kiosk_state(state_file, *, status, qr_url=None, message=None, duration_seconds=None, started_at=None, pin=None) -> None` — writes `state.json`.
  - `generate_deep_link(transport, wallet_address, device_name, ws_port=8765, state_dir=None) -> str` — returns `tapayokav://connect?...`; writes `qr.png` into `state_dir` when given.

- [ ] **Step 1: Write the failing test**

Create `tests/test_kiosk.py`:

```python
"""Tests for the dev kiosk state + deep link helpers."""

import json

from src.kiosk_state import generate_deep_link, update_kiosk_state


def test_update_kiosk_state_running(tmp_path):
    state_file = str(tmp_path / "state.json")
    update_kiosk_state(state_file, status="RUNNING", pin=15,
                       duration_seconds=30, started_at=1000)
    with open(state_file) as f:
        state = json.load(f)
    assert state["status"] == "RUNNING"
    assert state["pin"] == 15
    assert state["duration_seconds"] == 30
    assert state["started_at"] == 1000
    assert "timestamp" in state


def test_update_kiosk_state_qr(tmp_path):
    state_file = str(tmp_path / "state.json")
    update_kiosk_state(state_file, status="QR", qr_url="tapayokav://x",
                       message="Scan to connect")
    with open(state_file) as f:
        state = json.load(f)
    assert state["status"] == "QR"
    assert state["qr_url"] == "tapayokav://x"


def test_generate_deep_link_ws_writes_qr(tmp_path):
    url = generate_deep_link(
        transport="ws",
        wallet_address="0xabc",
        device_name="tapayoka-abc",
        state_dir=str(tmp_path),
    )
    assert url.startswith("tapayokav://connect?")
    assert "wsUrl=ws" in url
    assert (tmp_path / "qr.png").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_kiosk.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.kiosk_state'`.

- [ ] **Step 3: Create the kiosk_state module**

Create `src/kiosk_state.py` (CPython dev-only; ported from `tapayoka_pi`):

```python
"""Kiosk state management - writes JSON for the kiosk HTTP page.

CPython dev-only (TRANSPORT=ws); never imported on the Pico.
"""

from __future__ import annotations

import json
import os
import socket
import time
from urllib.parse import urlencode

import qrcode


def _write_json_atomic(path: str, data: dict[str, object]) -> None:
    """Write JSON to a file atomically and ensure world-readable permissions."""
    try:
        target_dir = os.path.dirname(path)
        if target_dir and not os.path.exists(target_dir):
            os.makedirs(target_dir, exist_ok=True)

        temp_file = path + ".tmp"
        with open(temp_file, "w") as f:
            json.dump(data, f)
        os.replace(temp_file, path)
        try:
            os.chmod(path, 0o666)
        except OSError:
            pass
    except PermissionError as e:
        print(f"[Kiosk] Permission denied writing to {path}: {e}")
    except Exception as e:
        print(f"[Kiosk] Error writing {path}: {e}")


def update_kiosk_state(
    state_file: str,
    *,
    status: str,
    qr_url: str | None = None,
    message: str | None = None,
    duration_seconds: int | None = None,
    started_at: int | None = None,
    pin: int | None = None,
) -> None:
    """Write kiosk state so the HTML page can render the correct view."""
    payload: dict[str, object] = {
        "status": status,
        "timestamp": int(time.time() * 1000),
    }
    if qr_url:
        payload["qr_url"] = qr_url
    if message:
        payload["message"] = message
    if duration_seconds is not None:
        payload["duration_seconds"] = duration_seconds
    if started_at is not None:
        payload["started_at"] = started_at
    if pin is not None:
        payload["pin"] = pin

    _write_json_atomic(state_file, payload)
    print(f"[Kiosk] State updated: {status}")


def _get_local_ip() -> str:
    """Get the machine's local network IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return str(ip)
    except Exception:
        return "127.0.0.1"


def generate_deep_link(
    transport: str,
    wallet_address: str,
    device_name: str,
    ws_port: int = 8765,
    state_dir: str | None = None,
) -> str:
    """Generate a tapayokav:// deep link and save a QR code PNG to state_dir."""
    params: dict[str, str] = {
        "transport": transport,
        "wallet": wallet_address,
        "name": device_name,
    }
    if transport == "ws":
        local_ip = _get_local_ip()
        params["wsUrl"] = f"ws://{local_ip}:{ws_port}"

    url = f"tapayokav://connect?{urlencode(params)}"

    if state_dir:
        os.makedirs(state_dir, exist_ok=True)
        qr = qrcode.QRCode(box_size=10, border=4)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        qr_path = os.path.join(state_dir, "qr.png")
        img.save(qr_path)
        print(f"[Kiosk] QR code PNG saved to {qr_path}")

    return url
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_kiosk.py -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add src/kiosk_state.py tests/test_kiosk.py
git commit -m "feat: add dev kiosk state + deep-link helpers"
```

---

### Task 3: Port kiosk HTTP server

**Files:**
- Create: `src/kiosk_server.py`
- Test: `tests/test_kiosk_server.py` (create)

**Interfaces:**
- Consumes: `update_kiosk_state` (Task 2) writes the `state.json` this server serves.
- Produces: `start_kiosk_server(state_dir, port=8026) -> HTTPServer` — starts a daemon-thread HTTP server; serves `/` (HTML), `/state.json`, `/qr.png`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_kiosk_server.py`:

```python
"""Smoke test for the dev kiosk HTTP server."""

import json
import urllib.request

from src.kiosk_server import start_kiosk_server
from src.kiosk_state import update_kiosk_state


def _get(server, path):
    host, port = server.server_address
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def test_serves_html_and_state(tmp_path):
    update_kiosk_state(str(tmp_path / "state.json"), status="CONNECTED", message="Connected")
    server = start_kiosk_server(str(tmp_path), port=0)
    try:
        status, body = _get(server, "/")
        assert status == 200
        assert "<title>Tapayoka</title>" in body

        status, body = _get(server, "/state.json")
        assert status == 200
        assert json.loads(body)["status"] == "CONNECTED"
    finally:
        server.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_kiosk_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.kiosk_server'`.

- [ ] **Step 3: Create the kiosk_server module**

Create `src/kiosk_server.py` (ported from `tapayoka_pi`, with the `/qrcode.min.js` static route and `STATIC_DIR` removed — the pico has no `static/` dir and the page renders the server-generated `qr.png`):

```python
"""Simple HTTP server for the kiosk display page.

CPython dev-only (TRANSPORT=ws); never imported on the Pico.
"""

from __future__ import annotations

import json
import os
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler

KIOSK_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Tapayoka</title>
  <style>
    *, *:before, *:after { padding: 0; margin: 0; box-sizing: border-box; }
    @media (pointer: coarse), (pointer: none) { html, body { cursor: none; } }
    html, body { height: 100%; }
    body {
      background-color: #080710;
      font-family: 'Helvetica Neue', Arial, sans-serif;
      color: #ffffff;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      text-align: center;
      padding: 16px;
      overflow: hidden;
    }
    .hidden { display: none !important; }

    #qr-view { display: flex; flex-direction: column; align-items: center; }
    #qr-img {
      width: min(300px, 64vh, 82vw);
      height: min(300px, 64vh, 82vw);
      display: block;
    }
    #qr-caption {
      font-size: clamp(15px, 4.5vw, 24px);
      font-weight: 400;
      margin-top: clamp(10px, 3vh, 28px);
      opacity: 0.9;
    }

    #connected-view { display: flex; flex-direction: column; align-items: center; }
    #connected-text {
      font-size: clamp(30px, 9vw, 52px);
      font-weight: 300;
      letter-spacing: 0.5px;
    }

    #job-status {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: clamp(10px, 2.5vw, 16px);
      margin-top: clamp(12px, 3.5vh, 28px);
      font-size: clamp(16px, 5vw, 26px);
      font-weight: 300;
    }
    .led {
      width: clamp(11px, 3vw, 16px);
      height: clamp(11px, 3vw, 16px);
      flex: none;
      border-radius: 50%;
      background: #2ecc71;
      box-shadow: 0 0 10px 2px rgba(46, 204, 113, 0.7);
      animation: pulse 1.6s ease-in-out infinite;
    }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
    #job-timer { font-variant-numeric: tabular-nums; min-width: 3.5ch; }
  </style>
</head>
<body>
  <div id="qr-view" class="hidden">
    <img id="qr-img" alt="QR code">
    <p id="qr-caption">Scan to continue</p>
  </div>
  <div id="connected-view" class="hidden">
    <div id="connected-text">Connected</div>
    <div id="job-status" class="hidden">
      <span class="led"></span>
      <span id="job-pin"></span>
      <span id="job-timer">00:00</span>
    </div>
  </div>
  <script>
    let lastTimestamp = -1;
    let countdownInterval = null;

    function fmt(sec) {
      sec = Math.max(0, sec);
      const m = Math.floor(sec / 60), s = sec % 60;
      return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    }
    function show(el, on) { el.classList.toggle('hidden', !on); }
    function stopCountdown() {
      if (countdownInterval) { clearInterval(countdownInterval); countdownInterval = null; }
    }

    function render(data) {
      const qrView = document.getElementById('qr-view');
      const connView = document.getElementById('connected-view');
      const jobStatus = document.getElementById('job-status');

      if (data.status === 'RUNNING') {
        show(qrView, false);
        show(connView, true);
        show(jobStatus, true);
        document.getElementById('job-pin').textContent =
          (data.pin === undefined || data.pin === null) ? '' : ('PIN ' + data.pin);
        stopCountdown();
        const start = data.started_at, duration = data.duration_seconds;
        const tick = () => {
          const now = Math.floor(Date.now() / 1000);
          const remaining = Math.max(0, duration - (now - start));
          document.getElementById('job-timer').textContent = fmt(remaining);
          if (remaining <= 0) stopCountdown();
        };
        tick();
        countdownInterval = setInterval(tick, 1000);

      } else if (data.status === 'CONNECTED') {
        stopCountdown();
        show(qrView, false);
        show(connView, true);
        show(jobStatus, false);

      } else if (data.status === 'QR' && data.qr_url) {
        stopCountdown();
        show(connView, false);
        show(jobStatus, false);
        document.getElementById('qr-img').src = '/qr.png?t=' + data.timestamp;
        show(qrView, true);
      }
    }

    function poll() {
      fetch('/state.json')
        .then(r => r.json())
        .then(data => {
          if (data.timestamp <= lastTimestamp) return;
          lastTimestamp = data.timestamp;
          render(data);
        })
        .catch(() => {});
    }
    setInterval(poll, 1000);
    poll();
  </script>
</body>
</html>
"""


class KioskHandler(SimpleHTTPRequestHandler):
    """Serves the kiosk HTML page and state.json from a directory."""

    def __init__(self, *args, state_dir: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self._state_dir = state_dir
        super().__init__(*args, directory=state_dir, **kwargs)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/" or path == "/index.html":
            self._serve_string(KIOSK_HTML, "text/html")
        elif path == "/state.json":
            state_file = os.path.join(self._state_dir, "state.json")
            if os.path.exists(state_file):
                with open(state_file) as f:
                    content = f.read()
                self._serve_string(content, "application/json")
            else:
                idle = json.dumps({"status": "IDLE", "timestamp": 0})
                self._serve_string(idle, "application/json")
        elif path == "/qr.png":
            qr_path = os.path.join(self._state_dir, "qr.png")
            if os.path.exists(qr_path):
                self._serve_binary(qr_path, "image/png")
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def _serve_string(self, content: str, content_type: str) -> None:
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _serve_binary(self, path: str, content_type: str) -> None:
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        pass


def start_kiosk_server(state_dir: str, port: int = 8026) -> HTTPServer:
    """Start the kiosk HTTP server in a background thread. Returns the server."""
    os.makedirs(state_dir, exist_ok=True)

    handler = partial(KioskHandler, state_dir=state_dir)
    server = HTTPServer(("0.0.0.0", port), handler)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[Kiosk] HTTP server started on http://0.0.0.0:{server.server_address[1]}")
    return server
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_kiosk_server.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/kiosk_server.py tests/test_kiosk_server.py
git commit -m "feat: add dev kiosk HTTP server"
```

---

### Task 4: WebSocket peripheral

**Files:**
- Create: `src/ws_peripheral.py`
- Test: `tests/test_ws_peripheral.py` (create)

**Interfaces:**
- Consumes: `CommandHandler(wallet, relay)` and its `.handle(msg)`; `EthWallet` (`address`, `address_short`, `sign_response`, `load_server_wallet`); `RelayController` (`is_active`, `is_sequence_running`, `deactivate`); `_hex` / `_random_bytes` from `src.eth_wallet`; `build_device_info_data` from `tapayoka_pi_core`; `update_kiosk_state` / `generate_deep_link` (Task 2); `BLE_DEVICE_NAME_PREFIX` / `DEFAULT_RELAY_PIN` (Task 1 config).
- Produces: `class TapayokaPicoWs(wallet, relay, kiosk_state_dir)` with `device_name` (property), `_build_device_info()`, `_handle_connection(ws)` (coroutine), `_state_file()`, `start(host="0.0.0.0", port=8765)`, `stop()`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ws_peripheral.py`:

```python
"""Tests for the Pico WebSocket dev transport (mock mode, no BLE/GPIO)."""

import asyncio
import json
from unittest.mock import patch

import pytest
import websockets
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
def peripheral(temp_wallet_dir):
    from src.ws_peripheral import TapayokaPicoWs
    return TapayokaPicoWs(EthWallet(), RelayController(), str(temp_wallet_dir))


def _signed(server, command, data):
    message = json.dumps(data)
    signed = server.sign_message(encode_defunct(text=message))
    sig = signed.signature.hex()
    return {
        "command": command,
        "data": data,
        "signing": {
            "walletAddress": server.address,
            "message": message,
            "signature": sig if sig.startswith("0x") else "0x" + sig,
        },
    }


async def _run_client(peripheral, scenario):
    async with websockets.serve(peripheral._handle_connection, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with websockets.connect("ws://127.0.0.1:%d" % port) as ws:
            return await scenario(ws)


def test_announce_on_connect(peripheral):
    async def scenario(ws):
        return json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
    msg = asyncio.run(_run_client(peripheral, scenario))
    assert msg["type"] == "announce"
    assert msg["data"]["walletAddress"] == peripheral._wallet.address
    assert msg["data"]["deviceName"] == peripheral.device_name


def test_device_info_recovers_to_device(peripheral):
    async def scenario(ws):
        await ws.recv()  # announce
        await ws.send(json.dumps({"type": "read_device_info"}))
        return json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
    msg = asyncio.run(_run_client(peripheral, scenario))
    assert msg["type"] == "device_info"
    signing = msg["data"]["signing"]
    recovered = Account.recover_message(
        encode_defunct(text=signing["message"]), signature=signing["signature"]
    )
    assert recovered.lower() == peripheral._wallet.address.lower()
    decoded = json.loads(signing["message"])
    decoded.pop("signing_timestamp")
    assert decoded == msg["data"]["data"]


def test_unknown_type_returns_error(peripheral):
    async def scenario(ws):
        await ws.recv()  # announce
        await ws.send(json.dumps({"type": "bogus"}))
        return json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
    msg = asyncio.run(_run_client(peripheral, scenario))
    assert msg["type"] == "response"
    assert msg["data"]["status"] == "ERROR"


def test_setup_then_execute_emits_running(peripheral, monkeypatch):
    monkeypatch.setattr(peripheral._relay, "activate", lambda duration_seconds=0: None)
    server = Account.create()

    async def scenario(ws):
        await ws.recv()  # announce
        await ws.send(json.dumps({"type": "command",
                                  "data": _signed(server, "SETUP_SERVER",
                                                  {"walletAddress": server.address})}))
        setup = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        exec_data = {"orderId": "o1", "offeringType": "TIMED", "seconds": 5,
                     "nonce": "n", "exp": 9999999999}
        await ws.send(json.dumps({"type": "command",
                                  "data": _signed(server, "EXECUTE", exec_data)}))
        execute = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        return setup, execute

    setup, execute = asyncio.run(_run_client(peripheral, scenario))
    assert setup["data"]["status"] == "OK"
    assert execute["data"]["status"] == "OK"
    with open(peripheral._state_file()) as f:
        state = json.load(f)
    assert state["status"] == "RUNNING"
    assert state["duration_seconds"] == 5
    assert state["pin"] == 15
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ws_peripheral.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ws_peripheral'`.

- [ ] **Step 3: Create the ws_peripheral module**

Create `src/ws_peripheral.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ws_peripheral.py -v`
Expected: PASS (all four tests).

- [ ] **Step 5: Commit**

```bash
git add src/ws_peripheral.py tests/test_ws_peripheral.py
git commit -m "feat: add WebSocket dev transport for the Pico"
```

---

### Task 5: Wire TRANSPORT switch into main.py + docs

**Files:**
- Modify: `src/main.py`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: everything from Tasks 1–4 (`start_kiosk_server`, `generate_deep_link`, `update_kiosk_state`, `TapayokaPicoWs`, env-aware `config`).

- [ ] **Step 1: Replace main.py with the TRANSPORT switch**

Replace the contents of `src/main.py` with:

```python
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
```

- [ ] **Step 2: Ignore the dev state dir**

Append to `.gitignore`:

```
# WS dev harness state (wallet + kiosk)
dev_state/
```

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ -v`
Expected: all tests PASS (existing + the new config/kiosk/ws tests).

- [ ] **Step 4: Manually run and drive the harness**

Run (from the repo root, dev venv active):

```bash
TRANSPORT=ws python -m src.main
```

Expected stdout includes:
- `Tapayoka Pico W - WS`
- `[Kiosk] HTTP server started on http://0.0.0.0:8026`
- `[Kiosk] QR code PNG saved to ./dev_state/qr.png`
- `[WS] Starting WebSocket peripheral on ws://0.0.0.0:8765`
- `[WS] Peripheral published: tapayoka-<prefix>`

In a second terminal, verify the kiosk and ws are live and driveable:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8026/        # 200
python - <<'PY'
import asyncio, json, websockets
async def main():
    async with websockets.connect("ws://127.0.0.1:8765") as ws:
        print("ANNOUNCE:", await ws.recv())
        await ws.send(json.dumps({"type": "read_device_info"}))
        print("DEVICE_INFO:", await ws.recv())
asyncio.run(main())
PY
```

Expected: HTTP `200`; an `announce` message with `deviceName`/`walletAddress`; a `device_info` message with a `{data, signing}` envelope. Then stop the server (Ctrl-C).

- [ ] **Step 5: Document the dev mode in README.md**

Add this section to `README.md` after the existing "## Development" section:

```markdown
## Local dev (WebSocket + kiosk)

Run the firmware logic on a Mac without a Pico W or BLE hardware. This mode
is CPython-only and never touches the on-device BLE path.

```bash
pip install -r requirements-dev.txt
TRANSPORT=ws python -m src.main
```

- WebSocket peripheral: `ws://0.0.0.0:8765` (mirrors the BLE protocol:
  `announce` on connect, `read_device_info`, `command`).
- Kiosk display: `http://0.0.0.0:8026` (QR → Connected → Running job countdown).
- Wallet key, server wallet, and kiosk state are written under `./dev_state/`.

Override ports/paths with `KIOSK_PORT`, `WALLET_KEY_FILE`, `SERVER_WALLET_FILE`,
`KIOSK_STATE_DIR`.

> The mock relay (no `machine` module) does not self-deactivate on a timer, so
> a `TRIGGER`/`TIMED` job logs "Relay ON" without an auto-off; the kiosk
> countdown and disconnect-safety still behave correctly.
```

- [ ] **Step 6: Document the dev mode in CLAUDE.md**

Add this section to `CLAUDE.md` after the "## Commands" section:

```markdown
## Local dev (WebSocket, no BLE/GPIO)

`TRANSPORT=ws python -m src.main` runs a CPython WebSocket transport
(`TapayokaPicoWs`) + a browser kiosk instead of BLE, so the firmware logic can
be driven on a Mac. WS on `8765`, kiosk on `8026`, state under `./dev_state/`.
All ws-mode modules (`ws_peripheral`, `kiosk_server`, `kiosk_state`) are
CPython-only and are never imported on the Pico (the `ws` branch is unreachable
in MicroPython, which has no `os.getenv`).
```

- [ ] **Step 7: Commit**

```bash
git add src/main.py .gitignore README.md CLAUDE.md
git commit -m "feat: add TRANSPORT=ws dev harness entrypoint + docs"
```

---

## Self-Review

**1. Spec coverage:**
- Transport switch in `main.py` → Task 5. ✓
- Dev paths under `./dev_state/` → Task 5 Step 1. ✓
- Env-aware `config.py` (MicroPython-safe) → Task 1. ✓
- `RUNNING` wiring in ws layer (not handler), pin/duration derivation → Task 4 (`_show_running`) + test. ✓
- `ws_peripheral.py` (announce / device_info / command / disconnect-safety) → Task 4. ✓
- `kiosk_server.py` ported, `/qrcode.min.js` route dropped → Task 3. ✓
- `kiosk_state.py` ported (`update_kiosk_state`, `generate_deep_link`) → Task 2. ✓
- `requirements-dev.txt` (`websockets`, `qrcode[pil]`) → Task 1. ✓
- `.gitignore` `dev_state/` → Task 5. ✓
- README/CLAUDE docs → Task 5. ✓
- Wire protocol parity → Task 4 test asserts announce/device_info/command. ✓
- Tests (ws + kiosk) → Tasks 2, 3, 4. ✓
- Known limitation documented → Task 5 README. ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows full content. ✓

**3. Type consistency:** `TapayokaPicoWs(wallet, relay, kiosk_state_dir)`, `device_name`, `_state_file()`, `_build_device_info()`, `_show_running(cmd_env)`, `_handle_connection(ws)`, `start(host, port)` are used consistently across Task 4 code and tests. `update_kiosk_state` / `generate_deep_link` / `start_kiosk_server` signatures match between definition (Tasks 2, 3) and call sites (Tasks 4, 5). ✓
