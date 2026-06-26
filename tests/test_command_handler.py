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


def _execute(server, data):
    return _signed(server, "EXECUTE", data)


def _setup(server):
    return _signed(server, "SETUP_SERVER", {"walletAddress": server.address})


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

    def test_execute_rejects_expired_command(self, handler):
        server = Account.create()
        handler.handle(_setup(server))
        data = {"orderId": "o1", "offeringType": "TIMED", "seconds": 1, "nonce": "n", "exp": 1}
        assert handler.handle(_execute(server, data))["status"] == "UNAUTHORIZED"

    def test_execute_rejects_replay(self, handler, monkeypatch):
        server = Account.create()
        handler.handle(_setup(server))
        monkeypatch.setattr(handler._relay, "activate", lambda duration_seconds=0: None)
        data = {"orderId": "o1", "offeringType": "TIMED", "seconds": 1, "nonce": "n", "exp": 9999999999}
        assert handler.handle(_execute(server, data))["status"] == "OK"
        assert handler.handle(_execute(server, data))["status"] == "UNAUTHORIZED"

    def test_execute_no_server_wallet(self, handler):
        server = Account.create()
        resp = handler.handle(_execute(server, {"orderId": "o1", "offeringType": "TIMED", "seconds": 1,
                                                "nonce": "n", "exp": 9999999999}))
        assert resp["status"] == "NOT_CONFIGURED"

    def test_execute_bad_signature(self, handler):
        server = Account.create()
        handler.handle(_setup(server))
        other = Account.create()
        resp = handler.handle(_execute(other, {"orderId": "o1", "offeringType": "TIMED", "seconds": 1,
                                               "nonce": "n", "exp": 9999999999}))
        assert resp["status"] == "UNAUTHORIZED"

    def test_unknown_command(self, handler):
        assert handler.handle({"command": "BOGUS"})["status"] == "ERROR"
