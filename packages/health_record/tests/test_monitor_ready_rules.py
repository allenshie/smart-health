"""等待就緒的評估規則（規格書 3.1）：就緒前只判定 fatal；就緒後從就緒時刻起算。"""
import pytest

PRE_READY = ("waiting", "starting", "服務啟動中，尚未就緒")
RULE3 = ("waiting", "starting", "啟動中，尚未有成功紀錄")


def triple(m, node):
    n = m.status()["nodes"][node]
    return n["state"], n["reason"], n["message"]


def one_node(make, wait=True, **kw):
    m = make(wait_for_ready=wait)
    m.add_lane("main", "Main")
    return m, m.add_node("a", "A", "main", **kw)


# ---------------------------------------------------------------- 就緒之前

def test_before_ready_past_grace_is_still_starting(make, clock):
    m, _ = one_node(make, stale_after_s=5, startup_grace_s=5)
    m.start()
    clock.advance(100)
    m.evaluate_once()
    assert triple(m, "a") == PRE_READY


def test_before_ready_fatal_is_unavailable(make, clock):
    m, rec = one_node(make, stale_after_s=5)
    rec.set_fatal("camera_lost", "相機中斷")
    m.evaluate_once()
    assert triple(m, "a") == ("unavailable", "camera_lost", "相機中斷")


def _stuck(rec, clock):
    rec.record_start()
    clock.advance(100)


def _errors(rec, clock):
    rec.record_success()
    rec.record_error("read_error", "讀取失敗")


def _stale(rec, clock):
    rec.record_success()
    clock.advance(100)


@pytest.mark.parametrize("node_kw, act", [
    (dict(stuck_after_s=5, startup_grace_s=0), _stuck),
    (dict(startup_grace_s=0), _errors),
    (dict(stale_after_s=5, startup_grace_s=0), _stale),
    (dict(enabled=False), lambda rec, clock: rec.record_success()),
    (dict(dependencies={"messaging": lambda: False}, startup_grace_s=0),
     lambda rec, clock: rec.record_success()),
], ids=["stuck", "error_window", "stale", "disabled", "dependency"])
def test_before_ready_ignores_other_rules(make, clock, node_kw, act):
    m, rec = one_node(make, **node_kw)
    m.evaluate_once()
    act(rec, clock)
    m.evaluate_once()
    assert triple(m, "a") == PRE_READY


def test_before_ready_ignores_upstream_and_lane(make, clock):
    m = make(wait_for_ready=True)
    m.add_lane("seq", "Seq", sequential=True)
    a = m.add_node("a", "A", "seq", stuck_after_s=5, startup_grace_s=0)
    b = m.add_node("b", "B", "seq", upstream=["c"], startup_grace_s=0)
    c = m.add_node("c", "C", "seq", startup_grace_s=0)
    for r in (a, b, c):
        r.record_success()
    c.set_fatal("broken")
    a.record_start()
    clock.advance(100)
    m.evaluate_once()
    assert triple(m, "a") == PRE_READY  # 不判定 stuck
    assert triple(m, "b") == PRE_READY  # 不判定 lane_blocked、upstream_not_ready
    assert triple(m, "c")[:2] == ("unavailable", "broken")


def test_before_ready_does_not_call_enabled_or_dependencies(make, clock):
    calls = {"enabled": 0, "dep": 0}

    def enabled():
        calls["enabled"] += 1
        return True

    def dep():
        calls["dep"] += 1
        return True

    m, _ = one_node(make, enabled=enabled, dependencies={"messaging": dep})
    for _ in range(3):
        m.evaluate_once()
    assert calls == {"enabled": 0, "dep": 0}
    m.mark_ready()
    m.evaluate_once()
    assert calls == {"enabled": 1, "dep": 1}


def test_ready_is_reflected_on_next_round(make, clock):
    m, rec = one_node(make)
    rec.record_success()
    m.evaluate_once()
    m.mark_ready()
    assert triple(m, "a") == PRE_READY  # 不立即觸發評估
    m.evaluate_once()
    assert triple(m, "a") == ("ok", None, None)


def test_message_differs_before_and_after_ready(make, clock):
    m, _ = one_node(make, startup_grace_s=30)
    m.evaluate_once()
    before = triple(m, "a")
    m.mark_ready()
    m.evaluate_once()
    after = triple(m, "a")
    assert before == PRE_READY
    assert after == RULE3
    assert before[2] != after[2]


# ---------------------------------------------------------------- 就緒之後（wait_for_ready=True）

def test_startup_grace_counts_from_ready(make, clock):
    m, _ = one_node(make, stale_after_s=5, startup_grace_s=5)
    m.evaluate_once()
    clock.advance(100)
    m.mark_ready()
    m.evaluate_once()
    assert triple(m, "a") == RULE3
    clock.advance(5)
    m.evaluate_once()
    assert triple(m, "a") == RULE3  # 剛好等於寬限期：未超過
    clock.advance(0.5)
    m.evaluate_once()
    assert triple(m, "a")[:2] == ("unavailable", "never_succeeded")


def test_success_before_ready_counts_as_ever_succeeded(make, clock):
    m, rec = one_node(make, startup_grace_s=30)
    rec.record_success()
    clock.advance(100)
    m.evaluate_once()  # 隱含 start
    m.mark_ready()
    m.evaluate_once()
    assert triple(m, "a") == ("ok", None, None)


def test_stuck_counts_from_ready(make, clock):
    m = make(wait_for_ready=True)
    m.add_lane("seq", "Seq", sequential=True)
    a = m.add_node("a", "A", "seq", stuck_after_s=5, startup_grace_s=0)
    b = m.add_node("b", "B", "seq", startup_grace_s=0)
    a.record_success()
    b.record_success()
    a.record_start()
    clock.advance(100)
    m.evaluate_once()  # 隱含 start
    m.mark_ready()
    m.evaluate_once()
    assert triple(m, "a") == ("ok", None, None)
    assert triple(m, "b") == ("ok", None, None)
    clock.advance(5.5)
    m.evaluate_once()
    assert triple(m, "a")[:2] == ("unavailable", "stuck")
    assert triple(m, "b")[:2] == ("waiting", "lane_blocked")


def test_stale_counts_from_ready(make, clock):
    m, rec = one_node(make, stale_after_s=5, startup_grace_s=0, stale_reason="no_new_frame")
    rec.record_success()
    clock.advance(100)
    m.evaluate_once()  # 隱含 start
    m.mark_ready()
    m.evaluate_once()
    assert triple(m, "a") == ("ok", None, None)
    clock.advance(6.5)
    m.evaluate_once()
    assert triple(m, "a") == ("unavailable", "no_new_frame", "已 6 秒沒有成功紀錄")


def test_stale_uses_success_after_ready(make, clock):
    m, rec = one_node(make, stale_after_s=5, startup_grace_s=0)
    rec.record_success()
    m.evaluate_once()  # 隱含 start
    m.mark_ready()
    clock.advance(3)
    rec.record_success()  # 晚於就緒時刻：以這次成功起算
    clock.advance(4)
    m.evaluate_once()
    assert triple(m, "a") == ("ok", None, None)
    clock.advance(1.5)
    m.evaluate_once()
    assert triple(m, "a") == ("unavailable", "stale_success", "已 5 秒沒有成功紀錄")


def test_error_before_ready_is_ignored(make, clock):
    m, rec = one_node(make, startup_grace_s=0)
    rec.record_success()
    rec.record_error("read_error")
    clock.advance(1)
    m.evaluate_once()  # 隱含 start
    m.mark_ready()
    m.evaluate_once()
    assert triple(m, "a") == ("ok", None, None)


def test_error_at_ready_time_counts(make, clock):
    m, rec = one_node(make, startup_grace_s=0)
    rec.record_success()
    m.evaluate_once()  # 隱含 start
    m.mark_ready()
    rec.record_error("read_error", "讀取失敗")  # 和就緒時刻相同
    m.evaluate_once()
    assert triple(m, "a") == ("degraded", "read_error", "讀取失敗")


def test_error_after_ready_counts(make, clock):
    m, rec = one_node(make, startup_grace_s=0)
    rec.record_success()
    m.evaluate_once()  # 隱含 start
    m.mark_ready()
    clock.advance(1)
    rec.record_error("read_error")
    m.evaluate_once()
    assert triple(m, "a")[:2] == ("degraded", "read_error")


# ---------------------------------------------------------------- 相容性（wait_for_ready=False）

def test_without_wait_events_before_start_keep_v14_formulas(make, clock):
    """False 時不取較晚時間：start() 前的事件照 v1.4 計算。"""
    m = make()
    m.add_lane("main", "Main")
    stale = m.add_node("stale", "S", "main", stale_after_s=5, startup_grace_s=0)
    stuck = m.add_node("stuck", "K", "main", stuck_after_s=5, startup_grace_s=0)
    err = m.add_node("err", "E", "main", startup_grace_s=0, error_window_s=200)
    for r in (stale, stuck, err):
        r.record_success()
    stuck.record_start()
    err.record_error("read_error")
    clock.advance(100)
    m.evaluate_once()  # 隱含 start：start() 晚於上面所有事件
    assert triple(m, "stale") == ("unavailable", "stale_success", "已 100 秒沒有成功紀錄")
    assert triple(m, "stuck")[:2] == ("unavailable", "stuck")
    assert triple(m, "err")[:2] == ("degraded", "read_error")
