"""以真實 socket（h11 路徑）驗證回應大小上限：無限 chunked 本文會被截斷。"""

from __future__ import annotations

import asyncio
import json
import socketserver
import threading
import time

import pytest
from api_support import api_client
from support import load_fixture

from smart_health_backend.app import create_app
from smart_health_backend.config import AppConfig, TargetConfig

pytestmark = pytest.mark.anyio

LIMIT = 64 * 1024
CHUNK = 16 * 1024
SEND_CAP = 64 * 1024 * 1024  # 防呆：伺服器最多送這麼多就停，避免測試失敗時無限送出


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.results: list[tuple[int, str]] = []  # 每條 /status 連線：(已送出位元組, 結束原因)
        self.topology = json.dumps(load_fixture("topology_edge.json")).encode()


class _Handler(socketserver.StreamRequestHandler):
    server: _Server

    def handle(self) -> None:
        request_line = self.rfile.readline().decode("latin-1")
        while self.rfile.readline() not in (b"\r\n", b"\n", b""):
            pass
        if " /topology " in request_line:
            body = self.server.topology
            self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                             b"Content-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)
            return
        self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                         b"Transfer-Encoding: chunked\r\n\r\n")
        chunk = b"%x\r\n" % CHUNK + b" " * CHUNK + b"\r\n"
        sent, reason = 0, "cap"
        try:
            while sent < SEND_CAP:
                self.wfile.write(chunk)
                sent += CHUNK
        except OSError as exc:  # 對方關閉連線：BrokenPipe 或 ConnectionReset
            reason = type(exc).__name__
        self.server.results.append((sent, reason))


@pytest.fixture
def server():
    srv = _Server()
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05})
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(5)


async def test_infinite_chunked_body_is_cut_on_real_socket(server):
    port = server.server_address[1]
    config = AppConfig(
        poll_interval_s=0.2, request_timeout_s=5, max_response_bytes=LIMIT,
        targets=[TargetConfig(id="big", name="Big", base_url=f"http://127.0.0.1:{port}")],
    )
    async with api_client(create_app(config)) as client:
        deadline = time.monotonic() + 3  # 遠小於 5 秒逾時：是上限讓讀取停止
        while True:
            body = (await client.get("/api/targets/big")).json()
            if body["connection"] == "invalid_response":
                break
            assert time.monotonic() < deadline, body["connection"]
            await asyncio.sleep(0.02)
        assert body["topology"] is not None
        assert {n["color"] for n in body["nodes"].values()} == {"gray"}
    for _ in range(100):  # 等伺服器端察覺連線被關閉
        if server.results:
            break
        await asyncio.sleep(0.05)
    sent, reason = server.results[0]
    assert reason in ("BrokenPipeError", "ConnectionResetError"), reason
    assert sent < 8 * 1024 * 1024  # 上限加上 socket 緩衝
