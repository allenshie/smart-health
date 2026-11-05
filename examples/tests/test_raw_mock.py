"""raw_mock：故意回傳不符合契約內容，驗證每個模式確實出現預期行為。"""
import json
import socket
import time
import urllib.error

import pytest
from jsonschema import Draft202012Validator

from support import SCHEMAS, get_json, http_request, wait_until

MODES = ["hang", "http_500", "invalid_json", "wrong_schema", "missing_nodes",
         "topology_change", "evaluation_stale"]


def _validator(name):
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


TOPOLOGY, STATUS = _validator("topology.schema.json"), _validator("status.schema.json")


def test_hang_never_responds(raw_mock):
    mock = raw_mock("hang")
    for path in ("/topology", "/status"):
        with pytest.raises((TimeoutError, socket.timeout, urllib.error.URLError)):
            http_request(f"{mock.url}{path}", timeout=1.0)


def test_http_500(raw_mock):
    mock = raw_mock("http_500")
    for path in ("/topology", "/status"):
        assert http_request(f"{mock.url}{path}")[0] == 500


def test_invalid_json(raw_mock):
    mock = raw_mock("invalid_json")
    for path in ("/topology", "/status"):
        code, text = http_request(f"{mock.url}{path}")
        assert code == 200
        with pytest.raises(ValueError):
            json.loads(text)


def test_wrong_schema(raw_mock):
    mock = raw_mock("wrong_schema")
    for path in ("/topology", "/status"):
        code, body = get_json(f"{mock.url}{path}")
        assert code == 200 and body["schema_version"] == 999


def test_missing_nodes(raw_mock):
    mock = raw_mock("missing_nodes")
    _, topo = get_json(f"{mock.url}/topology")
    _, status = get_json(f"{mock.url}/status")
    assert not list(TOPOLOGY.iter_errors(topo))
    assert not list(STATUS.iter_errors(status))  # 連線視為正常，契約合法
    ids = {n["id"] for n in topo["nodes"]}
    assert set(status["nodes"]) < ids and status["nodes"]
    assert all(v["state"] == "ok" for v in status["nodes"].values())
    assert status["topology_version"] == topo["topology_version"]


def test_topology_change(raw_mock):
    mock = raw_mock("topology_change", change_interval_s=0.5)
    seen = {}

    def changed():
        _, topo = get_json(f"{mock.url}/topology")
        _, status = get_json(f"{mock.url}/status")
        assert not list(TOPOLOGY.iter_errors(topo))
        assert not list(STATUS.iter_errors(status))
        if status["topology_version"] == topo["topology_version"]:  # 邊界可能剛好切換
            assert set(status["nodes"]) == {n["id"] for n in topo["nodes"]}
        seen[topo["topology_version"]] = {n["id"] for n in topo["nodes"]}
        return len(seen) >= 2

    wait_until(changed, 10.0, what="topology_version 改變")
    assert len({frozenset(v) for v in seen.values()}) == len(seen)  # 節點內容也不同


def test_evaluation_stale(raw_mock):
    mock = raw_mock("evaluation_stale")
    _, status = get_json(f"{mock.url}/status")
    assert not list(STATUS.iter_errors(status))
    assert status["evaluation_age_s"] >= 60
    _, topo = get_json(f"{mock.url}/topology")
    assert not list(TOPOLOGY.iter_errors(topo))
    assert topo["topology_version"] == status["topology_version"]


@pytest.mark.parametrize("mode", [m for m in MODES if m not in ("hang", "http_500",
                                                                "invalid_json", "wrong_schema")])
def test_valid_modes_pass_schema(raw_mock, mode):
    mock = raw_mock(mode)
    _, topo = get_json(f"{mock.url}/topology")
    assert not list(TOPOLOGY.iter_errors(topo))


@pytest.mark.parametrize("sig", ["SIGTERM", "SIGINT"])
@pytest.mark.parametrize("mode", MODES)
def test_signal_exits_cleanly(raw_mock, mode, sig):
    import signal
    mock = raw_mock(mode)
    held = None
    if mode == "hang":  # 保持一條懸而未決的連線，仍須能乾淨結束
        held = socket.create_connection(("127.0.0.1", mock.port), timeout=2)
        held.sendall(b"GET /status HTTP/1.1\r\nHost: x\r\n\r\n")
        time.sleep(0.2)
    try:
        mock.proc.popen.send_signal(getattr(signal, sig))
        assert mock.proc.popen.wait(10) == 0
    finally:
        if held is not None:
            held.close()
