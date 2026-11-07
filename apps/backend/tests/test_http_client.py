"""後端的 httpx client 不使用環境變數的 proxy 設定（trust_env=False）。"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from api_support import api_client, free_port
from support import load_fixture, wait_until

from smart_health_backend.app import create_app
from smart_health_backend.config import AppConfig, TargetConfig

pytestmark = pytest.mark.anyio

BODIES = {
    "/topology": json.dumps(load_fixture("topology_edge.json")).encode(),
    "/status": json.dumps(load_fixture("status_edge_camera_down.json")).encode(),
}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass

    def do_GET(self):  # noqa: N802
        body = BODIES.get(self.path)
        self.send_response(200 if body else 404)
        self.send_header("Content-Length", str(len(body or b"")))
        self.end_headers()
        self.wfile.write(body or b"")


@pytest.fixture
def service_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
    thread.join(5)


async def test_proxy_environment_is_ignored(monkeypatch, service_url):
    dead_proxy = f"http://127.0.0.1:{free_port()}"  # 沒有人監聽：若走 proxy 一定 offline
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, dead_proxy)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    config = AppConfig(poll_interval_s=0.1, request_timeout_s=1,
                       targets=[TargetConfig(id="edge", name="Edge", base_url=service_url)])
    app = create_app(config)
    async with api_client(app):
        store = app.state.store
        await wait_until(lambda: store.get_view("edge").connection != "unknown", 3)
        assert store.get_view("edge").connection == "online"
        assert app.state.client.trust_env is False
