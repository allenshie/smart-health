"""StatusServer：把 HealthMonitor 以 HTTP 對外提供（只用標準函式庫）。"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlsplit

from .monitor import HealthMonitor

_CONTENT_TYPE = "application/json; charset=utf-8"
_HANDLER_TIMEOUT_S = 5.0
_JOIN_TIMEOUT_S = 5.0


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, monitor: HealthMonitor) -> None:
        self.monitor = monitor
        super().__init__(address, handler)

    def handle_error(self, request, client_address) -> None:  # noqa: D401
        """靜音：不寫 stderr，也不記錄請求內容。"""


class _Handler(BaseHTTPRequestHandler):
    timeout = _HANDLER_TIMEOUT_S
    server_version = "SmartHealth"
    sys_version = ""

    def log_message(self, format, *args) -> None:  # noqa: A002
        """靜音。"""

    def _send(self, code: int, payload: dict, *, head_only: bool = False,
              allow: Optional[str] = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", _CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        if allow is not None:
            self.send_header("Allow", allow)
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        monitor = self.server.monitor
        if path == "/topology":
            read = monitor.topology
        elif path == "/status":
            read = monitor.status
        else:
            self._send(404, {"error": "not_found"})
            return
        try:
            payload = read()
        except RuntimeError:
            self._send(503, {"error": "monitor_not_started"})
            return
        except Exception:  # noqa: BLE001 - 不外洩例外內容，伺服器繼續服務
            self._send(500, {"error": "internal_error"})
            return
        self._send(200, payload)

    def _method_not_allowed(self) -> None:
        self._send(405, {"error": "method_not_allowed"},
                   head_only=self.command == "HEAD", allow="GET")

    def __getattr__(self, name: str):
        # 任何非 GET 的方法（含未知方法）都回 405，避免標準庫的 501 HTML。
        if name.startswith("do_"):
            return self._method_not_allowed
        raise AttributeError(name)


class StatusServer:
    """提供 `GET /topology`、`GET /status`；預設只綁定 127.0.0.1。

    `stop()` 後可再 `start()`；若建構時 port=0，重啟會沿用先前分配到的實際 port，
    不會重新分配。
    """

    def __init__(self, monitor: HealthMonitor, *, port: int, host: str = "127.0.0.1") -> None:
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("port 必須是 0 到 65535 的整數")
        self._monitor = monitor
        self._host = host
        self._port = port
        self._lock = threading.Lock()
        self._httpd: Optional[_Server] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> None:
        with self._lock:
            if self._httpd is not None:
                return
            httpd = _Server((self._host, self._port), _Handler, self._monitor)  # 綁定失敗拋 OSError
            thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True,
                                      name=f"smart-health-http-{httpd.server_address[1]}")
            self._httpd, self._thread = httpd, thread
            self._port = httpd.server_address[1]
            thread.start()

    def stop(self) -> None:
        with self._lock:
            httpd, thread = self._httpd, self._thread
            self._httpd = self._thread = None
        if httpd is None:
            return
        httpd.shutdown()
        httpd.server_close()
        if thread is not None:
            thread.join(_JOIN_TIMEOUT_S)
