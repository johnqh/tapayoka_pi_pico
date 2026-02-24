"""Tests for Pico BLE peripheral command handling."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.eth_wallet import EthWallet
from src.gpio_control import RelayController


# We can't import aioble on non-MicroPython, so test _handle_command directly
@pytest.fixture
def temp_wallet_dir(tmp_path):
    with (
        patch("src.eth_wallet.WALLET_KEY_FILE", str(tmp_path / "device_key.json")),
        patch("src.eth_wallet.SERVER_WALLET_FILE", str(tmp_path / "server_wallet.txt")),
    ):
        yield tmp_path


@pytest.fixture
def ble(temp_wallet_dir):
    # Import here since it patches aioble availability
    from src.ble_peripheral import TapayokaPicoBle
    wallet = EthWallet()
    relay = RelayController()
    return TapayokaPicoBle(wallet, relay)


class TestHandleCommand:
    def _cmd(self, command, **kwargs):
        return json.dumps({"command": command, **kwargs}).encode()

    def test_on_command(self, ble):
        result = ble._handle_command(self._cmd("ON"))
        assert result["status"] == "OK"
        assert ble._relay.is_active

    def test_off_command(self, ble):
        ble._relay.activate()
        result = ble._handle_command(self._cmd("OFF"))
        assert result["status"] == "OK"
        assert not ble._relay.is_active

    def test_status_command(self, ble):
        result = ble._handle_command(self._cmd("STATUS"))
        assert result["status"] == "OK"
        assert "data" in result
        data = json.loads(result["data"])
        assert "active" in data
        assert "walletAddress" in data

    def test_unknown_command(self, ble):
        result = ble._handle_command(self._cmd("BOGUS"))
        assert result["status"] == "ERROR"

    def test_invalid_json(self, ble):
        result = ble._handle_command(b"not json")
        assert result["status"] == "ERROR"

    def test_setup_server_valid(self, ble):
        result = ble._handle_command(
            self._cmd("SETUP_SERVER", payload="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD08")
        )
        assert result["status"] == "OK"
        assert ble._server_wallet == "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD08"

    def test_setup_server_invalid(self, ble):
        result = ble._handle_command(self._cmd("SETUP_SERVER", payload="bad"))
        assert result["status"] == "ERROR"

    def test_authorize_without_server_wallet(self, ble):
        ble._server_wallet = ""
        result = ble._handle_command(
            self._cmd("AUTHORIZE", payload="{}", signature="0xabc")
        )
        assert result["status"] == "ERROR"
        assert "No server wallet" in result["message"]

    def test_on_with_seconds(self, ble):
        result = ble._handle_command(self._cmd("ON", seconds=60))
        assert result["status"] == "OK"
        assert ble._relay.is_active
