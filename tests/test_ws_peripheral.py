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


def test_execute_unconfigured_closes_connection(peripheral):
    server = Account.create()

    async def scenario(ws):
        await ws.recv()  # announce
        cmd = _signed(server, "EXECUTE", {
            "orderId": "o1", "offeringType": "TIMED", "seconds": 1,
            "nonce": "n", "exp": 9999999999,
        })
        await ws.send(json.dumps({"type": "command", "data": cmd}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        # Server must close the socket right after the NOT_CONFIGURED response.
        with pytest.raises(websockets.exceptions.ConnectionClosed):
            await asyncio.wait_for(ws.recv(), timeout=5)
        return resp

    msg = asyncio.run(_run_client(peripheral, scenario))
    assert msg["type"] == "response"
    assert msg["data"]["status"] == "NOT_CONFIGURED"


def test_setup_then_execute_emits_running(peripheral, monkeypatch):
    monkeypatch.setattr(peripheral._relay, "activate", lambda duration_seconds=0, pin=None: None)
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
        # Read the kiosk state while still connected; the disconnect handler
        # resets it to "QR" once this scenario returns.
        with open(peripheral._state_file()) as f:
            state = json.load(f)
        return setup, execute, state

    setup, execute, state = asyncio.run(_run_client(peripheral, scenario))
    assert setup["data"]["status"] == "OK"
    assert execute["data"]["status"] == "OK"
    assert state["status"] == "RUNNING"
    assert state["duration_seconds"] == 5
    assert state["pin"] == 15


# ---------------------------------------------------------------------------
# Kiosk-state semantics: "Connected" must reflect engagement, not raw sockets.
# ---------------------------------------------------------------------------

def _read_status(peripheral):
    try:
        with open(peripheral._state_file()) as f:
            return json.load(f)["status"]
    except (OSError, ValueError, KeyError):
        return None


async def _serve_and(peripheral, scenario):
    async with websockets.serve(peripheral._handle_connection, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        return await scenario(port)


def test_announce_alone_does_not_show_connected(peripheral):
    """A discovery socket (announce only, no messages) must not show CONNECTED."""
    from src.kiosk_state import update_kiosk_state
    update_kiosk_state(peripheral._state_file(), status="QR", message="Scan to connect")

    async def scenario(port):
        async with websockets.connect("ws://127.0.0.1:%d" % port) as ws:
            ann = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert ann["type"] == "announce"
            await asyncio.sleep(0.1)  # pure discovery: send nothing
            return _read_status(peripheral)

    status = asyncio.run(_serve_and(peripheral, scenario))
    assert status != "CONNECTED"
    assert status == "QR"


def test_read_device_info_marks_connected(peripheral):
    """Reading device info (real engagement) flips the kiosk to CONNECTED."""
    async def scenario(port):
        async with websockets.connect("ws://127.0.0.1:%d" % port) as ws:
            await ws.recv()  # announce
            await ws.send(json.dumps({"type": "read_device_info"}))
            await asyncio.wait_for(ws.recv(), timeout=5)  # device_info
            await asyncio.sleep(0.05)
            return _read_status(peripheral)

    assert asyncio.run(_serve_and(peripheral, scenario)) == "CONNECTED"


def test_qr_restored_after_engaged_disconnect(peripheral):
    """When the last engaged client leaves, the kiosk returns to QR."""
    async def scenario(port):
        async with websockets.connect("ws://127.0.0.1:%d" % port) as ws:
            await ws.recv()  # announce
            await ws.send(json.dumps({"type": "read_device_info"}))
            await asyncio.wait_for(ws.recv(), timeout=5)  # device_info
        for _ in range(50):  # wait for the disconnect handler to run
            await asyncio.sleep(0.02)
            if _read_status(peripheral) == "QR":
                break
        return _read_status(peripheral)

    assert asyncio.run(_serve_and(peripheral, scenario)) == "QR"
