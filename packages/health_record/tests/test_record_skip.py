"""NodeRecorder.record_skip()（規格書 5.1、5.2）：跳過只清除進行中狀態，不算成功。"""
from monitor_support import simple


def _facts(rec):
    s = rec.snapshot()
    return (s.last_success_at, s.last_error_at, s.last_error_reason, s.last_error_message,
            s.fatal_reason, s.fatal_message, dict(s.metrics))


# ---------------------------------------------------------------- recorder

def test_record_skip_clears_in_progress(rec, clock):
    rec.record_start()
    assert rec.snapshot().in_progress_since == 1000.0
    rec.record_skip()
    assert rec.snapshot().in_progress_since is None


def test_record_skip_keeps_all_other_facts(rec, clock):
    rec.record_success()
    clock.advance(1)
    rec.record_error("read_error", "讀取失敗")
    rec.set_fatal("broken", "壞了")
    rec.set_metric("fps", 12.5)
    clock.advance(1)
    rec.record_start()
    clock.advance(1)
    rec.record_skip()
    assert _facts(rec) == (1000.0, 1001.0, "read_error", "讀取失敗", "broken", "壞了",
                           {"fps": 12.5})
    assert rec.snapshot().in_progress_since is None


def test_record_skip_without_work_in_progress_does_nothing(rec, clock):
    rec.record_success()
    before = rec.snapshot()
    clock.advance(5)
    rec.record_skip()
    assert rec.snapshot() == before


def test_record_skip_does_not_raise_into_business_thread(rec):
    class BrokenLock:
        def __enter__(self):
            raise RuntimeError("lock boom")

        def __exit__(self, *exc):
            return False

    rec._lock = BrokenLock()
    rec.record_skip()  # 不能拋出


# ---------------------------------------------------------------- 評估（驗收）

def test_skip_after_start_is_not_stuck(make, clock):
    m = make()
    rec = simple(m, stuck_after_s=5, startup_grace_s=0)
    rec.record_success()
    rec.record_start()
    rec.record_skip()
    clock.advance(10)
    m.evaluate_once()
    node = m.status()["nodes"]["a"]
    assert (node["state"], node["reason"]) == ("ok", None)


def test_continuous_skip_becomes_stale(make, clock):
    m = make()
    rec = simple(m, stale_after_s=5, stuck_after_s=5, startup_grace_s=0)
    m.evaluate_once()
    rec.record_success()
    for _ in range(6):  # 每秒執行一次，每次都跳過
        clock.advance(1)
        rec.record_start()
        rec.record_skip()
    m.evaluate_once()
    node = m.status()["nodes"]["a"]
    assert (node["state"], node["reason"], node["message"]) == (
        "unavailable", "stale_success", "已 6 秒沒有成功紀錄")
