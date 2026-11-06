from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timedelta, timezone

import pytest
from support import make_config

from smart_health_backend.contract import parse_status, parse_topology
from smart_health_backend.store import TargetStore

NOW = datetime(2026, 11, 6, 12, 0, 0, 123456, tzinfo=timezone(timedelta(hours=8)))


def transition(node, to, at, frm="ok", reason="r"):
    return {"node": node, "from": frm, "to": to, "reason": reason, "at": at}


def at(n: int) -> str:
    return f"2026-11-05T10:00:{n:02d}+08:00"


def make_store(history: int = 200):
    return TargetStore(make_config(["t1"], history=history), clock=lambda: NOW)


def feed(store, topology, status, connection="online"):
    store.set_topology("t1", parse_topology(json.dumps(topology)))
    store.apply_status("t1", parse_status(json.dumps(status)), connection)


def with_transitions(status, transitions):
    status = copy.deepcopy(status)
    status["recent_transitions"] = transitions
    return status


def keys(store, limit=500):
    return [(t.node, t.at, t.to) for t in store.get_transitions("t1", limit)]


def test_transitions_deduplicated(topology_edge, status_edge):
    store = make_store()
    feed(store, topology_edge, status_edge)
    first = keys(store)
    assert len(first) == 6
    # 同一份回應再收一次，不會重複
    store.apply_status("t1", parse_status(json.dumps(status_edge)), "online")
    assert keys(store) == first
    # 新增一筆：放最前面，其餘不變
    newer = with_transitions(
        status_edge,
        [transition("infer", "ok", at(30), frm="waiting")] + status_edge["recent_transitions"],
    )
    store.apply_status("t1", parse_status(json.dumps(newer)), "online")
    assert keys(store) == [("infer", at(30), "ok")] + first


def test_transitions_order_follows_arrival_not_at(topology_edge, status_edge):
    store = make_store()
    feed(store, topology_edge, with_transitions(status_edge, [transition("infer", "ok", at(50))]))
    # 後到的批次，即使對方時鐘的 at 較早，仍排在最前面
    older = with_transitions(status_edge, [transition("stream", "ok", at(1))])
    store.apply_status("t1", parse_status(json.dumps(older)), "online")
    assert keys(store) == [("stream", at(1), "ok"), ("infer", at(50), "ok")]


def test_transitions_limited(topology_edge, status_edge):
    store = make_store(history=3)
    batch = [transition("infer", "ok", at(n)) for n in (9, 8, 7, 6, 5)]
    feed(store, topology_edge, with_transitions(status_edge, batch))
    assert keys(store) == [("infer", at(9), "ok"), ("infer", at(8), "ok"), ("infer", at(7), "ok")]
    assert len(store.get_transitions("t1", 2)) == 2
    assert store.get_transitions("t1", 1)[0].at == at(9)


def test_history_limit_below_50_does_not_readd_evicted(topology_edge, status_edge):
    store = make_store(history=2)
    batch = [transition("infer", "ok", at(n)) for n in (3, 2, 1)]
    feed(store, topology_edge, with_transitions(status_edge, batch))
    assert keys(store) == [("infer", at(3), "ok"), ("infer", at(2), "ok")]
    # 被淘汰的 at(1) 仍在服務回應中，不能再加入
    store.apply_status("t1", parse_status(json.dumps(with_transitions(status_edge, batch))), "online")
    assert keys(store) == [("infer", at(3), "ok"), ("infer", at(2), "ok")]
    # 新的一筆進來；回應仍含舊的三筆，已淘汰的 at(1) 仍不可回來
    newer = [transition("infer", "ok", at(4))] + batch
    store.apply_status("t1", parse_status(json.dumps(with_transitions(status_edge, newer))), "online")
    assert keys(store) == [("infer", at(4), "ok"), ("infer", at(3), "ok")]
    store.apply_status("t1", parse_status(json.dumps(with_transitions(status_edge, newer))), "online")
    assert keys(store) == [("infer", at(4), "ok"), ("infer", at(3), "ok")]


def test_transitions_for_unknown_nodes_not_recorded(topology_edge, status_edge):
    store = make_store()
    batch = [transition("ghost", "ok", at(5)), transition("infer", "ok", at(4))]
    feed(store, topology_edge, with_transitions(status_edge, batch))
    assert keys(store) == [("infer", at(4), "ok")]


def test_transitions_not_recorded_when_not_validated(topology_edge, status_edge):
    store = make_store()
    store.set_topology("t1", parse_topology(json.dumps(topology_edge)))
    store.apply_failure("t1", "offline")
    assert keys(store) == []


def test_stale_status_transitions_are_recorded(topology_edge, status_edge):
    store = make_store()
    feed(store, topology_edge, status_edge, connection="stale")
    assert len(keys(store)) == 6


def test_unknown_target(topology_edge):
    store = make_store()
    assert store.get_transitions("nope", 5) is None
    assert store.get_view("nope") is None


def test_summaries_before_first_poll():
    store = make_store()
    (summary,) = store.list_views()
    assert summary.connection == "unknown"
    assert summary.summary_color == "gray"
    assert summary.last_success_at is None
    detail = store.get_view("t1")
    assert detail.topology is None
    assert detail.nodes == {}
    assert store.get_transitions("t1", 10) == []


def test_missing_node_is_gray_status_missing(topology_edge, status_edge):
    status = copy.deepcopy(status_edge)
    del status["nodes"]["publish"]
    store = make_store()
    feed(store, topology_edge, status)
    view = store.get_view("t1")
    node = view.nodes["publish"]
    assert (node.state, node.message, node.since) == (None, None, None)
    assert node.metrics == {}
    assert node.reason == "status_missing"
    assert node.color == "gray"
    assert view.nodes["ingest-worker"].color == "red"
    assert list(view.nodes) == [n["id"] for n in topology_edge["nodes"]]


def test_extra_status_node_ignored(topology_edge, status_edge, caplog):
    status = copy.deepcopy(status_edge)
    status["nodes"]["ghost"] = copy.deepcopy(status["nodes"]["ingest"])
    store = make_store()
    with caplog.at_level(logging.INFO, logger="smart_health_backend"):
        feed(store, topology_edge, status)
        store.apply_status("t1", parse_status(json.dumps(status)), "online")
        store.apply_status("t1", parse_status(json.dumps(status)), "online")
    view = store.get_view("t1")
    assert "ghost" not in view.nodes
    assert set(view.nodes) == {n["id"] for n in topology_edge["nodes"]}
    # 同一組多出的節點只記一次 log
    assert sum("ghost" in r.getMessage() for r in caplog.records) == 1


def test_online_summary_and_last_success_at(topology_edge, status_edge):
    store = make_store()
    feed(store, topology_edge, status_edge)
    (summary,) = store.list_views()
    assert summary.connection == "online"
    assert summary.summary_color == "red"
    assert summary.last_success_at == "2026-11-06T12:00:00.123+08:00"
    detail = store.get_view("t1")
    assert detail.topology.service == "edge"
    assert detail.topology.topology_version == topology_edge["topology_version"]
    dumped = detail.model_dump_json()
    assert "base_url" not in dumped
    assert "http://" not in dumped


def test_stale_does_not_update_last_success_and_is_gray(topology_edge, status_edge):
    store = make_store()
    feed(store, topology_edge, status_edge)
    later = NOW + timedelta(seconds=30)
    store._clock = lambda: later
    store.apply_status("t1", parse_status(json.dumps(status_edge)), "stale")
    view = store.get_view("t1")
    assert view.connection == "stale"
    assert view.summary_color == "gray"
    assert view.last_success_at == "2026-11-06T12:00:00.123+08:00"
    assert all(n.color == "gray" and n.reason == "stale" for n in view.nodes.values())


def test_transition_serializes_from_alias(topology_edge, status_edge):
    store = make_store()
    feed(store, topology_edge, status_edge)
    data = json.loads(store.get_transitions("t1", 1)[0].model_dump_json(by_alias=True))
    assert set(data) == {"node", "from", "to", "reason", "at"}


@pytest.mark.parametrize("connection", ["offline", "invalid_response", "incompatible"])
def test_failure_keeps_structure_and_grays_nodes(topology_edge, status_edge, connection):
    store = make_store()
    feed(store, topology_edge, status_edge)
    store.apply_failure("t1", connection)
    view = store.get_view("t1")
    assert view.connection == connection
    assert view.topology is not None
    assert all(n.reason == connection and n.color == "gray" for n in view.nodes.values())


def test_transition_models_are_frozen(topology_edge, status_edge):
    store = make_store()
    feed(store, topology_edge, status_edge)
    item = store.get_transitions("t1", 1)[0]
    with pytest.raises(Exception):
        item.to = "ok"
    view = store.get_view("t1")
    with pytest.raises(Exception):
        view.connection = "x"
    with pytest.raises(Exception):
        next(iter(view.nodes.values())).color = "x"


@pytest.mark.parametrize("limit", [0, -1])
def test_get_transitions_rejects_limit_below_one(limit):
    store = make_store()
    with pytest.raises(ValueError):
        store.get_transitions("t1", limit)
