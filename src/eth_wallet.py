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
