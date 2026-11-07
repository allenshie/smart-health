"""raw_mock：故意回傳不符合契約的內容，用來驗證後端防護。

只用標準函式庫，不 import smart_health_record，才能回傳函式庫不會產生的內容。

    python raw_mock.py --mode {hang,http_500,invalid_json,wrong_schema,
                               missing_nodes,topology_change,evaluation_stale} --port <p>
                       [--hang-max-s 60]

hang 模式不送任何 HTTP 回應，直到對方關閉連線、程序停止或掛起超過 --hang-max-s，
之後直接關閉連線，所以掛起的請求不會讓執行緒無限累積。
"""
import argparse
import hashlib
import json
import signal
import socket
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODES = ["hang", "http_500", "invalid_json", "wrong_schema", "missing_nodes",
         "topology_change", "evaluation_stale"]
HANG = object()  # respond() 的哨兵值：不回應，交給 handler 等待對方斷線
HANG_POLL_S = 0.2  # 掛起時檢查程序停止與上限的間隔
HANDLER_TIMEOUT_S = 10  # 只連線不送請求的 client 不會讓 handler 永遠阻塞


def wait_for_disconnect(sock, stop_event, max_s):
    """不回應，直到對方關閉連線、程序停止或超過 max_s。

    讀到的資料直接丟棄，避免 MSG_PEEK 造成忙迴圈。
    """
    deadline = time.monotonic() + max_s
    sock.settimeout(HANG_POLL_S)
    while not stop_event.is_set() and time.monotonic() < deadline:
        try:
            if not sock.recv(4096):  # b"" 代表對方已關閉
                return
        except socket.timeout:
            continue
        except OSError:
            return


def topology_version(lanes, nodes):
    text = json.dumps({"lanes": lanes, "nodes": nodes}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _node(node_id, upstream=()):
    return {"id": node_id, "label": node_id.title(), "upstream": list(upstream),
            "dependencies": []}


# 兩種架構：topology_change 模式依時間在兩者間切換，節點內容和版本一起變
LAYOUTS = [
    (["ingest", "infer", "publish"],
     [_node("ingest"), _node("infer", ["ingest"]), _node("publish", ["infer"])]),
    (["ingest", "infer", "stream", "publish"],
     [_node("ingest"), _node("infer", ["ingest"]), _node("stream", ["infer"]),
      _node("publish", ["infer"])]),
]


def build_topology(layout, instance):
    order, nodes = LAYOUTS[layout]
    lanes = [{"id": "main", "label": "Main", "parent": None, "sequential": True,
              "nodes": order}]
    return {"schema_version": 1, "service": "raw", "instance": instance,
            "topology_version": topology_version(lanes, nodes),
            "lanes": lanes, "nodes": nodes}


def build_status(topology, *, drop=(), age=0.4):
    now = datetime.now().astimezone().isoformat(timespec="milliseconds")
    nodes = {n["id"]: {"state": "ok", "reason": None, "message": None,
                       "since": now, "metrics": {}}
             for n in topology["nodes"] if n["id"] not in drop}
    return {"schema_version": 1, "service": topology["service"],
            "instance": topology["instance"],
            "topology_version": topology["topology_version"],
            "started_at": now, "evaluated_at": now, "evaluation_age_s": age,
            "nodes": nodes,
            "recent_transitions": [{"node": n, "from": None, "to": "ok", "reason": None,
                                    "at": now} for n in nodes]}


class Responder:
    """依模式決定回應內容；回傳 (HTTP 碼, 內容 bytes)，hang 模式回傳 HANG。"""

    def __init__(self, mode, change_interval_s, stop_event, hang_max_s=60.0):
        self.mode, self.interval, self.stop_event = mode, change_interval_s, stop_event
        self.hang_max_s = hang_max_s
        self.started = time.monotonic()

    def layout(self):
        if self.mode != "topology_change":
            return 0
        return int((time.monotonic() - self.started) / self.interval) % len(LAYOUTS)

    def respond(self, path):
        mode = self.mode
        if mode == "hang":
            return HANG
        if mode == "http_500":
            return 500, b'{"error":"internal"}'
        if mode == "invalid_json":
            return 200, b"<html>this is not json"
        topology = build_topology(self.layout(), "raw-1")
        if path == "/topology":
            body = topology
        else:
            body = build_status(
                topology,
                drop=("publish",) if mode == "missing_nodes" else (),
                age=3600.0 if mode == "evaluation_stale" else 0.4)
        if mode == "wrong_schema":
            body["schema_version"] = 999
        return 200, json.dumps(body, ensure_ascii=False).encode("utf-8")


class Server(ThreadingHTTPServer):
    # socketserver 預設 backlog 只有 5：短時間湧入多條連線（例如 hang 模式下多個逾時重試）時
    # accept queue 會溢位，Linux 丟棄握手的最後一個 ACK，伺服器要等 SYN-ACK 重送才 accept
    request_queue_size = 128


def make_handler(responder):
    class Handler(BaseHTTPRequestHandler):
        timeout = HANDLER_TIMEOUT_S

        def log_message(self, format, *args):  # noqa: A002
            pass

        def do_GET(self):  # noqa: N802
            path = self.path.split("?")[0]
            if path not in ("/topology", "/status"):
                self.send_error(404)
                return
            result = responder.respond(path)
            if result is HANG:
                wait_for_disconnect(self.connection, responder.stop_event, responder.hang_max_s)
                self.close_connection = True  # 不送回應，直接關閉連線
                return
            code, body = result
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main(argv=None):
    p = argparse.ArgumentParser(description="smart_health raw_mock")
    p.add_argument("--mode", choices=MODES, required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--change-interval-s", type=float, default=10.0)
    p.add_argument("--hang-max-s", type=float, default=60.0,
                   help="hang 模式單一請求最長掛起秒數，超過就不回應直接關閉連線")
    args = p.parse_args(argv)
    if args.change_interval_s <= 0:
        p.error("--change-interval-s 必須大於 0")
    if not args.hang_max_s > 0:
        p.error("--hang-max-s 必須大於 0")

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    try:
        httpd = Server((args.host, args.port),
                       make_handler(Responder(args.mode, args.change_interval_s, stop,
                                              args.hang_max_s)))
    except OSError as exc:
        print(f"raw_mock 無法綁定 {args.host}:{args.port}：{exc}", file=sys.stderr, flush=True)
        return 2
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    print(f"raw_mock ready mode={args.mode} port={args.port}", flush=True)
    stop.wait()
    httpd.shutdown()
    httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
