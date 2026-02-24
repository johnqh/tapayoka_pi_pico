"""Tests for lightweight Pico W ETH wallet."""

import json
import os
from unittest.mock import patch

import pytest

from src.eth_wallet import EthWallet, _bytes_to_hex, _keccak256, _random_bytes


@pytest.fixture
def temp_wallet_dir(tmp_path):
    with (
        patch("src.eth_wallet.WALLET_KEY_FILE", str(tmp_path / "device_key.json")),
        patch("src.eth_wallet.SERVER_WALLET_FILE", str(tmp_path / "server_wallet.txt")),
    ):
        yield tmp_path


def test_bytes_to_hex():
    assert _bytes_to_hex(b"\x00\xff\x0a") == "00ff0a"
    assert _bytes_to_hex(b"") == ""


def test_keccak256_returns_32_bytes():
    result = _keccak256(b"test data")
    assert len(result) == 32


def test_random_bytes_length():
    result = _random_bytes(16)
    assert len(result) == 16


def test_wallet_creates_new_keypair(temp_wallet_dir):
    wallet = EthWallet()
    assert wallet.address.startswith("0x")
    assert len(wallet.address) == 42


def test_wallet_loads_existing_keypair(temp_wallet_dir):
    w1 = EthWallet()
    addr1 = w1.address
    w2 = EthWallet()
    assert w2.address == addr1


def test_address_short(temp_wallet_dir):
    wallet = EthWallet()
    short = wallet.address_short
    assert len(short) == 8
    assert short == wallet.address[2:10].lower()


def test_sign_challenge(temp_wallet_dir):
    wallet = EthWallet()
    challenge = wallet.sign_challenge()
    assert "walletAddress" in challenge
    assert "timestamp" in challenge
    assert "nonce" in challenge
    assert "signedPayload" in challenge
    assert "signature" in challenge
    assert challenge["walletAddress"] == wallet.address


def test_sign_challenge_unique_nonces(temp_wallet_dir):
    wallet = EthWallet()
    c1 = wallet.sign_challenge()
    c2 = wallet.sign_challenge()
    assert c1["nonce"] != c2["nonce"]


def test_verify_server_signature_valid_hex(temp_wallet_dir):
    wallet = EthWallet()
    # Valid 32-byte hex signature
    sig = "a" * 64
    assert wallet.verify_server_signature("payload", sig, "0xserver")


def test_verify_server_signature_rejects_empty(temp_wallet_dir):
    wallet = EthWallet()
    assert not wallet.verify_server_signature("payload", "", "0xserver")
    assert not wallet.verify_server_signature("payload", "valid", "")


def test_verify_server_signature_rejects_invalid_hex(temp_wallet_dir):
    wallet = EthWallet()
    assert not wallet.verify_server_signature("payload", "not-hex!", "0xserver")


def test_save_and_load_server_wallet(temp_wallet_dir):
    EthWallet.save_server_wallet("0xTestServerAddress")
    loaded = EthWallet.load_server_wallet()
    assert loaded == "0xTestServerAddress"


def test_load_server_wallet_empty(temp_wallet_dir):
    result = EthWallet.load_server_wallet()
    assert result == ""
