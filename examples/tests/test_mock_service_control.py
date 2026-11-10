"""mock_service CLI、控制接口與帳密遮蔽。"""
import json
import socket
import sys

import pytest

from support import (MOCK_SERVICE_DIR, assert_holds, free_port, http_request,
                      wait_until)
from mock_service.scenarios import (EDGE_SCENARIOS, FAKE_SECRET)

FAST = dict(tick_interval_s=0.1, stuck_after_s=0.5, stale_after_s=3.0,
            startup_grace_s=30, error_window_s=30)


def test_initial_scenario_is_normal_and_post_get(mock_service):
    svc = mock_service("edge", **FAST)
    assert svc.scenario() == "normal"
    svc.set_scenario("messaging_down")
    assert svc.scenario() == "messaging_down"


def test_unknown_scenario_and_invalid_json_return_400(mock_service):
    svc = mock_service("edge", **FAST)
    url = f"{svc.control_url}/scenario"
    code, body = http_request(url, method="POST", body={"name": "no_such"})
    assert code == 400 and "error" in json.loads(body)
    code, body = http_request(url, method="POST", raw_body=b"{not json")
    assert code == 400 and "error" in json.loads(body)
    code, body = http_request(url, method="POST", body={"nom": "x"})
    assert code == 400 and "error" in json.loads(body)
    assert svc.scenario() == "normal"


def test_edge_scenario_list_has_all_12():
    assert len(set(EDGE_SCENARIOS)) == 12


@pytest.mark.parametrize("sig", ["SIGTERM", "SIGINT"])
def test_signal_exits_cleanly(mock_service, sig):
    import signal
    svc = mock_service("edge", **FAST)
    svc.proc.popen.send_signal(getattr(signal, sig))
    assert svc.proc.popen.wait(10) == 0


def test_bind_failure_exits_nonzero_with_reason(procs):
    import os
    port = free_port()
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", port))
        blocker.listen()
        proc = procs([sys.executable, "-m", "mock_service", "--profile", "edge",
                      "--instance", "x", "--host", "127.0.0.1", "--port", port,
                      "--control-port", free_port()], "bindfail",
                     dict(os.environ, PYTHONPATH=str(MOCK_SERVICE_DIR)))
        code = proc.popen.wait(10)
    assert code != 0
    assert str(port) in proc.output()


def test_stuck_must_be_smaller_than_stale(procs):
    import os
    proc = procs([sys.executable, "-m", "mock_service", "--profile", "edge",
                  "--instance", "x", "--host", "127.0.0.1", "--port", free_port(),
                  "--control-port", free_port(), "--stuck-after-s", "9",
                  "--stale-after-s", "5"], "badargs",
                 dict(os.environ, PYTHONPATH=str(MOCK_SERVICE_DIR)))
    assert proc.popen.wait(10) != 0


# (情境, 預期出現遮蔽字串的節點, 該節點此時的狀態)
CREDENTIAL_CASES = [
    ("read_errors", "ingest-worker", "degraded"),
    ("publish_errors", "publish", "degraded"),
    ("infer_exception", "infer", "degraded"),
    ("worker_fatal", "ingest-worker", "unavailable"),
]


@pytest.mark.parametrize("scenario,node,state", CREDENTIAL_CASES,
                         ids=[c[0] for c in CREDENTIAL_CASES])
def test_no_credentials_in_status_or_output(mock_service, scenario, node, state):
    svc = mock_service("edge", **FAST)
    svc.wait_states({n: "ok" for n in svc.states()})
    svc.set_scenario(scenario)

    def masked():
        entry = svc.status()["nodes"][node]
        return entry["state"] == state and "***" in (entry["message"] or "")

    wait_until(masked, what=f"{node} 帶有遮蔽後的錯誤訊息")
    _, text = http_request(f"{svc.url}/status")
    assert FAKE_SECRET not in text
    assert_holds(lambda: FAKE_SECRET not in http_request(f"{svc.url}/status")[1],
                 "status 不含帳密", reads=5)
    svc.proc.stop()
    assert FAKE_SECRET not in svc.proc.output()


@pytest.mark.parametrize("old", ["mqtt_down", "mediamtx_down", "camera_and_mqtt_down"])
def test_old_scenario_names_are_rejected(mock_service, old):
    svc = mock_service("edge", **FAST)
    code, body = http_request(f"{svc.control_url}/scenario", method="POST", body={"name": old})
    assert code == 400 and "error" in json.loads(body)
    assert svc.scenario() == "normal"
