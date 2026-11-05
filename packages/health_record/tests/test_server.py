"""StatusServer：以真實 HTTP（port=0）驗證。"""
import http.client
import json
import socket
import threading
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from smart_health_record import HealthMonitor, StatusServer

CONTRACT = Path(__file__).resolve().parents[3] / "contract"
WAIT_S = 5.0


def schema(name):
    return Draft202012Validator(json.loads((CONTRACT / name).read_text(encoding="utf-8")))


@pytest.fixture
def monitor(clock, wall, logger):
    m = HealthMonitor("edge", "inst", clock=clock, wall_clock=wall, logger=logger)
    yield m
    m.stop()


@pytest.fixture
def serve():
    servers = []

    def factory(mon, **kw):
        kw.setdefault("port", 0)
        s = StatusServer(mon, **kw)
        servers.append(s)
        s.start()
        return s

    yield factory
    for s in servers:
        s.stop()


@pytest.fixture
def ready(monitor, edge_builder):
    edge_builder(monitor)
    monitor.evaluate_once()
    return monitor


def request(server, method, path, host="127.0.0.1"):
    conn = http.client.HTTPConnection(host, server.port, timeout=WAIT_S)
    try:
        conn.request(method, path)
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, resp, body
    finally:
        conn.close()


def get_json(server, path):
    status, resp, body = request(server, "GET", path)
    return status, resp, json.loads(body.decode("utf-8"))


def test_get_topology_and_status_match_schema(ready, serve):
    s = serve(ready)
    code, resp, topo = get_json(s, "/topology")
    assert code == 200
    assert resp.getheader("Content-Type") == "application/json; charset=utf-8"
    assert topo == ready.topology()
    schema("topology.schema.json").validate(topo)
    code, resp, st = get_json(s, "/status")
    assert code == 200
    schema("status.schema.json").validate(st)
    assert st["service"] == "edge"


def test_response_has_content_length_and_content_type(ready, serve):
    s = serve(ready)
    _, resp, body = request(s, "GET", "/status")
    assert int(resp.getheader("Content-Length")) == len(body)
    assert resp.getheader("Content-Type") == "application/json; charset=utf-8"


def test_non_ascii_not_escaped(clock, wall, logger, serve):
    m = HealthMonitor("edge", "倉庫一號", clock=clock, wall_clock=wall, logger=logger)
    m.add_lane("main", "主流程")
    m.add_node("a", "節點", "main")
    m.evaluate_once()
    s = serve(m)
    _, _, body = request(s, "GET", "/topology")
    assert "主流程".encode("utf-8") in body
    assert b"\\u" not in body


def test_unknown_path_returns_404_json(ready, serve):
    s = serve(ready)
    for path in ("/nope", "/", "/status/", "/topology/"):
        code, resp, data = get_json(s, path)
        assert code == 404
        assert data == {"error": "not_found"}
        assert resp.getheader("Content-Type") == "application/json; charset=utf-8"


def test_query_string_is_ignored(ready, serve):
    s = serve(ready)
    assert get_json(s, "/status?x=1")[0] == 200
    assert get_json(s, "/topology?a=b&c=d")[0] == 200


def test_post_returns_405(ready, serve):
    s = serve(ready)
    code, resp, body = request(s, "POST", "/status")
    assert code == 405
    assert resp.getheader("Allow") == "GET"
    assert json.loads(body) == {"error": "method_not_allowed"}


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@pytest.mark.parametrize("path", ["/status", "/nope"])
def test_other_methods_return_405_with_allow(ready, serve, method, path):
    s = serve(ready)
    code, resp, body = request(s, method, path)
    assert code == 405
    assert resp.getheader("Allow") == "GET"
    assert json.loads(body) == {"error": "method_not_allowed"}


@pytest.mark.parametrize("method", ["FOO", "TRACE", "CONNECT"])
def test_unlisted_methods_return_405_json(ready, serve, method):
    s = serve(ready)
    code, resp, body = request(s, method, "/status")
    assert code == 405
    assert resp.getheader("Allow") == "GET"
    assert resp.getheader("Content-Type") == "application/json; charset=utf-8"
    assert json.loads(body) == {"error": "method_not_allowed"}


def test_head_returns_405_without_body(ready, serve):
    s = serve(ready)
    code, resp, body = request(s, "HEAD", "/status")
    assert code == 405
    assert resp.getheader("Allow") == "GET"
    assert body == b""


def test_no_cors_headers(ready, serve):
    s = serve(ready)
    _, resp, _ = request(s, "GET", "/status")
    assert resp.getheader("Access-Control-Allow-Origin") is None


def test_default_host_is_loopback(ready, serve):
    s = serve(ready)
    assert s._httpd.server_address[0] == "127.0.0.1"


def test_port_in_use_raises_oserror(ready, serve):
    first = serve(ready)
    second = StatusServer(ready, port=first.port)
    with pytest.raises(OSError):
        second.start()
    second.stop()


def test_invalid_port_raises_value_error(ready):
    for bad in (-1, 65536, 100000):
        with pytest.raises(ValueError):
            StatusServer(ready, port=bad)


def test_port_property_before_and_after_start(ready, serve):
    s = StatusServer(ready, port=0)
    assert s.port == 0
    s.start()
    try:
        assert s.port != 0
    finally:
        s.stop()


def test_response_has_no_credentials(monitor, serve):
    monitor.add_lane("main", "Main")
    rec = monitor.add_node("a", "A", "main")
    rec.record_error("conn_failed", "connect rtsp://admin:hunter2pw@10.0.0.5/live failed")
    monitor.evaluate_once()
    s = serve(monitor)
    for path in ("/topology", "/status"):
        _, _, body = request(s, "GET", path)
        assert b"hunter2pw" not in body
    st = get_json(s, "/status")[2]
    assert st["nodes"]["a"]["message"] is not None


@pytest.fixture
def gates():
    events = []

    def new():
        e = threading.Event()
        events.append(e)
        return e

    yield new
    for e in events:
        e.set()


def test_status_does_not_block_while_evaluating(monitor, serve, gates):
    block, entered = gates(), gates()
    state = {"block": False}

    def dep():
        if state["block"]:
            entered.set()
            block.wait(WAIT_S)
        return True

    monitor.add_lane("main", "Main")
    monitor.add_node("a", "A", "main", dependencies={"d": dep})
    monitor.evaluate_once()
    s = serve(monitor)
    state["block"] = True
    t = threading.Thread(target=monitor.evaluate_once, daemon=True)
    t.start()
    assert entered.wait(WAIT_S)
    code, _, data = get_json(s, "/status")
    assert code == 200
    assert data["nodes"]["a"]["state"] in {"ok", "waiting"}
    block.set()
    t.join(WAIT_S)


def test_stop_releases_port(ready, serve):
    s = serve(ready)
    port = s.port
    s.stop()
    s2 = StatusServer(ready, port=port)
    s2.start()
    try:
        assert get_json(s2, "/status")[0] == 200
        assert s2.port == port
    finally:
        s2.stop()


def test_stop_closes_socket_and_joins_thread(ready, serve):
    s = serve(ready)
    thread = s._thread
    port = s.port
    s.stop()
    assert not thread.is_alive()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


def test_restart_after_stop_reuses_previous_port(ready):
    s = StatusServer(ready, port=0)
    s.start()
    port = s.port
    s.stop()
    s.start()
    try:
        assert s.port == port
        assert get_json(s, "/status")[0] == 200
    finally:
        s.stop()


def test_start_and_stop_are_idempotent(ready):
    s = StatusServer(ready, port=0)
    s.stop()  # 未啟動就停止
    s.start()
    port = s.port
    s.start()
    assert s.port == port
    s.stop()
    s.stop()


def test_threads_are_daemon(ready, serve):
    s = serve(ready)
    assert s._thread.daemon is True
    assert s._httpd.daemon_threads is True


def test_before_start_returns_503_json(monitor, serve):
    monitor.add_lane("main", "Main")
    monitor.add_node("a", "A", "main")
    s = serve(monitor)
    for path in ("/topology", "/status"):
        code, resp, data = get_json(s, path)
        assert code == 503
        assert data == {"error": "monitor_not_started"}
        assert resp.getheader("Content-Type") == "application/json; charset=utf-8"
    monitor.evaluate_once()
    assert get_json(s, "/status")[0] == 200


def test_unexpected_exception_returns_500_and_keeps_serving(ready, serve, monkeypatch):
    s = serve(ready)
    calls = {"n": 0}
    real = ready.status

    def boom():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("secret-detail")
        return real()

    monkeypatch.setattr(ready, "status", boom)
    code, _, body = request(s, "GET", "/status")[0:3]
    assert code == 500
    assert json.loads(body) == {"error": "internal_error"}
    assert b"secret-detail" not in body
    assert get_json(s, "/status")[0] == 200


def test_server_is_silent_on_stderr(ready, serve, monkeypatch, capfd):
    s = serve(ready)
    monkeypatch.setattr(ready, "status", lambda: (_ for _ in ()).throw(ValueError("x")))
    request(s, "GET", "/status")
    request(s, "GET", "/nope")
    request(s, "POST", "/status")
    out = capfd.readouterr()
    assert out.err == ""
    assert out.out == ""


def test_handler_has_timeout():
    from smart_health_record.server import _Handler

    assert 0 < _Handler.timeout <= 30
