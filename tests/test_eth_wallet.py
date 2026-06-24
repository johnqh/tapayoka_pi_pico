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
    assert set(env.keys()) == {"walletAddress", "timestamp", "nonce", "signedPayload", "signature"}
    recovered = Account.recover_message(
        encode_defunct(text=env["signedPayload"]), signature=env["signature"]
    )
    assert recovered.lower() == w.address.lower()
    assert json.loads(env["signedPayload"]) == {
        "nonce": env["nonce"],
        "timestamp": env["timestamp"],
        "walletAddress": env["walletAddress"],
    }


def test_sign_response_envelope_recovers_to_device(temp_wallet_dir):
    w = EthWallet()
    data = {"status": "OK", "message": "ready"}
    signing = w.sign_response(data)
    assert set(signing.keys()) == {"walletAddress", "message", "signature"}
    msg = signing["message"]
    sig = signing["signature"]
    recovered = Account.recover_message(encode_defunct(text=msg), signature=sig)
    assert recovered.lower() == w.address.lower()
    decoded = json.loads(msg)
    decoded.pop("signing_timestamp")
    assert decoded == data


def _server_execute_envelope(server_account, data: dict) -> dict:
    message = json.dumps(data)
    signed = server_account.sign_message(encode_defunct(text=message))
    sig = signed.signature.hex()
    return {
        "data": data,
        "signing": {
            "walletAddress": server_account.address,
            "message": message,
            "signature": sig if sig.startswith("0x") else "0x" + sig,
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
