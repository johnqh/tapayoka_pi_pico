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
