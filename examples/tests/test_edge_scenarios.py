"""edge 模擬服務：規格書 8.2 的 14 個情境與 starting 重建行為。"""
import json
import threading

import pytest

from support import FIXTURES, assert_holds, get_json, wait_until

NODES = ["ingest-worker", "ingest", "infer", "stream", "stream-output", "publish"]
CODE = {"G": "ok", "Y": "degraded", "R": "unavailable", "灰": "waiting", "D": "disabled"}

# 規格書 8.2 的情境表，逐字轉成資料（順序同 NODES）
SCENARIO_TABLE = [
    ("normal",               "G G G G G G"),
    ("starting",             "灰 灰 灰 灰 灰 灰"),
    ("camera_down",          "R 灰 灰 灰 灰 灰"),
    ("messaging_down",       "G G G G G R"),
    ("stream_sink_down",     "G G G G R G"),
    ("infer_stuck",          "G 灰 R 灰 灰 灰"),
    ("infer_exception",      "G G R 灰 灰 灰"),
    ("camera_and_messaging_down", "R 灰 灰 灰 灰 R"),
    ("read_errors",          "Y G G G G G"),
    ("publish_errors",       "G G G G G Y"),
    ("worker_fatal",         "R 灰 灰 灰 灰 灰"),
    ("stream_disabled",      "G G G D D G"),
    ("loading",              "灰 灰 灰 灰 灰 灰"),
    ("loading_fatal",        "R 灰 灰 灰 灰 灰"),
]

FAST = dict(tick_interval_s=0.1, stuck_after_s=0.5, stale_after_s=2.0,
            startup_grace_s=30, error_window_s=30)


def expected_states(row):
    return {n: CODE[c] for n, c in zip(NODES, row.split())}


ALL_OK = {n: "ok" for n in NODES}


def test_table_has_all_14_rows():
    assert len(SCENARIO_TABLE) == 14


@pytest.mark.parametrize("name,row", SCENARIO_TABLE, ids=[r[0] for r in SCENARIO_TABLE])
def test_scenario_states(mock_service, name, row):
    svc = mock_service("edge", **FAST)
    svc.wait_states(ALL_OK)
    svc.set_scenario(name)
    expected = expected_states(row)
    svc.wait_states(expected)
    assert_holds(lambda: svc.states() == expected, f"{name} 狀態維持 {expected}")


def test_infer_exception_degraded_then_unavailable(mock_service):
    svc = mock_service("edge", **dict(FAST, stale_after_s=3.0))
    svc.wait_states(ALL_OK)
    svc.set_scenario("infer_exception")
    # 超過 stale 門檻前：有紀錄過成功，錯誤在窗口內 -> degraded
    wait_until(lambda: svc.states()["infer"] == "degraded", 10.0, what="infer degraded")
    assert svc.reasons()["infer"] == "exception"
    # 超過門檻後：stale -> unavailable，後面的節點因上游而 waiting
    expected = expected_states(dict(SCENARIO_TABLE)["infer_exception"])
    svc.wait_states(expected)
    assert svc.reasons()["infer"] == "stale_success"
    assert_holds(lambda: svc.states() == expected, "infer_exception 維持 R")


def test_starting_rebuilds_monitor_and_server(mock_service):
    svc = mock_service("edge", **FAST)
    svc.wait_states(ALL_OK)
    before = svc.status()["started_at"]
    svc.set_scenario("starting")

    def rebuilt():
        status = svc.status()
        return status["started_at"] != before and len(status["nodes"]) == 6

    wait_until(rebuilt, 15.0, what="重建完成")
    waiting = {n: "waiting" for n in NODES}
    assert_holds(lambda: svc.states() == waiting, "starting 全部 waiting")
    assert set(svc.reasons().values()) == {"starting"}
    new_started = svc.status()["started_at"]
    assert new_started != before


def test_scenarios_after_starting_do_not_rebuild_but_starting_again_does(mock_service):
    svc = mock_service("edge", **FAST)
    svc.wait_states(ALL_OK)
    svc.set_scenario("starting")
    wait_until(lambda: svc.states() == {n: "waiting" for n in NODES}, 15.0, what="starting")
    started = svc.status()["started_at"]
    svc.set_scenario("normal")
    svc.wait_states(ALL_OK)
    assert svc.status()["started_at"] == started
    svc.set_scenario("messaging_down")
    svc.wait_states(expected_states("G G G G G R"))
    assert svc.status()["started_at"] == started
    svc.set_scenario("starting")
    wait_until(lambda: svc.status()["started_at"] != started, 15.0, what="再次重建")


def test_infer_stuck_does_not_block_rebuild_or_exit(mock_service):
    svc = mock_service("edge", **FAST)
    svc.wait_states(ALL_OK)
    svc.set_scenario("infer_stuck")
    svc.wait_states(expected_states("G 灰 R 灰 灰 灰"))
    before = svc.status()["started_at"]
    svc.set_scenario("starting")
    wait_until(lambda: svc.status()["started_at"] != before, 15.0, what="stuck 中重建")
    svc.set_scenario("infer_stuck")
    svc.set_scenario("normal")
    svc.wait_states(ALL_OK)


def test_control_port_stays_available_during_rebuild(mock_service):
    svc = mock_service("edge", **FAST)
    svc.wait_states(ALL_OK)
    before = svc.status()["started_at"]
    results, stop = [], threading.Event()

    def hammer():
        while not stop.is_set():
            try:
                code, body = get_json(f"{svc.control_url}/scenario", timeout=2.0)
                results.append(code == 200 and "name" in body)
            except Exception:  # noqa: BLE001
                results.append(False)

    thread = threading.Thread(target=hammer)
    thread.start()
    try:
        for _ in range(2):
            svc.set_scenario("starting")
            svc.set_scenario("normal")
        wait_until(lambda: svc.status()["started_at"] != before, 15.0, what="重建")
        svc.wait_states(ALL_OK)
    finally:
        stop.set()
        thread.join()
    assert len(results) > 20
    assert all(results), f"{results.count(False)} 次控制接口請求失敗"
    assert svc.scenario() == "normal"


def test_edge_topology_matches_fixture(mock_service):
    svc = mock_service("edge", instance="CamA-northbound-1", **FAST)
    fixture = json.loads((FIXTURES / "topology_edge.json").read_text(encoding="utf-8"))
    topo = svc.topology()
    assert topo["service"] == "edge"
    assert topo["lanes"] == fixture["lanes"]
    assert topo["nodes"] == fixture["nodes"]
    assert topo["topology_version"] == fixture["topology_version"]
    assert svc.status()["topology_version"] == fixture["topology_version"]


@pytest.mark.parametrize("name,node,message", [
    ("messaging_down", "publish", "依賴 messaging 無法使用"),
    ("stream_sink_down", "stream-output", "依賴 stream_sink 無法使用"),
])
def test_dependency_message_uses_role_name(mock_service, name, node, message):
    svc = mock_service("edge", **FAST)
    svc.wait_states(ALL_OK)
    svc.set_scenario(name)
    wait_until(lambda: svc.status()["nodes"][node]["state"] == "unavailable", 10.0,
               what=f"{node} unavailable")
    got = svc.status()["nodes"][node]
    assert (got["reason"], got["message"]) == ("dependency_unavailable", message)
