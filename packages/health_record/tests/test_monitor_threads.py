"""HealthMonitor 行為測試：執行緒存活（規格書 4.3、5.1、5.2）。

不使用 sleep 等待狀態：以 Event 同步，或以輪詢加上限時間。
共用工具在 monitor_support.py，fixture 在 conftest.py。
"""
import json
import logging
import threading

import pytest
from monitor_support import (
    _eval_threads,
    call_with_timeout,
    simple,
    wait_until,
)

from smart_health_record import HealthMonitor


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
