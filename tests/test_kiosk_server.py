"""Smoke test for the dev kiosk HTTP server."""

import json
import urllib.request

from src.kiosk_server import start_kiosk_server
from src.kiosk_state import update_kiosk_state


def _get(server, path):
    host, port = server.server_address
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def test_serves_html_and_state(tmp_path):
    update_kiosk_state(str(tmp_path / "state.json"), status="CONNECTED", message="Connected")
    server = start_kiosk_server(str(tmp_path), port=0)
    try:
        status, body = _get(server, "/")
        assert status == 200
        assert "<title>Tapayoka</title>" in body

        status, body = _get(server, "/state.json")
        assert status == 200
        assert json.loads(body)["status"] == "CONNECTED"
    finally:
        server.shutdown()
