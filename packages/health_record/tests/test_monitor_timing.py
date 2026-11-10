"""HealthMonitor 行為測試：阻塞、時間與生命週期（規格書 4.3、5.1、5.2）。

不使用 sleep 等待狀態：以 Event 同步，或以輪詢加上限時間。
共用工具在 monitor_support.py，fixture 在 conftest.py。
"""
import logging

import pytest
from monitor_support import (
    WAIT_S,
    _eval_threads,
    call_with_timeout,
    load,
    simple,
    status_validator,
    wait_until,
)

from smart_health_record import HealthMonitor


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

    def stream_sink():
        entered.set()
        block.wait(WAIT_S)
        return True

    m = edge_builder(make("CamA-northbound-1", tick_interval_s=0.01), stream_sink=stream_sink)
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
