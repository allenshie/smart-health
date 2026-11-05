"""控制接口：獨立的 ThreadingHTTPServer，不隨 monitor 或 server 重建。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from .simulator import Simulator, UnknownScenario

_MAX_BODY = 4096


def make_handler(simulator: Simulator):
    class Handler(BaseHTTPRequestHandler):
        timeout = 5.0
        server_version = "MockControl"
        sys_version = ""

        def log_message(self, format, *args) -> None:  # noqa: A002
            """靜音。"""

        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?")[0] != "/scenario":
                self._send(404, {"error": "not_found"})
                return
            self._send(200, {"name": simulator.scenario})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.split("?")[0] != "/scenario":
                self._send(404, {"error": "not_found"})
                return
            name = self._read_name()
            if name is None:
                self._send(400, {"error": "body must be JSON like {\"name\": \"...\"}"})
                return
            try:
                simulator.set_scenario(name)  # 完成切換後才回應
            except UnknownScenario:
                self._send(400, {"error": f"unknown scenario: {name}",
                                 "scenarios": list(simulator.scenarios)})
                return
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"error": f"switch failed: {type(exc).__name__}"})
                return
            self._send(200, {"name": name})

        def _read_name(self) -> Optional[str]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= _MAX_BODY:
                    return None
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return None
            name = data.get("name") if isinstance(data, dict) else None
            return name if isinstance(name, str) else None

    return Handler


class ControlServer:
    def __init__(self, simulator: Simulator, host: str, port: int) -> None:
        self._httpd = ThreadingHTTPServer((host, port), make_handler(simulator))  # 綁定失敗拋 OSError
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True,
                                        name="mock-control")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(5.0)
