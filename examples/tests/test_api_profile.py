"""api 模擬服務：通用性驗證（非 Edge 命名、多依賴、多上游、巢狀 lane、閒置仍為 ok）。"""
import json

import pytest

from support import FIXTURES, assert_holds, wait_until

NODES = ["gateway", "handler", "response", "job-runner", "cache-warmer", "batch-export"]
CODE = {"G": "ok", "R": "unavailable", "W": "waiting"}

# stale_after_s 全為 None，閒置不記錄成功也要 ok；grace 縮短避免等待
FAST = dict(tick_interval_s=0.1, startup_grace_s=0.5)

API_TABLE = [
    ("normal",             "G G G G G G"),
    ("database_down",      "G R W R G W"),
    ("cache_down",         "G R W W R W"),
    ("gateway_fatal",      "R W W W G W"),
    ("cache_warmer_fatal", "G W W W R W"),
    ("job_runner_fatal",   "G G G R G W"),
]


def expected(row):
    return {n: CODE[c] for n, c in zip(NODES, row.split())}


ALL_OK = expected("G G G G G G")


def start(mock_service):
    svc = mock_service("api", instance="api-1", **FAST)
    svc.wait_states(ALL_OK)
    return svc


def test_idle_node_stays_ok(mock_service):
    svc = start(mock_service)
    # 沒有任何成功紀錄，且超過 grace 很久，仍然是 ok 而非 never_succeeded
    assert_holds(lambda: svc.states() == ALL_OK, "閒置維持 ok", reads=15, gap=0.1)
    assert set(svc.reasons().values()) == {None}


@pytest.mark.parametrize("name,row", API_TABLE, ids=[r[0] for r in API_TABLE])
def test_api_scenario_states(mock_service, name, row):
    svc = start(mock_service)
    svc.set_scenario(name)
    svc.wait_states(expected(row))
    assert_holds(lambda: svc.states() == expected(row), f"{name} 維持")
    svc.set_scenario("normal")  # 恢復後全部回到 ok
    svc.wait_states(ALL_OK)


@pytest.mark.parametrize("scenario,down", [("database_down", {"handler", "job-runner"}),
                                           ("cache_down", {"handler", "cache-warmer"})])
def test_any_dependency_down_is_unavailable(mock_service, scenario, down):
    svc = start(mock_service)
    svc.set_scenario(scenario)
    wait_until(lambda: {n for n, s in svc.states().items() if s == "unavailable"} == down,
               what="依賴失效節點")
    assert {svc.reasons()[n] for n in down} == {"dependency_unavailable"}
    assert_holds(lambda: {n for n, s in svc.states().items() if s == "unavailable"} == down,
                 "依賴失效維持")


# (情境, 受影響節點, 不就緒的上游, 仍就緒的上游)
MULTI_UPSTREAM = [
    ("gateway_fatal", "handler", "gateway", "cache-warmer"),
    ("cache_warmer_fatal", "handler", "cache-warmer", "gateway"),
    ("job_runner_fatal", "batch-export", "job-runner", "cache-warmer"),
]


@pytest.mark.parametrize("scenario,node,bad,good", MULTI_UPSTREAM,
                         ids=[f"{m[1]}-{m[2]}" for m in MULTI_UPSTREAM])
def test_multiple_upstreams_require_all_ready(mock_service, scenario, node, bad, good):
    svc = start(mock_service)
    svc.set_scenario(scenario)

    def cond():
        states = svc.states()
        return (states[bad] == "unavailable" and states[good] == "ok"
                and states[node] == "waiting")

    wait_until(cond, what=f"{node} 因 {bad} waiting（{good} 仍 ok）")
    assert_holds(cond, "多上游維持")
    assert svc.reasons()[node] == "upstream_not_ready"


def test_nested_lane_in_topology(mock_service):
    svc = mock_service("api", instance="api-1", **FAST)
    fixture = json.loads((FIXTURES / "topology_api.json").read_text(encoding="utf-8"))
    topo = svc.topology()
    assert topo["service"] == "api"
    assert topo["lanes"] == fixture["lanes"]
    assert topo["nodes"] == fixture["nodes"]
    assert topo["topology_version"] == fixture["topology_version"]
    lanes = {lane["id"]: lane for lane in topo["lanes"]}
    # batch 掛在 workers 內的 job-runner 底下，workers 又掛在 handler 底下
    assert lanes["batch"]["parent"] == "job-runner"
    assert "job-runner" in lanes["workers"]["nodes"]
    assert lanes["workers"]["parent"] == "handler"
    assert svc.status()["topology_version"] == fixture["topology_version"]
