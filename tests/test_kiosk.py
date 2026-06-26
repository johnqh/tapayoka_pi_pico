"""Tests for the dev kiosk state + deep link helpers."""

import json

from src.kiosk_state import generate_deep_link, update_kiosk_state


def test_update_kiosk_state_running(tmp_path):
    state_file = str(tmp_path / "state.json")
    update_kiosk_state(state_file, status="RUNNING", pin=15,
                       duration_seconds=30, started_at=1000)
    with open(state_file) as f:
        state = json.load(f)
    assert state["status"] == "RUNNING"
    assert state["pin"] == 15
    assert state["duration_seconds"] == 30
    assert state["started_at"] == 1000
    assert "timestamp" in state


def test_update_kiosk_state_qr(tmp_path):
    state_file = str(tmp_path / "state.json")
    update_kiosk_state(state_file, status="QR", qr_url="tapayokav://x",
                       message="Scan to connect")
    with open(state_file) as f:
        state = json.load(f)
    assert state["status"] == "QR"
    assert state["qr_url"] == "tapayokav://x"


def test_generate_deep_link_ws_writes_qr(tmp_path):
    url = generate_deep_link(
        transport="ws",
        wallet_address="0xabc",
        device_name="tapayoka-abc",
        state_dir=str(tmp_path),
    )
    assert url.startswith("tapayokav://connect?")
    assert "wsUrl=ws" in url
    assert (tmp_path / "qr.png").exists()
