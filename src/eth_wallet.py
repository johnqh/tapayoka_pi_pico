"""Ethereum wallet for MicroPython using real keccak-256 + secp256k1."""

import json
import os
import time

from .config import WALLET_KEY_FILE, SERVER_WALLET_FILE
from tapayoka_pi_core import (
    build_challenge_data,
    build_signed_response_data,
    verify_signed_envelope,
)
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


def _utc_iso_timestamp():
    try:
        t = time.gmtime()
        return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}Z".format(
            t[0], t[1], t[2], t[3], t[4], t[5]
        )
    except Exception:
        return str(int(time.time()))


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
        challenge = build_challenge_data(self._address, int(time.time()), _hex(_random_bytes(16)))
        message = json.dumps(challenge, sort_keys=True)
        return {
            **challenge,
            "signedPayload": message,
            "signature": self._sign_message(message),
        }

    def sign_response(self, data):
        message_obj = build_signed_response_data(data, _utc_iso_timestamp())
        message = json.dumps(message_obj)
        return {
            "walletAddress": self._address,
            "message": message,
            "signature": self._sign_message(message),
        }

    def verify_server_signature(self, payload, signature, server_address):
        try:
            sig_bytes = bytes.fromhex(signature.replace("0x", ""))
            raw = sig_bytes
            if len(raw) != 65:
                return False
            r = int.from_bytes(raw[0:32], "big")
            s = int.from_bytes(raw[32:64], "big")
            v = raw[64]
            if v < 27:
                v += 27
            x, y = recover(_eip191_hash(payload), r, s, v)
            recovered = pubkey_to_address(x, y)
            return recovered.lower() == server_address.lower()
        except Exception:
            return False

    def verify_signed_payload(self, payload, expected_signer=None, max_age_s=30.0):
        return verify_signed_payload(payload, expected_signer=expected_signer, max_age_s=max_age_s)

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


def verify_signed_response(data, signing, max_age_s=30.0):
    return verify_signed_envelope(data, signing, _recover_message_address, max_age_s=max_age_s)


def verify_signed_payload(payload, expected_signer=None, max_age_s=30.0):
    data = payload.get("data")
    signing = payload.get("signing")
    if not data or not signing:
        return False
    return verify_signed_envelope(
        data,
        signing,
        _recover_message_address,
        expected_signer=expected_signer,
        max_age_s=max_age_s,
    )


def _recover_message_address(message, signature):
    try:
        sig_bytes = bytes.fromhex(signature.replace("0x", ""))
        if len(sig_bytes) != 65:
            return None
        r = int.from_bytes(sig_bytes[0:32], "big")
        s = int.from_bytes(sig_bytes[32:64], "big")
        v = sig_bytes[64]
        if v < 27:
            v += 27
        x, y = recover(_eip191_hash(message), r, s, v)
        return pubkey_to_address(x, y)
    except Exception:
        return None
