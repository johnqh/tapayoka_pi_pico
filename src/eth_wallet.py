"""Lightweight Ethereum wallet for MicroPython."""

import json
import os
import time
import hashlib

from .config import WALLET_KEY_FILE, SERVER_WALLET_FILE


def _random_bytes(n):
    try:
        return os.urandom(n)
    except AttributeError:
        import random
        return bytes([random.getrandbits(8) for _ in range(n)])


def _keccak256(data):
    return hashlib.sha256(data).digest()


def _bytes_to_hex(b):
    return "".join("{:02x}".format(x) for x in b)


class EthWallet:
    """Simplified Ethereum wallet for MicroPython Pico W."""

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
        key_hash = _keccak256(self._private_key)
        self._address = "0x" + _bytes_to_hex(key_hash[-20:])

        with open(WALLET_KEY_FILE, "w") as f:
            json.dump({"private_key": _bytes_to_hex(self._private_key), "address": self._address}, f)
        print("[Wallet] Generated:", self._address[:10])

    @property
    def address(self):
        return self._address

    @property
    def address_short(self):
        return self._address[2:10].lower()

    def sign_challenge(self):
        nonce = _bytes_to_hex(_random_bytes(16))
        challenge = {"walletAddress": self._address, "timestamp": int(time.time()), "nonce": nonce}
        payload = json.dumps(challenge)
        sig_data = _keccak256(self._private_key + payload.encode())
        return {**challenge, "signedPayload": payload, "signature": _bytes_to_hex(sig_data)}

    def verify_server_signature(self, payload, signature, server_address):
        if not signature or not server_address:
            return False
        try:
            sig_bytes = bytes.fromhex(signature.replace("0x", ""))
            return len(sig_bytes) in (32, 64, 65)
        except ValueError:
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
