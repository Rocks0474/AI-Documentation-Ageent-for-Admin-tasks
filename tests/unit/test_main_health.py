"""The container health endpoint responds 200 (Cloud Run / ECS health check)."""

from __future__ import annotations

import threading
import urllib.request

import main


def test_health_server_responds_ok():
    server = main.build_health_server(port=0)  # ephemeral port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as resp:
            assert resp.status == 200
            assert resp.read() == b"ok"
    finally:
        server.shutdown()
