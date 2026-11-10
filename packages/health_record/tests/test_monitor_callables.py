"""HealthMonitor 行為測試：callable 與評估例外（規格書 4.3、5.1、5.2）。

不使用 sleep 等待狀態：以 Event 同步，或以輪詢加上限時間。
共用工具在 monitor_support.py，fixture 在 conftest.py。
"""
import logging
from datetime import datetime

import pytest
from monitor_support import (
    call_with_timeout,
    simple,
    wait_until,
)


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
    rec = simple(m, dependencies={"messaging": lambda: False}, startup_grace_s=0)
    rec.record_success()
    m.evaluate_once()
    node = m.status()["nodes"]["a"]
    assert (node["state"], node["reason"], node["message"]) == (
        "unavailable", "dependency_unavailable", "依賴 messaging 無法使用")


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
    m._wall_clock = lambda: datetime.now().astimezone()
    m._guarded_round()
    m._wall_clock = broken
    m._guarded_round()
    assert len(records.at(logging.ERROR)) == 2
