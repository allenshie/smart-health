"""NodeRecorder.track()：成功、Exception 與其他 BaseException（取消、Ctrl-C）。"""
import asyncio

import pytest


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


@pytest.mark.parametrize("exc_type", [asyncio.CancelledError, KeyboardInterrupt, SystemExit])
def test_track_base_exception_clears_in_progress_only(rec, clock, exc_type):
    rec.record_success()
    clock.advance(5)
    with pytest.raises(exc_type):
        with rec.track():
            assert rec.snapshot().in_progress_since == 1005.0
            raise exc_type()
    s = rec.snapshot()
    assert s.in_progress_since is None  # 不殘留進行中，避免假的 stuck
    assert s.last_success_at == 1000.0  # 不記 success
    assert s.last_error_at is None and s.last_error_reason is None  # 也不記 error


def test_track_cancelled_async_task_clears_in_progress(rec):
    async def main():
        started = asyncio.Event()

        async def work():
            with rec.track():
                started.set()
                await asyncio.sleep(3600)

        task = asyncio.create_task(work())
        await started.wait()
        assert rec.snapshot().in_progress_since is not None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    s = rec.snapshot()
    assert s.in_progress_since is None
    assert s.last_success_at is None and s.last_error_at is None
