"""Kiosk state management - writes JSON for the kiosk HTTP page.

CPython dev-only (TRANSPORT=ws); never imported on the Pico.
"""

from __future__ import annotations

import json
import os
import socket
import time
from urllib.parse import urlencode

import qrcode


def _write_json_atomic(path: str, data: dict[str, object]) -> None:
    """Write JSON to a file atomically and ensure world-readable permissions."""
    try:
        target_dir = os.path.dirname(path)
        if target_dir and not os.path.exists(target_dir):
            os.makedirs(target_dir, exist_ok=True)

        temp_file = path + ".tmp"
        with open(temp_file, "w") as f:
            json.dump(data, f)
        os.replace(temp_file, path)
        try:
            os.chmod(path, 0o666)
        except OSError:
            pass
    except PermissionError as e:
        print(f"[Kiosk] Permission denied writing to {path}: {e}")
    except Exception as e:
        print(f"[Kiosk] Error writing {path}: {e}")


def update_kiosk_state(
    state_file: str,
    *,
    status: str,
    qr_url: str | None = None,
    message: str | None = None,
    duration_seconds: int | None = None,
    started_at: int | None = None,
    pin: int | None = None,
) -> None:
    """Write kiosk state so the HTML page can render the correct view."""
    payload: dict[str, object] = {
        "status": status,
        "timestamp": int(time.time() * 1000),
    }
    if qr_url:
        payload["qr_url"] = qr_url
    if message:
        payload["message"] = message
    if duration_seconds is not None:
        payload["duration_seconds"] = duration_seconds
    if started_at is not None:
        payload["started_at"] = started_at
    if pin is not None:
        payload["pin"] = pin

    _write_json_atomic(state_file, payload)
    print(f"[Kiosk] State updated: {status}")


def _get_local_ip() -> str:
    """Get the machine's local network IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return str(ip)
    except Exception:
        return "127.0.0.1"


def generate_deep_link(
    transport: str,
    wallet_address: str,
    device_name: str,
    ws_port: int = 8765,
    state_dir: str | None = None,
) -> str:
    """Generate a tapayokav:// deep link and save a QR code PNG to state_dir."""
    params: dict[str, str] = {
        "transport": transport,
        "wallet": wallet_address,
        "name": device_name,
    }
    if transport == "ws":
        local_ip = _get_local_ip()
        params["wsUrl"] = f"ws://{local_ip}:{ws_port}"

    url = f"tapayokav://connect?{urlencode(params)}"

    if state_dir:
        os.makedirs(state_dir, exist_ok=True)
        qr = qrcode.QRCode(box_size=10, border=4)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        qr_path = os.path.join(state_dir, "qr.png")
        img.save(qr_path)
        print(f"[Kiosk] QR code PNG saved to {qr_path}")

    return url
