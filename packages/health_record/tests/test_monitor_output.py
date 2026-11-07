"""HealthMonitor 行為測試：基本輸出（規格書 4.3、5.1、5.2）。

不使用 sleep 等待狀態：以 Event 同步，或以輪詢加上限時間。
共用工具在 monitor_support.py，fixture 在 conftest.py。
"""

from monitor_support import (
    simple,
    status_validator,
)


# ---------------------------------------------------------------- 基本輸出

def test_status_matches_schema(make, edge_builder, clock):
    m = edge_builder(make())
    m.evaluate_once()
    st = m.status()
    status_validator().validate(st)
    assert st["topology_version"] == m.topology()["topology_version"]
    assert set(st["nodes"]) == {"ingest-worker", "ingest", "infer", "stream",
                                "stream-output", "publish"}
    assert st["evaluated_at"] is not None


def test_status_returns_independent_copy(make):
    m = make("other")
    rec = simple(m)
    rec.set_metric("fps", 1.0)
    m.evaluate_once()
    first = m.status()
    first["nodes"]["a"]["metrics"]["fps"] = 999
    first["nodes"]["a"]["state"] = "hack"
    first["recent_transitions"].clear()
    second = m.status()
    assert second["nodes"]["a"]["metrics"]["fps"] == 1.0
    assert second["nodes"]["a"]["state"] != "hack"
    assert len(second["recent_transitions"]) == 1


def test_timestamps_use_millisecond_isoformat(make, wall):
    m = make()
    simple(m)
    m.evaluate_once()
    st = m.status()
    assert st["started_at"] == "2026-11-05T10:00:00.000+08:00"
    assert st["evaluated_at"] == "2026-11-05T10:00:00.000+08:00"
    assert st["nodes"]["a"]["since"] == "2026-11-05T10:00:00.000+08:00"


def test_since_only_changes_on_state_change(make, wall):
    m = make()
    rec = simple(m, startup_grace_s=0)
    rec.record_success()
    m.evaluate_once()
    t0 = m.status()["nodes"]["a"]["since"]
    wall.advance(5)
    rec.record_error("first_problem", "m1")
    m.evaluate_once()
    st = m.status()
    assert st["nodes"]["a"]["state"] == "degraded"
    t1 = st["nodes"]["a"]["since"]
    assert t1 != t0
    wall.advance(5)
    rec.record_error("second_problem", "m2")
    m.evaluate_once()
    st = m.status()
    node = st["nodes"]["a"]
    assert (node["state"], node["reason"], node["message"]) == ("degraded", "second_problem", "m2")
    assert node["since"] == t1
    assert [t["to"] for t in st["recent_transitions"]] == ["degraded", "ok"]


def test_first_evaluation_recorded_as_transition(make):
    m = make()
    rec = simple(m, startup_grace_s=0)
    rec.record_success()
    m.evaluate_once()
    st = m.status()
    assert st["recent_transitions"] == [
        {"node": "a", "from": None, "to": "ok", "reason": None,
         "at": "2026-11-05T10:00:00.000+08:00"}]


def test_recent_transitions_newest_first_limited_to_50(make, wall):
    flag = {"on": True}
    m = make()
    simple(m, enabled=lambda: flag["on"], startup_grace_s=0)
    for i in range(60):
        flag["on"] = (i % 2 == 0)
        wall.advance(1)
        m.evaluate_once()
    trans = m.status()["recent_transitions"]
    assert len(trans) == 50
    ats = [t["at"] for t in trans]
    assert ats == sorted(ats, reverse=True)
    assert trans[0]["to"] == "disabled"  # 最後一輪（i=59，奇數）為關閉
    status_validator().validate(m.status())


def test_max_transitions_bounds_history(make, wall):
    flag = {"on": True}
    m = make(max_transitions=3)
    simple(m, enabled=lambda: flag["on"])
    for i in range(10):
        flag["on"] = (i % 2 == 0)
        wall.advance(1)
        m.evaluate_once()
    assert len(m.status()["recent_transitions"]) == 3
