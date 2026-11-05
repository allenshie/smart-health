"""評估規則測試（規格書第 3 節）：只測純函式，不涉及執行緒與時鐘。"""
import pytest

from smart_health_record.evaluator import (
    blocks_lane,
    evaluate_node,
    is_stuck,
    lane_blocked_nodes,
)
from smart_health_record.recorder import RecorderSnapshot
from smart_health_record.topology import LaneSpec, NodeSpec

STARTED = 1000.0


def spec(**kw):
    base = dict(
        id="n", label="N", lane="main", upstream=(), dependencies=(),
        stale_after_s=None, stuck_after_s=None, startup_grace_s=30.0,
        error_window_s=30.0, stale_reason="stale_success",
    )
    base.update(kw)
    return NodeSpec(**base)


def snap(**kw):
    base = dict(
        last_success_at=None, last_error_at=None, last_error_reason=None,
        last_error_message=None, in_progress_since=None, fatal_reason=None,
        fatal_message=None, metrics={},
    )
    base.update(kw)
    return RecorderSnapshot(**base)


def ev(s=None, sn=None, *, now=STARTED + 100, started_at=STARTED, enabled=True,
       dependencies=None, upstream_states=None, lane_blocked=False):
    return evaluate_node(
        s or spec(), sn or snap(), now=now, started_at=started_at, enabled=enabled,
        dependencies=dependencies or {}, upstream_states=upstream_states or {},
        lane_blocked=lane_blocked,
    )


def test_rule_1_disabled_over_fatal():
    sn = snap(fatal_reason="boom", fatal_message="x")
    assert ev(sn=sn, enabled=False) == ("disabled", "disabled", None)


def test_rule_2_fatal():
    sn = snap(fatal_reason="boom", fatal_message="壞了", last_success_at=STARTED + 99)
    assert ev(sn=sn) == ("unavailable", "boom", "壞了")


def test_rule_3_starting_within_grace():
    state, reason, message = ev(now=STARTED + 30)  # 邊界：<= grace 仍是 starting
    assert (state, reason) == ("waiting", "starting")
    assert message
    assert ev(now=STARTED + 30.001)[1] != "starting"


def test_rule_3_not_applied_after_success():
    sn = snap(last_success_at=STARTED + 1)
    assert ev(sn=sn, now=STARTED + 5)[1] is None


def test_rule_4_stuck():
    s = spec(stuck_after_s=10)
    sn = snap(in_progress_since=STARTED + 80, last_success_at=STARTED + 79)
    assert is_stuck(s, sn, STARTED + 90) is False  # 嚴格大於
    assert is_stuck(s, sn, STARTED + 90.5) is True
    state, reason, message = ev(s, sn, now=STARTED + 91)
    assert (state, reason) == ("unavailable", "stuck") and message
    assert is_stuck(spec(stuck_after_s=None), sn, STARTED + 1000) is False
    assert is_stuck(s, snap(), STARTED + 1000) is False


def test_rule_5_dependency_false_over_upstream():
    sn = snap(last_success_at=STARTED + 99)
    res = ev(spec(dependencies=("mqtt", "db")), sn,
             dependencies={"mqtt": True, "db": False},
             upstream_states={"u": "unavailable"}, lane_blocked=True)
    assert res == ("unavailable", "dependency_unavailable", "依賴 db 無法使用")


def test_rule_5_dependency_none_is_ignored():
    sn = snap(last_success_at=STARTED + 99)
    res = ev(spec(dependencies=("mqtt",)), sn, dependencies={"mqtt": None})
    assert res == ("ok", None, None)


def test_rule_6_lane_blocked():
    sn = snap(last_success_at=STARTED + 99)
    state, reason, message = ev(sn=sn, lane_blocked=True,
                                upstream_states={"u": "unavailable"})
    assert (state, reason) == ("waiting", "lane_blocked") and message


def lanes_fixture():
    return [
        LaneSpec("seq", "Seq", None, True, ("a", "b", "c")),
        LaneSpec("bg", "Bg", "a", False, ("w1", "w2")),
    ]


def test_rule_6_only_sequential_lanes():
    assert lane_blocked_nodes(lanes_fixture(), {"w1"}) == set()
    assert lane_blocked_nodes(lanes_fixture(), {"b"}) == {"a", "c"}
    assert lane_blocked_nodes(lanes_fixture(), set()) == set()


def test_rule_6_node_does_not_block_itself():
    assert "b" not in lane_blocked_nodes(lanes_fixture(), {"b"})


def test_blocks_lane_excludes_nodes_hitting_rules_1_to_3():
    s = spec(stuck_after_s=5)
    stuck_sn = snap(in_progress_since=STARTED + 10, last_success_at=STARTED + 1)
    kw = dict(now=STARTED + 100, started_at=STARTED)
    assert blocks_lane(s, stuck_sn, enabled=True, **kw) is True
    assert blocks_lane(s, stuck_sn, enabled=False, **kw) is False
    fatal = snap(in_progress_since=STARTED + 10, last_success_at=STARTED + 1,
                 fatal_reason="boom")
    assert blocks_lane(s, fatal, enabled=True, **kw) is False
    never = snap(in_progress_since=STARTED + 10)
    assert blocks_lane(s, never, enabled=True, now=STARTED + 20, started_at=STARTED) is False
    assert blocks_lane(s, never, enabled=True, **kw) is True
    assert blocks_lane(spec(), stuck_sn, enabled=True, **kw) is False


def test_rule_7_upstream_not_ready():
    sn = snap(last_success_at=STARTED + 99)
    for bad in ("waiting", "unavailable", "disabled"):
        state, reason, message = ev(sn=sn, upstream_states={"a": "ok", "b": bad})
        assert (state, reason) == ("waiting", "upstream_not_ready") and message


def test_rule_7_upstream_degraded_is_ready():
    sn = snap(last_success_at=STARTED + 99)
    assert ev(sn=sn, upstream_states={"a": "degraded", "b": "ok"}) == ("ok", None, None)


def test_rule_8_never_succeeded_after_grace():
    s = spec(stale_after_s=10)
    state, reason, message = ev(s)
    assert (state, reason) == ("unavailable", "never_succeeded") and message
    assert ev(spec(stale_after_s=None))[0] == "ok"


def test_rule_9_stale_uses_custom_reason():
    s = spec(stale_after_s=10, stale_reason="no_new_frame")
    sn = snap(last_success_at=STARTED + 80)
    assert ev(s, sn, now=STARTED + 90)[0] == "ok"  # 嚴格大於
    assert ev(s, sn, now=STARTED + 92.9) == (
        "unavailable", "no_new_frame", "已 12 秒沒有成功紀錄")
    assert ev(spec(stale_after_s=10), sn, now=STARTED + 95)[1] == "stale_success"


def test_rule_9_skipped_when_stale_after_none():
    sn = snap(last_success_at=STARTED + 1)
    assert ev(spec(stale_after_s=None), sn, now=STARTED + 5000) == ("ok", None, None)


def test_rule_10_recent_error_degraded():
    sn = snap(last_success_at=STARTED + 99, last_error_at=STARTED + 90,
              last_error_reason="decode_error", last_error_message="壞幀")
    assert ev(sn=sn, now=STARTED + 100) == ("degraded", "decode_error", "壞幀")
    assert ev(sn=sn, now=STARTED + 120)[0] == "degraded"  # 邊界：<= window


def test_rule_10_error_outside_window_is_ok():
    sn = snap(last_success_at=STARTED + 99, last_error_at=STARTED + 50,
              last_error_reason="decode_error")
    assert ev(sn=sn, now=STARTED + 80.001)[0] == "ok"


def test_rule_11_ok():
    assert ev(sn=snap(last_success_at=STARTED + 99)) == ("ok", None, None)
