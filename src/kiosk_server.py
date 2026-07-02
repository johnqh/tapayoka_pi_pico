"""Simple HTTP server for the kiosk display page.

CPython dev-only (TRANSPORT=ws); never imported on the Pico.
"""

from __future__ import annotations

import json
import os
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler

KIOSK_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Tapayoka</title>
  <style>
    *, *:before, *:after { padding: 0; margin: 0; box-sizing: border-box; }
    @media (pointer: coarse), (pointer: none) { html, body { cursor: none; } }
    html, body { height: 100%; }
    body {
      background-color: #080710;
      font-family: 'Helvetica Neue', Arial, sans-serif;
      color: #ffffff;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      text-align: center;
      padding: 16px;
      overflow: hidden;
    }
    .hidden { display: none !important; }

    #qr-view { display: flex; flex-direction: column; align-items: center; }
    #qr-img {
      width: min(300px, 64vh, 82vw);
      height: min(300px, 64vh, 82vw);
      display: block;
    }
    #qr-caption {
      font-size: clamp(15px, 4.5vw, 24px);
      font-weight: 400;
      margin-top: clamp(10px, 3vh, 28px);
      opacity: 0.9;
    }

    #connected-view { display: flex; flex-direction: column; align-items: center; }
    #connected-text {
      font-size: clamp(30px, 9vw, 52px);
      font-weight: 300;
      letter-spacing: 0.5px;
    }

    #job-status {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: clamp(10px, 2.5vw, 16px);
      margin-top: clamp(12px, 3.5vh, 28px);
      font-size: clamp(16px, 5vw, 26px);
      font-weight: 300;
    }
    .led {
      width: clamp(11px, 3vw, 16px);
      height: clamp(11px, 3vw, 16px);
      flex: none;
      border-radius: 50%;
      background: #2ecc71;
      box-shadow: 0 0 10px 2px rgba(46, 204, 113, 0.7);
      animation: pulse 1.6s ease-in-out infinite;
    }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
    #job-timer { font-variant-numeric: tabular-nums; min-width: 3.5ch; }

    /* Action detail (the relay signals being run) */
    #job-action {
      margin-top: clamp(8px, 2vh, 16px);
      font-size: clamp(13px, 3.2vw, 18px);
      font-weight: 300;
      opacity: 0.7;
      letter-spacing: 0.3px;
      max-width: 90vw;
    }
  </style>
</head>
<body>
  <div id="qr-view" class="hidden">
    <img id="qr-img" alt="QR code">
    <p id="qr-caption">Scan to continue</p>
  </div>
  <div id="connected-view" class="hidden">
    <div id="connected-text">Connected</div>
    <div id="job-status" class="hidden">
      <span class="led"></span>
      <span id="job-pin"></span>
      <span id="job-timer">00:00</span>
    </div>
    <div id="job-action" class="hidden"></div>
  </div>
  <script>
    let lastTimestamp = -1;
    let countdownInterval = null;

    function fmt(sec) {
      sec = Math.max(0, sec);
      const m = Math.floor(sec / 60), s = sec % 60;
      return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    }
    function show(el, on) { el.classList.toggle('hidden', !on); }
    function stopCountdown() {
      if (countdownInterval) { clearInterval(countdownInterval); countdownInterval = null; }
    }

    function actionLabel(data) {
      const signals = Array.isArray(data.signals) ? data.signals : [];
      if (!signals.length) return '';
      const kind = data.offering_type || '';
      if (kind === 'TIMED') return 'PIN ' + signals[0].pinNumber + ' · held';
      if (kind === 'TRIGGER') return 'PIN ' + signals[0].pinNumber + ' · pulse';
      return signals.map(s => 'PIN ' + s.pinNumber + ' · ' + s.duration + 's').join('  →  ');
    }

    function render(data) {
      const qrView = document.getElementById('qr-view');
      const connView = document.getElementById('connected-view');
      const jobStatus = document.getElementById('job-status');
      const jobAction = document.getElementById('job-action');

      if (data.status === 'RUNNING') {
        show(qrView, false);
        show(connView, true);
        show(jobStatus, true);
        document.getElementById('job-pin').textContent =
          (data.pin === undefined || data.pin === null) ? '' : ('PIN ' + data.pin);
        const label = actionLabel(data);
        jobAction.textContent = label;
        show(jobAction, label !== '');
        stopCountdown();
        const start = data.started_at, duration = data.duration_seconds;
        const tick = () => {
          const now = Math.floor(Date.now() / 1000);
          const remaining = Math.max(0, duration - (now - start));
          document.getElementById('job-timer').textContent = fmt(remaining);
          if (remaining <= 0) stopCountdown();
        };
        tick();
        countdownInterval = setInterval(tick, 1000);

      } else if (data.status === 'CONNECTED') {
        stopCountdown();
        show(qrView, false);
        show(connView, true);
        show(jobStatus, false);
        show(jobAction, false);

      } else if (data.status === 'QR' && data.qr_url) {
        stopCountdown();
        show(connView, false);
        show(jobStatus, false);
        show(jobAction, false);
        document.getElementById('qr-img').src = '/qr.png?t=' + data.timestamp;
        show(qrView, true);
      }
    }

    function poll() {
      fetch('/state.json')
        .then(r => r.json())
        .then(data => {
          if (data.timestamp <= lastTimestamp) return;
          lastTimestamp = data.timestamp;
          render(data);
        })
        .catch(() => {});
    }
    setInterval(poll, 1000);
    poll();
  </script>
</body>
</html>
"""


class KioskHandler(SimpleHTTPRequestHandler):
    """Serves the kiosk HTML page and state.json from a directory."""

    def __init__(self, *args, state_dir: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self._state_dir = state_dir
        super().__init__(*args, directory=state_dir, **kwargs)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/" or path == "/index.html":
            self._serve_string(KIOSK_HTML, "text/html")
        elif path == "/state.json":
            state_file = os.path.join(self._state_dir, "state.json")
            if os.path.exists(state_file):
                with open(state_file) as f:
                    content = f.read()
                self._serve_string(content, "application/json")
            else:
                idle = json.dumps({"status": "IDLE", "timestamp": 0})
                self._serve_string(idle, "application/json")
        elif path == "/qr.png":
            qr_path = os.path.join(self._state_dir, "qr.png")
            if os.path.exists(qr_path):
                self._serve_binary(qr_path, "image/png")
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def _serve_string(self, content: str, content_type: str) -> None:
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _serve_binary(self, path: str, content_type: str) -> None:
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        pass


def start_kiosk_server(state_dir: str, port: int = 8026) -> HTTPServer:
    """Start the kiosk HTTP server in a background thread. Returns the server."""
    os.makedirs(state_dir, exist_ok=True)

    handler = partial(KioskHandler, state_dir=state_dir)
    server = HTTPServer(("0.0.0.0", port), handler)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[Kiosk] HTTP server started on http://0.0.0.0:{server.server_address[1]}")
    return server
