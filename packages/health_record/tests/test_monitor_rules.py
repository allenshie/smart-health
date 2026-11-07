"""HealthMonitor 行為測試：整合規則（規格書 4.3、5.1、5.2）。

不使用 sleep 等待狀態：以 Event 同步，或以輪詢加上限時間。
共用工具在 monitor_support.py，fixture 在 conftest.py。
"""


# ---------------------------------------------------------------- 整合規則

def test_upstream_uses_same_round_results_in_topological_order(make):
    m = make()
    m.add_lane("main", "Main")
    ra = m.add_node("a", "A", "main", upstream=["b"], startup_grace_s=0)  # 前向參照
    rb = m.add_node("b", "B", "main", dependencies={"d": lambda: False}, startup_grace_s=0)
    ra.record_success()
    rb.record_success()
    m.evaluate_once()
    nodes = m.status()["nodes"]
    assert nodes["b"]["state"] == "unavailable"
    assert (nodes["a"]["state"], nodes["a"]["reason"]) == ("waiting", "upstream_not_ready")


def lane_monitor(make, **c_kw):
    m = make()
    m.add_lane("seq", "Seq", sequential=True)
    m.add_lane("bg", "Bg")
    recs = {
        "a": m.add_node("a", "A", "seq", startup_grace_s=0),
        "b": m.add_node("b", "B", "seq", stuck_after_s=5, startup_grace_s=0, **c_kw),
        "c": m.add_node("c", "C", "seq", startup_grace_s=0),
        "w": m.add_node("w", "W", "bg", startup_grace_s=0),
    }
    return m, recs


def test_lane_blocked_in_sequential_lane(make, clock):
    m, recs = lane_monitor(make)
    for r in recs.values():
        r.record_success()
    recs["b"].record_start()
    clock.advance(10)
    m.evaluate_once()
    nodes = m.status()["nodes"]
    assert (nodes["b"]["state"], nodes["b"]["reason"]) == ("unavailable", "stuck")
    for n in ("a", "c"):
        assert (nodes[n]["state"], nodes[n]["reason"]) == ("waiting", "lane_blocked")
    assert nodes["w"]["state"] == "ok"


def test_lane_not_blocked_by_disabled_fatal_or_starting_node(make, clock):
    flag = {"on": False}
    m, recs = lane_monitor(make, enabled=lambda: flag["on"])
    for r in recs.values():
        r.record_success()
    recs["b"].record_start()
    clock.advance(10)
    m.evaluate_once()  # b 已關閉
    nodes = m.status()["nodes"]
    assert nodes["b"]["state"] == "disabled" and nodes["a"]["state"] == "ok"
    flag["on"] = True
    recs["b"].set_fatal("boom", "x")
    m.evaluate_once()  # b 為 fatal
    nodes = m.status()["nodes"]
    assert nodes["b"]["reason"] == "boom" and nodes["a"]["state"] == "ok"


def test_lane_not_blocked_by_starting_node(make, clock):
    m = make()
    m.add_lane("seq", "Seq", sequential=True)
    ra = m.add_node("a", "A", "seq", startup_grace_s=0)
    rb = m.add_node("b", "B", "seq", stuck_after_s=1, startup_grace_s=30)
    ra.record_success()
    rb.record_start()  # 從未成功，仍在啟動寬限內
    clock.advance(10)
    m.evaluate_once()
    nodes = m.status()["nodes"]
    assert nodes["b"]["reason"] == "starting"
    assert nodes["a"]["state"] == "ok"
