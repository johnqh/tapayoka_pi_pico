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
    env = ble._build_device_info()
    recovered = Account.recover_message(
        encode_defunct(text=env["signing"]["message"]),
        signature=env["signing"]["signature"],
    )
    assert recovered.lower() == ble._wallet.address.lower()
    decoded = json.loads(env["signing"]["message"])
    signing_ts = decoded.pop("signing_timestamp")
    assert isinstance(signing_ts, str)
    assert decoded == env["data"]
