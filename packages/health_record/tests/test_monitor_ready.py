"""等待就緒：mark_ready() 與 /status 的 ready_at（規格書 3.1、4.3、5.1、5.2）。"""
import threading

import pytest
from monitor_support import WAIT_S, call_with_timeout, simple, status_validator

T0 = "2026-11-05T10:00:00.000+08:00"


# ---------------------------------------------------------------- mark_ready()

@pytest.mark.parametrize("wait", [False, True])
def test_mark_ready_before_start_raises_runtime_error(make, wait):
    m = make(wait_for_ready=wait)
    simple(m)
    with pytest.raises(RuntimeError):
        m.mark_ready()


@pytest.mark.parametrize("wait", [False, True])
def test_mark_ready_after_implicit_start_is_allowed(make, wait):
    m = make(wait_for_ready=wait)
    simple(m)
    m.evaluate_once()  # 隱含 start
    m.mark_ready()


def test_ready_at_equals_started_at_without_wait_for_ready(make, clock, wall):
    m = make()
    simple(m)
    m.start()
    st = m.status()
    assert st["ready_at"] == st["started_at"] == T0
    status_validator().validate(st)


def test_mark_ready_is_noop_without_wait_for_ready(make, clock, wall):
    m = make()
    simple(m, startup_grace_s=5)
    m.evaluate_once()
    clock.advance(100)
    wall.advance(100)
    m.mark_ready()  # 不能把就緒時刻改成現在
    m.evaluate_once()
    st = m.status()
    assert st["ready_at"] == T0
    # 寬限期仍從 start() 起算：已超過 5 秒，不再是 starting
    assert st["nodes"]["a"]["state"] == "ok"


def test_ready_at_is_null_until_mark_ready(make, clock, wall):
    m = make(wait_for_ready=True)
    simple(m)
    m.start()
    st = m.status()  # 可能是第一輪前或後，都必須是 null
    assert st["ready_at"] is None
    status_validator().validate(st)
    wall.advance(42)
    m.mark_ready()
    assert m.status()["ready_at"] == "2026-11-05T10:00:42.000+08:00"


def test_repeated_mark_ready_keeps_first_ready_time(make, clock, wall):
    m = make(wait_for_ready=True)
    simple(m)
    m.evaluate_once()
    wall.advance(10)
    m.mark_ready()
    wall.advance(10)
    clock.advance(10)
    m.mark_ready()
    assert m.status()["ready_at"] == "2026-11-05T10:00:10.000+08:00"


def test_ready_at_before_first_evaluation_with_wait_for_ready(make, gates):
    entered, block = gates(), gates()

    def blocking_wall():
        # 只卡住評估執行緒：讓 status() 停在「第一輪評估完成前」
        import datetime as _dt
        if threading.current_thread().name.startswith("smart-health-"):
            entered.set()
            block.wait(WAIT_S)
        return _dt.datetime(2026, 11, 5, 10, 0, 0, tzinfo=_dt.timezone(_dt.timedelta(hours=8)))

    m = make(wait_for_ready=True, wall_clock=blocking_wall, tick_interval_s=0.01)
    simple(m)
    m.start()
    assert entered.wait(WAIT_S)
    st = call_with_timeout(m.status)
    assert st["evaluated_at"] is None and st["ready_at"] is None
    status_validator().validate(st)


def test_mark_ready_does_not_wait_for_evaluation(make, gates):
    """評估卡住時，mark_ready() 仍要立即回傳（不碰評估鎖）。"""
    entered, block = gates(), gates()
    import datetime as _dt
    tz = _dt.timezone(_dt.timedelta(hours=8))

    def wall():
        if threading.current_thread().name.startswith("smart-health-"):
            entered.set()
            block.wait(WAIT_S)
        return _dt.datetime(2026, 11, 5, 10, 0, 0, tzinfo=tz)

    m = make(wait_for_ready=True, wall_clock=wall, tick_interval_s=0.01)
    simple(m)
    m.start()
    assert entered.wait(WAIT_S)  # 評估執行緒持有評估鎖，卡在發布前
    call_with_timeout(m.mark_ready, timeout=1.0)
    assert m.status()["ready_at"] is not None
