import dataclasses
import logging
import threading

import pytest

from smart_health_record import NodeRecorder
from smart_health_record.recorder import RecorderSnapshot


@pytest.fixture
def rec(clock, logger):
    return NodeRecorder("n1", clock, logger)


def test_initial_snapshot_is_empty(rec):
    s = rec.snapshot()
    assert s.last_success_at is None and s.last_error_at is None
    assert s.last_error_reason is None and s.last_error_message is None
    assert s.in_progress_since is None
    assert s.fatal_reason is None and s.fatal_message is None
    assert dict(s.metrics) == {}


def test_snapshot_is_frozen(rec):
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.snapshot().last_success_at = 1.0
    assert [f.name for f in dataclasses.fields(RecorderSnapshot)] == [
        "last_success_at", "last_error_at", "last_error_reason",
        "last_error_message", "in_progress_since", "fatal_reason",
        "fatal_message", "metrics",
    ]


def test_record_success_and_start(rec, clock):
    rec.record_start()
    assert rec.snapshot().in_progress_since == 1000.0
    clock.advance(2)
    rec.record_success()
    s = rec.snapshot()
    assert s.last_success_at == 1002.0 and s.in_progress_since is None


def test_success_clears_in_progress(rec):
    rec.record_start()
    rec.record_success()
    assert rec.snapshot().in_progress_since is None


def test_error_clears_in_progress(rec, clock):
    rec.record_start()
    clock.advance(1)
    rec.record_error("timeout", "x")
    s = rec.snapshot()
    assert s.in_progress_since is None
    assert s.last_error_at == 1001.0 and s.last_error_reason == "timeout"


def test_record_error_masks_message(rec):
    rec.record_error("conn_failed", "open rtsp://admin:secret@10.0.0.1/live password=abc")
    msg = rec.snapshot().last_error_message
    assert "secret" not in msg and "abc" not in msg
    assert "rtsp://***@10.0.0.1/live" in msg


def test_record_error_message_none_and_truncate(rec):
    rec.record_error("a")
    assert rec.snapshot().last_error_message is None
    rec.record_error("a", "m" * 999)
    assert len(rec.snapshot().last_error_message) == 200


def test_invalid_reason_does_not_raise(rec):
    rec.record_error("Bad Reason")
    assert rec.snapshot().last_error_reason == "invalid_reason"


@pytest.mark.parametrize("bad", ["", "1abc", "a-b", "ab\n", None, 5, b"x", object()])
def test_invalid_reason_variants(rec, bad):
    rec.record_error(bad)
    assert rec.snapshot().last_error_reason == "invalid_reason"


def test_non_string_message_does_not_raise(rec):
    rec.record_error("ok_reason", 12345)
    rec.record_error("ok_reason", object())
    rec.record_error("ok_reason", ["password=abc"])
    assert "abc" not in (rec.snapshot().last_error_message or "")


def test_message_whose_str_raises(rec):
    class Bad:
        def __str__(self):
            raise RuntimeError("boom")

    rec.record_error("r", Bad())
    s = rec.snapshot()
    assert s.last_error_reason == "r" and s.last_error_message is None


def test_fatal_set_and_clear(rec):
    rec.set_fatal("model_missing", "token=abc gone")
    s = rec.snapshot()
    assert s.fatal_reason == "model_missing" and "abc" not in s.fatal_message
    rec.clear_fatal()
    s = rec.snapshot()
    assert s.fatal_reason is None and s.fatal_message is None


def test_set_fatal_invalid_reason(rec):
    rec.set_fatal("BAD")
    assert rec.snapshot().fatal_reason == "invalid_reason"
    rec.set_fatal(None, object())


def test_set_metric_basic_types(rec):
    for name, v in [("a", 1), ("b", 1.5), ("c", "s"), ("d", True), ("e", None)]:
        rec.set_metric(name, v)
    assert dict(rec.snapshot().metrics) == {"a": 1, "b": 1.5, "c": "s", "d": True, "e": None}


def test_set_metric_masks_string_values(rec):
    rec.set_metric("url", "rtsp://a:b@h/x")
    rec.set_metric("note", "token=abc")
    m = rec.snapshot().metrics
    assert m["url"] == "rtsp://***@h/x" and m["note"] == "token=***"
    rec.set_metric("long", "z" * 500)
    assert len(rec.snapshot().metrics["long"]) == 200


def test_invalid_metric_type_ignored(rec):
    rec.set_metric("good", 1)
    rec.set_metric("bad", object())
    rec.set_metric("bad2", [1])
    rec.set_metric("nan", float("nan"))
    assert dict(rec.snapshot().metrics) == {"good": 1}


def test_invalid_metric_replaces_nothing(rec):
    rec.set_metric("k", 1)
    rec.set_metric("k", object())
    assert rec.snapshot().metrics["k"] == 1


def test_invalid_metric_name_does_not_raise(rec):
    rec.set_metric(None, 1)
    rec.set_metric(123, 1)
    rec.set_metric(object(), 1)
    assert dict(rec.snapshot().metrics) == {}


def test_snapshot_metrics_cannot_mutate_internal_state(rec):
    rec.set_metric("a", 1)
    s = rec.snapshot()
    with pytest.raises(TypeError):
        s.metrics["a"] = 2
    with pytest.raises(TypeError):
        s.metrics["b"] = 2
    rec.set_metric("c", 3)
    assert "c" not in s.metrics  # 快照不隨後續記錄變動
    assert rec.snapshot().metrics["a"] == 1


def test_track_success_records_success(rec, clock):
    with rec.track():
        assert rec.snapshot().in_progress_since == 1000.0
        clock.advance(3)
    s = rec.snapshot()
    assert s.last_success_at == 1003.0 and s.in_progress_since is None


def test_track_exception_records_and_reraises(rec):
    with pytest.raises(ValueError, match="oops"):
        with rec.track():
            raise ValueError("oops")
    s = rec.snapshot()
    assert s.last_error_reason == "exception"
    assert s.last_error_message == "oops"
    assert s.in_progress_since is None and s.last_success_at is None


def test_track_exception_message_masked(rec):
    with pytest.raises(RuntimeError):
        with rec.track():
            raise RuntimeError("fail rtsp://a:b@h/x")
    assert rec.snapshot().last_error_message == "fail rtsp://***@h/x"


def test_track_exception_with_failing_str_reraises_original(rec):
    class E(Exception):
        def __str__(self):
            raise RuntimeError("str boom")

    with pytest.raises(E):
        with rec.track():
            raise E()
    s = rec.snapshot()
    assert s.last_error_reason == "exception" and s.last_error_message is None


def test_uses_monotonic_clock_only(clock, logger, monkeypatch):
    import time

    def boom(*a, **k):
        raise AssertionError("wall clock used")

    monkeypatch.setattr(time, "time", boom)
    monkeypatch.setattr(time, "monotonic", boom)
    r = NodeRecorder("n", clock, logger)
    r.record_start()
    r.record_success()
    r.record_error("x")
    with r.track():
        pass
    assert r.snapshot().last_success_at == 1000.0


def test_failing_clock_does_not_raise(logger):
    def bad():
        raise RuntimeError("clock")

    r = NodeRecorder("n", bad, logger)
    r.record_start()
    r.record_success()
    r.record_error("x")
    with r.track():
        pass
    assert r.snapshot().last_success_at is None


def test_invalid_reason_warns_once(rec, log_handler):
    secret = "Bad Secret password=hunter2"
    rec.record_error(secret)
    rec.record_error(secret)
    rec.set_fatal("ALSO BAD")
    warnings = [m for m in log_handler.messages if "reason" in m]
    assert len(warnings) == 1
    assert "hunter2" not in warnings[0] and "Bad Secret" not in warnings[0]


def test_invalid_metric_warns_once_without_value(rec, log_handler):
    class Leaky:
        def __repr__(self):
            return "LEAK-token=abc"

    rec.set_metric("a", Leaky())
    rec.set_metric("b", Leaky())
    assert len(log_handler.messages) == 1
    assert "LEAK" not in log_handler.messages[0] and "abc" not in log_handler.messages[0]


def test_warning_categories_are_independent(rec, log_handler):
    rec.record_error("BAD")
    rec.set_metric("a", object())
    assert len(log_handler.messages) == 2


def test_warning_once_per_recorder(clock, logger, log_handler):
    NodeRecorder("a", clock, logger).record_error("BAD")
    NodeRecorder("b", clock, logger).record_error("BAD")
    assert len(log_handler.messages) == 2


def test_no_logging_while_holding_lock(clock):
    holder = {}

    class CheckingHandler(logging.Handler):
        def emit(self, record):
            # 若呼叫端持有鎖，這裡無法取得
            got = holder["rec"]._lock.acquire(blocking=False)
            holder["free"] = got
            if got:
                holder["rec"]._lock.release()

    log = logging.getLogger("test.lockcheck")
    log.handlers = [CheckingHandler()]
    log.propagate = False
    r = NodeRecorder("n", clock, log)
    holder["rec"] = r
    r.record_error("BAD")
    assert holder["free"] is True


def test_logger_failure_does_not_raise(clock):
    class BadLogger:
        def warning(self, *a, **k):
            raise RuntimeError("log boom")

    r = NodeRecorder("n", clock, BadLogger())
    r.record_error("BAD")
    r.set_metric("a", object())


def test_concurrent_recording_is_safe(rec):
    def work():
        for i in range(500):
            with rec.track():
                rec.set_metric("i", i)
            rec.snapshot()

    ts = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert rec.snapshot().last_success_at is not None


def test_record_error_masks_authorization_header(rec):
    rec.record_error("bad_auth", "Authorization: Bearer abc")
    msg = rec.snapshot().last_error_message
    assert "abc" not in msg and msg == "Authorization: Bearer ***"
