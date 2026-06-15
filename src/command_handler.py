"""Transport-agnostic command handling for the Pico BLE peripheral."""

from .eth_wallet import EthWallet

MAX_SIGNAL_SECONDS = 3600
MIN_BCM_PIN = 0
MAX_BCM_PIN = 27


def validate_signals(signals):
    if not isinstance(signals, list) or not signals:
        return None
    result = []
    for sig in signals:
        if not isinstance(sig, dict):
            return None
        pin = sig.get("pinNumber")
        duration = sig.get("duration")
        if not isinstance(pin, int) or isinstance(pin, bool):
            return None
        if pin < MIN_BCM_PIN or pin > MAX_BCM_PIN:
            return None
        if not isinstance(duration, (int, float)) or isinstance(duration, bool):
            return None
        if duration <= 0 or duration > MAX_SIGNAL_SECONDS:
            return None
        result.append({"pinNumber": pin, "duration": duration})
    return result


class CommandHandler:
    def __init__(self, wallet, relay):
        self._wallet = wallet
        self._relay = relay
        self._server_wallet = EthWallet.load_server_wallet()

    def handle(self, msg):
        command = str(msg.get("command", "")).upper()
        print("[CMD]", command)
        if command == "SETUP_SERVER":
            return self._setup_server(msg)
        if command == "EXECUTE":
            return self._execute(msg)
        return {"status": "ERROR", "message": "Unknown command: " + command}

    def _setup_server(self, msg):
        if not self._wallet.verify_signed_payload(msg):
            return {"status": "UNAUTHORIZED", "message": "Invalid server signature"}
        address = msg.get("signing", {}).get("walletAddress", "")
        if not address or not address.startswith("0x"):
            return {"status": "ERROR", "message": "Invalid server wallet address"}
        EthWallet.save_server_wallet(address)
        self._server_wallet = address
        return {"status": "OK", "message": "Server wallet configured"}

    def _execute(self, msg):
        if not self._server_wallet:
            return {"status": "ERROR", "message": "No server wallet configured"}
        if not self._wallet.verify_signed_payload(msg, expected_signer=self._server_wallet):
            return {"status": "UNAUTHORIZED", "message": "Invalid server signature"}

        data = msg.get("data", {})
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
