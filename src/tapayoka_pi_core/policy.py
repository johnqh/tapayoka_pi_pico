"""Pure policy helpers shared by Tapayoka Pi and Pico."""

import json
import time

MAX_SIGNAL_SECONDS = 3600
MIN_BCM_PIN = 0
MAX_BCM_PIN = 27
MAX_SEEN_NONCES = 512


def _days_from_civil(year, month, day):
    year = year - 1 if month <= 2 else year
    era = year // 400 if year >= 0 else (year - 399) // 400
    year_of_era = year - era * 400
    month_index = month + 9 if month <= 2 else month - 3
    day_of_year = (153 * month_index + 2) // 5 + day - 1
    day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
    return era * 146097 + day_of_era - 719468


def validate_signals(signals, max_signal_seconds=MAX_SIGNAL_SECONDS, min_bcm_pin=MIN_BCM_PIN, max_bcm_pin=MAX_BCM_PIN):
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
        if pin < min_bcm_pin or pin > max_bcm_pin:
            return None
        if not isinstance(duration, (int, float)) or isinstance(duration, bool):
            return None
        if duration <= 0 or duration > max_signal_seconds:
            return None
        result.append({"pinNumber": pin, "duration": duration})
    return result


def build_challenge_data(wallet_address, timestamp, nonce):
    return {
        "walletAddress": wallet_address,
        "timestamp": int(timestamp),
        "nonce": nonce,
    }


def build_device_info_data(wallet_address, firmware_version, has_server_wallet, timestamp, nonce):
    return {
        "walletAddress": wallet_address,
        "firmwareVersion": firmware_version,
        "hasServerWallet": bool(has_server_wallet),
        "timestamp": int(timestamp),
        "nonce": nonce,
    }


def build_signed_response_data(data, signing_timestamp):
    message = dict(data)
    message["signing_timestamp"] = signing_timestamp
    return message


def parse_signing_timestamp(signing_timestamp):
    if signing_timestamp is None:
        return None
    if isinstance(signing_timestamp, bool):
        return None
    if isinstance(signing_timestamp, (int, float)):
        return float(signing_timestamp)
    if not isinstance(signing_timestamp, str):
        return None
    text = signing_timestamp.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        text = text.split(".", 1)[0]
    if len(text) >= 19:
        text = text[:19]
    try:
        parts = (
            int(text[0:4]),
            int(text[5:7]),
            int(text[8:10]),
            int(text[11:13]),
            int(text[14:16]),
            int(text[17:19]),
            0,
            0,
            -1,
        )
        days = _days_from_civil(parts[0], parts[1], parts[2])
        return float(days * 86400 + parts[3] * 3600 + parts[4] * 60 + parts[5])
    except Exception:
        try:
            return float(signing_timestamp)
        except Exception:
            return None


def is_command_expired(exp, now=None):
    if now is None:
        now = time.time()
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return True
    return exp < now


def is_nonce_valid(nonce):
    return isinstance(nonce, str) and bool(nonce)


def prune_seen_nonces(seen_nonces, now=None, max_seen_nonces=MAX_SEEN_NONCES):
    if now is None:
        now = time.time()
    expired = [nonce for nonce, exp in seen_nonces.items() if exp < now]
    for nonce in expired:
        del seen_nonces[nonce]
    if len(seen_nonces) <= max_seen_nonces:
        return
    oldest = sorted(seen_nonces.items(), key=lambda item: item[1])
    for nonce, _exp in oldest[: len(seen_nonces) - max_seen_nonces]:
        del seen_nonces[nonce]


def verify_signed_envelope(data, signing, recover_address, expected_signer=None, max_age_s=30.0):
    try:
        message = signing["message"]
        decoded = json.loads(message)

        signing_ts = decoded.pop("signing_timestamp", None)
        signed_at = parse_signing_timestamp(signing_ts)
        if signed_at is not None:
            age = abs(time.time() - signed_at)
            if age > max_age_s:
                return False

        if json.dumps(decoded) != json.dumps(data):
            return False

        signer = recover_address(message, signing["signature"])
        if not signer:
            return False
        if signer.lower() != signing["walletAddress"].lower():
            return False
        if expected_signer and signer.lower() != expected_signer.lower():
            return False
        return True
    except Exception:
        return False
