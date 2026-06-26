"""Transport-agnostic command handling for the Pico BLE peripheral."""

import time

from .eth_wallet import EthWallet, verify_signed_payload
from tapayoka_pi_core import (
    MAX_SEEN_NONCES,
    STATUS_NOT_CONFIGURED,
    is_command_expired,
    is_nonce_valid,
    prune_seen_nonces,
    validate_signals,
)


class CommandHandler:
    def __init__(self, wallet, relay):
        self._wallet = wallet
        self._relay = relay
        self._server_wallet = EthWallet.load_server_wallet()
        self._seen_nonces = {}

    def handle(self, msg):
        command = str(msg.get("command", "")).upper()
        print("[CMD]", command)
        if command == "SETUP_SERVER":
            return self._setup_server(msg)
        if command == "EXECUTE":
            return self._execute(msg)
        return {"status": "ERROR", "message": "Unknown command: " + command}

    def _setup_server(self, msg):
        if not verify_signed_payload(msg):
            return {"status": "UNAUTHORIZED", "message": "Invalid server signature"}
        address = msg.get("signing", {}).get("walletAddress", "")
        if not address or not address.startswith("0x"):
            return {"status": "ERROR", "message": "Invalid server wallet address"}
        EthWallet.save_server_wallet(address)
        self._server_wallet = address
        return {"status": "OK", "message": "Server wallet configured"}

    def _execute(self, msg):
        if not self._server_wallet:
            return {"status": STATUS_NOT_CONFIGURED, "message": "Device not configured"}
        if not verify_signed_payload(msg, expected_signer=self._server_wallet):
            return {"status": "UNAUTHORIZED", "message": "Invalid server signature"}

        data = msg.get("data", {})
        now = time.time()
        exp = data.get("exp")
        if is_command_expired(exp, now):
            return {"status": "UNAUTHORIZED", "message": "Command expired"}
        nonce = data.get("nonce")
        if not is_nonce_valid(nonce):
            return {"status": "UNAUTHORIZED", "message": "Missing nonce"}
        prune_seen_nonces(self._seen_nonces, now, MAX_SEEN_NONCES)
        if nonce in self._seen_nonces:
            return {"status": "UNAUTHORIZED", "message": "Replay detected"}
        self._seen_nonces[nonce] = float(exp)

        seconds = data.get("seconds", 0)
        offering_type = data.get("offeringType", "TRIGGER")

        if offering_type == "FIXED" and data.get("signals"):
            signals = validate_signals(data.get("signals"))
            if signals is None:
                return {"status": "ERROR", "message": "Invalid signals"}
            if not self._relay.run_sequence(signals):
                return {"status": "BUSY", "message": "Device is busy"}
            total = int(sum(s["duration"] for s in signals))
            return {"status": "OK", "message": "Sequence started ({}s)".format(total)}

        if offering_type == "TRIGGER":
            self._relay.activate(duration_seconds=1)
            return {"status": "OK", "message": "Activated for 1s"}

        self._relay.activate(duration_seconds=seconds)
        return {"status": "OK", "message": "Activated for {}s".format(seconds)}

    def _prune_nonces(self, now):
        prune_seen_nonces(self._seen_nonces, now, MAX_SEEN_NONCES)
