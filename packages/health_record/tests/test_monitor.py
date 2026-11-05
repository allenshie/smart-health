"""HealthMonitor 行為測試（規格書 4.3、5.1、5.2）。

不使用 sleep 等待狀態：以 Event 同步，或以輪詢加上限時間。
"""
import copy
import json
import logging
import threading
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from smart_health_record import HealthMonitor

CONTRACT = Path(__file__).resolve().parents[3] / "contract"
WAIT_S = 5.0


def load(name):
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


def wait_until(pred, timeout=WAIT_S):
    gate = threading.Event()
    waited = 0.0
    while not pred():
        if waited >= timeout:
            raise AssertionError("條件在時限內未成立")
        gate.wait(0.005)
        waited += 0.005
    return True


def call_with_timeout(fn, timeout=WAIT_S):
    """在另一條執行緒呼叫 fn，逾時代表被卡住。"""
    box = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - 轉交給測試主執行緒
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    assert not t.is_alive(), "呼叫被卡住"
    if "error" in box:
        raise box["error"]
    return box["value"]


class Records(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def texts(self):
        return [r.getMessage() for r in self.records]

    def at(self, level):
        return [r for r in self.records if r.levelno == level]


@pytest.fixture
def records():
    return Records()


@pytest.fixture
def log(records):
    lg = logging.getLogger("test.smart_health_record.monitor")
    lg.handlers = [records]
    lg.setLevel(logging.DEBUG)
    lg.propagate = False
    return lg


@pytest.fixture
def make(clock, wall, log):
    """建立監控器；teardown 一定停止執行緒。"""
    created = []

    def factory(instance="inst", **kw):
        kw.setdefault("clock", clock)
        kw.setdefault("wall_clock", wall)
        kw.setdefault("logger", log)
        m = HealthMonitor("edge", instance, **kw)
        created.append(m)
        return m

    yield factory
    for m in created:
        m.stop()


@pytest.fixture
def gates():
    """阻塞用 Event；teardown 一律釋放，避免殘留執行緒。"""
    events = []

    def new():
        e = threading.Event()
        events.append(e)
        return e

    yield new
    for e in events:
        e.set()


def simple(m, **node_kw):
    m.add_lane("main", "Main")
    return m.add_node("a", "A", "main", **node_kw)


def status_validator():
    return Draft202012Validator(load("status.schema.json"))


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


# ---------------------------------------------------------------- callable

def test_callables_called_once_per_round(make):
    calls = {"dep": 0, "en": 0}

    def dep():
        calls["dep"] += 1
        return True

    def en():
        calls["en"] += 1
        return True

    m = make()
    simple(m, dependencies={"d": dep}, enabled=en)
    m.evaluate_once()
    m.evaluate_once()
    assert calls == {"dep": 2, "en": 2}


def test_dependency_callable_exception_treated_as_none(make):
    def boom():
        raise RuntimeError("down")

    m = make()
    rec = simple(m, dependencies={"d": boom}, startup_grace_s=0)
    rec.record_success()
    m.evaluate_once()
    assert m.status()["nodes"]["a"]["state"] == "ok"


def test_dependency_false_makes_unavailable(make):
    m = make()
    rec = simple(m, dependencies={"mqtt": lambda: False}, startup_grace_s=0)
    rec.record_success()
    m.evaluate_once()
    node = m.status()["nodes"]["a"]
    assert (node["state"], node["reason"], node["message"]) == (
        "unavailable", "dependency_unavailable", "依賴 mqtt 無法使用")


def test_enabled_callable_exception_treated_as_true(make):
    def boom():
        raise RuntimeError("x")

    m = make()
    rec = simple(m, enabled=boom, startup_grace_s=0)
    rec.record_success()
    m.evaluate_once()
    assert m.status()["nodes"]["a"]["state"] == "ok"


def test_repeated_callable_failure_logs_once(make, records):
    mode = {"fail": True}

    def flaky():
        if mode["fail"]:
            raise RuntimeError("password=hunter2")
        return True

    m = make()
    simple(m, dependencies={"d": flaky}, enabled=flaky)
    for _ in range(3):
        m.evaluate_once()
    warnings = [r for r in records.at(logging.WARNING) if "callable" in r.getMessage()]
    assert len(warnings) == 2  # dependency 與 enabled 各一次
    mode["fail"] = False
    m.evaluate_once()
    mode["fail"] = True
    m.evaluate_once()
    warnings = [r for r in records.at(logging.WARNING) if "callable" in r.getMessage()]
    assert len(warnings) == 4  # 成功後重置，再失敗又記一次


def test_logs_never_contain_unmasked_text_or_tracebacks(make, records):
    class Unprintable(Exception):
        def __str__(self):
            raise ValueError("no str")

    def leak():
        raise RuntimeError("password=hunter2 rtsp://admin:s3cret@10.0.0.1/live")

    def unprintable():
        raise Unprintable()

    m = make()
    simple(m, dependencies={"d": leak, "e": unprintable})
    m.evaluate_once()
    assert records.records
    for r in records.records:
        assert "hunter2" not in r.getMessage() and "s3cret" not in r.getMessage()
        assert r.exc_info is None and r.exc_text is None
    assert any("RuntimeError" in t for t in records.texts())
    assert any("Unprintable" in t for t in records.texts())


def test_callable_can_call_status_without_deadlock(make):
    holder = {}

    def dep():
        holder["status"] = holder["m"].status()
        return True

    m = make()
    holder["m"] = m
    simple(m, dependencies={"d": dep})
    call_with_timeout(m.evaluate_once)
    call_with_timeout(m.evaluate_once)
    assert holder["status"]["evaluated_at"] is not None


# ---------------------------------------------------------------- 評估例外

def test_evaluate_once_propagates_exceptions(make, wall):
    m = make()
    simple(m)
    m.evaluate_once()

    def broken():
        raise RuntimeError("clock broken")

    m._wall_clock = broken
    with pytest.raises(RuntimeError):
        m.evaluate_once()


def test_evaluation_exception_does_not_stop_thread(make, wall, records):
    calls = {"n": 0}

    def flaky_wall():
        calls["n"] += 1
        if calls["n"] == 2:  # 第 1 次是 started_at；第 2 次是第一輪評估
            raise RuntimeError("password=hunter2")
        return wall()

    m = make(tick_interval_s=0.01, wall_clock=flaky_wall)
    simple(m)
    m.start()
    wait_until(lambda: m.status()["evaluated_at"] is not None)
    errors = records.at(logging.ERROR)
    assert len(errors) == 1
    assert "RuntimeError" in errors[0].getMessage()
    assert "hunter2" not in errors[0].getMessage()
    assert errors[0].exc_info is None


def test_repeated_evaluation_failure_logs_once(make, records):
    m = make()
    simple(m)
    m.evaluate_once()

    def broken():
        raise RuntimeError("bad")

    m._wall_clock = broken
    for _ in range(3):
        m._guarded_round()
    assert len(records.at(logging.ERROR)) == 1
    m._wall_clock = lambda: __import__("datetime").datetime.now().astimezone()
    m._guarded_round()
    m._wall_clock = broken
    m._guarded_round()
    assert len(records.at(logging.ERROR)) == 2


# ---------------------------------------------------------------- 阻塞與時間

def test_blocking_callable_increases_evaluation_age(make, clock, gates):
    block = gates()
    entered = gates()
    state = {"block": False}

    def dep():
        if state["block"]:
            entered.set()
            block.wait(WAIT_S)
        return True

    m = make(tick_interval_s=0.01)
    simple(m, dependencies={"d": dep})
    m.start()
    wait_until(lambda: m.status()["evaluated_at"] is not None)
    state["block"] = True
    assert entered.wait(WAIT_S)
    published_at = clock.now
    clock.advance(5)
    st = call_with_timeout(m.status)
    assert st["evaluation_age_s"] >= 5.0
    first_age = st["evaluation_age_s"]
    clock.advance(7)
    st = call_with_timeout(m.status)
    assert st["evaluation_age_s"] == pytest.approx(first_age + 7)
    assert st["nodes"]["a"]["state"] in {"ok", "waiting"}  # 仍是快取內容
    assert published_at <= clock.now


def test_status_uses_monotonic_for_age(make, clock, wall):
    m = make()
    simple(m)
    m.evaluate_once()
    clock.advance(2.0)
    wall.advance(-3600)  # wall clock 往回跳
    st = m.status()
    assert st["evaluation_age_s"] == 2.0
    assert st["evaluation_age_s"] >= 0


def test_evaluation_age_never_negative_and_rounded(make, clock):
    m = make()
    simple(m)
    m.evaluate_once()
    clock.advance(1.23456)
    assert m.status()["evaluation_age_s"] == 1.235
    clock.advance(-100)
    assert m.status()["evaluation_age_s"] == 0.0


def test_transition_to_unavailable_logs_warning(make, records, clock):
    m = make()
    rec = simple(m, stale_after_s=10, startup_grace_s=0)
    rec.record_success()
    m.evaluate_once()
    assert not records.at(logging.WARNING)
    assert any(r.levelno == logging.INFO for r in records.records)
    clock.advance(20)
    m.evaluate_once()
    warns = records.at(logging.WARNING)
    assert len(warns) == 1
    assert "unavailable" in warns[0].getMessage() and "stale_success" in warns[0].getMessage()


# ---------------------------------------------------------------- 生命週期

def _eval_threads(instance):
    return [t for t in threading.enumerate()
            if t.name.startswith("smart-health-") and instance in t.name and t.is_alive()]


def test_start_stop_idempotent(make):
    m = make("idem", tick_interval_s=0.01)
    simple(m)
    m.start()
    first_started = m.status()["started_at"]
    m.start()
    assert len(_eval_threads("idem")) == 1
    m.stop()
    m.stop()
    assert _eval_threads("idem") == []
    m.start()
    assert len(_eval_threads("idem")) == 1
    assert m.status()["started_at"] == first_started
    m.stop()
    assert _eval_threads("idem") == []


def test_stop_before_start_is_noop(make):
    m = make()
    simple(m)
    m.stop()
    with pytest.raises(RuntimeError):
        m.status()


def test_restart_keeps_started_at(make, wall):
    m = make("restart", tick_interval_s=0.01)
    simple(m)
    m.start()
    first = m.status()["started_at"]
    m.stop()
    wall.advance(100)
    m.start()
    assert m.status()["started_at"] == first
    m.stop()


def test_first_evaluation_runs_immediately(make):
    m = make("immediate", tick_interval_s=3600)
    simple(m)
    m.start()
    wait_until(lambda: m.status()["evaluated_at"] is not None)
    assert _eval_threads("immediate")


def test_stop_does_not_wait_forever_on_stuck_callable(make, gates, monkeypatch):
    block = gates()
    entered = gates()

    def dep():
        entered.set()
        block.wait(WAIT_S)
        return True

    monkeypatch.setattr(HealthMonitor, "_STOP_JOIN_TIMEOUT_S", 0.2)
    m = make("stuck", tick_interval_s=0.01)
    simple(m, dependencies={"d": dep})
    m.start()
    assert entered.wait(WAIT_S)
    call_with_timeout(m.stop, timeout=3)
    block.set()
    wait_until(lambda: _eval_threads("stuck") == [])


def test_status_before_first_evaluation(make, clock, wall, gates, edge_builder):
    block = gates()
    entered = gates()

    def ffmpeg():
        entered.set()
        block.wait(WAIT_S)
        return True

    m = edge_builder(make("CamA-northbound-1", tick_interval_s=0.01), ffmpeg=ffmpeg)
    m.start()
    assert entered.wait(WAIT_S)
    clock.advance(2.5)
    st = call_with_timeout(m.status)
    expected = load("fixtures/status_before_first_evaluation.json")
    expected["started_at"] = "2026-11-05T10:00:00.000+08:00"
    assert st == expected
    assert st["evaluated_at"] is None and st["nodes"] == {}
    status_validator().validate(st)


def test_status_and_topology_before_start_raise_runtime_error(make):
    m = make()
    simple(m)
    with pytest.raises(RuntimeError):
        m.status()
    with pytest.raises(RuntimeError):
        m.topology()


def test_evaluate_once_without_start_does_not_start_thread(make, clock, wall):
    m = make("nostart")
    simple(m, stale_after_s=None, startup_grace_s=30)
    m.evaluate_once()
    assert _eval_threads("nostart") == []
    st = m.status()
    assert st["started_at"] == "2026-11-05T10:00:00.000+08:00"
    assert st["nodes"]["a"]["reason"] == "starting"
    clock.advance(31)
    wall.advance(31)
    m.evaluate_once()
    assert m.status()["nodes"]["a"]["state"] == "ok"
    m.start()  # 沿用原本的開始時間
    assert m.status()["started_at"] == "2026-11-05T10:00:00.000+08:00"
    m.stop()


def test_add_after_implicit_start_raises(make):
    m = make()
    simple(m)
    m.evaluate_once()
    with pytest.raises(ValueError):
        m.add_lane("x", "X")
    with pytest.raises(ValueError):
        m.add_node("b", "B", "main")


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


# ---------------------------------------------------------------- 執行緒存活（第 1 輪修正）

class RaisingHandler(logging.Handler):
    def emit(self, record):
        raise RuntimeError("handler broken")


def test_logger_failure_does_not_kill_evaluation_thread(make, wall):
    calls = {"n": 0}

    def flaky_wall():
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return wall()

    lg = logging.getLogger("test.smart_health_record.raising")
    lg.handlers = [RaisingHandler()]
    lg.propagate = False
    m = make("raisinglog", tick_interval_s=0.01, wall_clock=flaky_wall, logger=lg)
    simple(m)
    m.start()
    wait_until(lambda: m.status()["evaluated_at"] is not None)
    assert _eval_threads("raisinglog")


def test_baseexception_in_callables_does_not_kill_thread(make):
    def exits():
        raise SystemExit(1)

    m = make("sysexit", tick_interval_s=0.01)
    rec = simple(m, dependencies={"d": exits}, enabled=exits, startup_grace_s=0)
    rec.record_success()
    m.start()
    wait_until(lambda: m.status()["evaluated_at"] is not None)
    assert m.status()["nodes"]["a"]["state"] == "ok"
    assert _eval_threads("sysexit")


def test_baseexception_in_round_does_not_kill_thread(make, wall):
    calls = {"n": 0}

    def exit_once():
        calls["n"] += 1
        if calls["n"] == 2:
            raise SystemExit(1)
        return wall()

    m = make("sysexit2", tick_interval_s=0.01, wall_clock=exit_once)
    simple(m)
    m.start()
    wait_until(lambda: m.status()["evaluated_at"] is not None)
    assert _eval_threads("sysexit2")


def test_enabled_bool_failure_treated_as_true_and_warns_once(make, records):
    class BadBool:
        def __bool__(self):
            raise RuntimeError("no bool")

    m = make()
    rec = simple(m, enabled=lambda: BadBool(), startup_grace_s=0)
    rec.record_success()
    for _ in range(3):
        m.evaluate_once()
    assert m.status()["nodes"]["a"]["state"] == "ok"
    warns = [r for r in records.at(logging.WARNING) if "callable" in r.getMessage()]
    assert len(warns) == 1


@pytest.mark.parametrize("value", [1e12, float("inf"), threading.TIMEOUT_MAX * 2])
def test_too_large_tick_interval_rejected(value):
    with pytest.raises(ValueError):
        HealthMonitor("edge", "i", tick_interval_s=value)


def test_stopped_thread_does_not_run_round_after_getting_lock(make, monkeypatch):
    monkeypatch.setattr(HealthMonitor, "_STOP_JOIN_TIMEOUT_S", 0.1)
    m = make("lateStop".lower(), tick_interval_s=0.01)
    simple(m)
    m._eval_lock.acquire()
    try:
        m.start()
        call_with_timeout(m.stop, timeout=3)
    finally:
        m._eval_lock.release()
    wait_until(lambda: _eval_threads("latestop") == [])
    assert m.status()["evaluated_at"] is None


def test_secrets_never_appear_in_status_or_logs(make, records):
    m = make()
    m.add_lane("main", "Main")
    r1 = m.add_node("n1", "N1", "main", startup_grace_s=0)
    r2 = m.add_node("n2", "N2", "main", startup_grace_s=0)
    r3 = m.add_node("n3", "N3", "main", startup_grace_s=0)
    r4 = m.add_node("n4", "N4", "main", startup_grace_s=0)
    r1.set_fatal("boom", "password=hunter2")
    r2.record_error("bad", "token: abc123tok")
    with pytest.raises(ValueError):
        with r3.track():
            raise ValueError("api_key=zzz999key")
    r4.record_success()
    r4.set_metric("url", "rtsp://admin:s3cret@10.0.0.1/live")
    m.evaluate_once()
    blob = json.dumps(m.status(), ensure_ascii=False) + "\n".join(records.texts())
    for secret in ("hunter2", "abc123tok", "zzz999key", "s3cret"):
        assert secret not in blob
    assert "password=***" in blob
