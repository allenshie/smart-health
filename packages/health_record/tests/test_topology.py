"""架構驗證與 topology 測試（規格書 4.2、5.2）。"""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from smart_health_record import HealthMonitor

CONTRACT = Path(__file__).resolve().parents[3] / "contract"


def load(name):
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


def new(**kw):
    return HealthMonitor("edge", "CamA-northbound-1", **kw)


def test_duplicate_ids_raise():
    m = new()
    m.add_lane("main", "Main")
    with pytest.raises(ValueError):
        m.add_lane("main", "Again")
    m.add_node("a", "A", "main")
    with pytest.raises(ValueError):
        m.add_node("a", "A2", "main")


@pytest.mark.parametrize("bad", ["", "Main", "1a", "a b", "a.b", "_a", "a\n", None, 3])
def test_invalid_ids_raise(bad):
    m = new()
    with pytest.raises(ValueError):
        m.add_lane(bad, "x")
    m.add_lane("main", "Main")
    with pytest.raises(ValueError):
        m.add_node(bad, "x", "main")
    with pytest.raises(ValueError):
        m.add_node("ok", "x", "main", dependencies={bad: lambda: True})


@pytest.mark.parametrize("service,instance", [("Bad", "i"), ("", "i"), ("edge", ""), ("edge", None)])
def test_invalid_service_or_instance_raises(service, instance):
    with pytest.raises(ValueError):
        HealthMonitor(service, instance)


def test_instance_does_not_need_id_format():
    HealthMonitor("edge", "CamA northbound/1")


def test_unknown_lane_raises():
    m = new()
    with pytest.raises(ValueError):
        m.add_node("a", "A", "nope")


def test_unknown_upstream_raises_on_start():
    m = new()
    m.add_lane("main", "Main")
    m.add_node("a", "A", "main", upstream=["ghost"])
    with pytest.raises(ValueError):
        m.start()


def test_unknown_parent_raises_on_start():
    m = new()
    m.add_lane("main", "Main", parent="ghost")
    with pytest.raises(ValueError):
        m.start()


def test_forward_references_are_allowed():
    m = new()
    m.add_lane("main", "Main")
    m.add_node("a", "A", "main", upstream=["b"])
    m.add_node("b", "B", "main")
    m.evaluate_once()
    assert m.topology()["nodes"][0]["upstream"] == ["b"]


def test_upstream_cycle_raises():
    m = new()
    m.add_lane("main", "Main")
    m.add_node("a", "A", "main", upstream=["b"])
    m.add_node("b", "B", "main", upstream=["a"])
    with pytest.raises(ValueError):
        m.start()


def test_upstream_self_reference_raises():
    m = new()
    m.add_lane("main", "Main")
    m.add_node("a", "A", "main", upstream=["a"])
    with pytest.raises(ValueError):
        m.start()


def test_parent_cycle_raises():
    m = new()
    m.add_lane("l1", "L1", parent="n2")
    m.add_lane("l2", "L2", parent="n1")
    m.add_node("n1", "N1", "l1")
    m.add_node("n2", "N2", "l2")
    with pytest.raises(ValueError):
        m.start()


def test_parent_self_reference_raises():
    m = new()
    m.add_lane("l1", "L1", parent="n1")
    m.add_node("n1", "N1", "l1")
    with pytest.raises(ValueError):
        m.start()


def test_failed_start_does_not_mark_started():
    m = new()
    m.add_lane("main", "Main")
    m.add_node("a", "A", "main", upstream=["b"])
    with pytest.raises(ValueError):
        m.start()
    m.add_node("b", "B", "main")  # 修正後仍可新增並成功啟動
    m.start()
    m.stop()


def test_add_after_start_raises():
    m = new()
    m.add_lane("main", "Main")
    m.start()
    try:
        with pytest.raises(ValueError):
            m.add_lane("x", "X")
        with pytest.raises(ValueError):
            m.add_node("a", "A", "main")
    finally:
        m.stop()


@pytest.mark.parametrize("name,value", [
    ("stale_after_s", -1), ("stuck_after_s", -0.1), ("startup_grace_s", -1),
    ("error_window_s", -1), ("startup_grace_s", float("nan")),
    ("stale_after_s", float("nan")), ("error_window_s", "10"),
])
def test_invalid_numeric_node_params_raise(name, value):
    m = new()
    m.add_lane("main", "Main")
    with pytest.raises(ValueError):
        m.add_node("a", "A", "main", **{name: value})


@pytest.mark.parametrize("kw", [
    {"tick_interval_s": 0}, {"tick_interval_s": -1}, {"tick_interval_s": float("nan")},
    {"max_transitions": -1},
])
def test_invalid_monitor_params_raise(kw):
    with pytest.raises(ValueError):
        new(**kw)


def test_zero_values_are_allowed():
    m = new()
    m.add_lane("main", "Main")
    m.add_node("a", "A", "main", stale_after_s=0, stuck_after_s=0, startup_grace_s=0,
               error_window_s=0)


@pytest.mark.parametrize("reason", ["Bad", "1x", "has space", "", "a-b"])
def test_invalid_stale_reason_raises(reason):
    m = new()
    m.add_lane("main", "Main")
    with pytest.raises(ValueError):
        m.add_node("a", "A", "main", stale_reason=reason)


def test_topology_version_is_deterministic(edge_builder):
    a = edge_builder(new())
    b = edge_builder(new())
    a.start()
    b.start()
    try:
        assert a.topology()["topology_version"] == b.topology()["topology_version"]
    finally:
        a.stop()
        b.stop()
    c = new()
    c.add_lane("main", "Main")
    c.add_node("x", "X", "main")
    d = new()
    d.add_lane("main", "Main")
    d.add_node("y", "X", "main")
    c.evaluate_once()
    d.evaluate_once()
    assert c.topology()["topology_version"] != d.topology()["topology_version"]


def test_topology_matches_schema(edge_builder):
    m = edge_builder(new())
    m.evaluate_once()
    topo = m.topology()
    fixture = load("fixtures/topology_edge.json")
    assert topo == fixture
    schema = load("topology.schema.json")
    Draft202012Validator(schema).validate(topo)


def test_topology_returns_independent_copy(edge_builder):
    m = edge_builder(new())
    m.evaluate_once()
    first = m.topology()
    first["lanes"][0]["nodes"].append("hack")
    first["nodes"][0]["upstream"].append("hack")
    first["service"] = "hack"
    second = m.topology()
    assert "hack" not in second["lanes"][0]["nodes"]
    assert "hack" not in second["nodes"][0]["upstream"]
    assert second["service"] == "edge"
