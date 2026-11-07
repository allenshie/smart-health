"""Poller 生命週期：run／stop、取消與 task 清理。"""

from __future__ import annotations

import asyncio
import contextlib

import pytest
from poller_support import reaches
from support import make_config, wait_until

from smart_health_backend.poller import Poller
from smart_health_backend.store import TargetStore

pytestmark = pytest.mark.anyio


async def test_stop_cancels_all_tasks(network, make_service):
    svc = make_service()
    svc.mode = "hang"
    network.add("t1", svc)
    config = make_config(["t1"], timeout=5)
    store = TargetStore(config)
    async with network.client() as client:
        poller = Poller(config, store, client)
        task = asyncio.create_task(poller.run())
        await wait_until(lambda: svc.count("/topology") >= 1)
        await asyncio.wait_for(poller.stop(), 1)
        await asyncio.wait_for(task, 1)
        assert task.done()


def poll_tasks() -> list[asyncio.Task]:
    return [t for t in asyncio.all_tasks() if t.get_name().startswith("poll-") and not t.done()]


async def test_stop_before_run_leaves_no_tasks(network, make_service):
    network.add("t1", make_service())
    config = make_config(["t1"])
    async with network.client() as client:
        poller = Poller(config, TargetStore(config), client)
        run_task = asyncio.create_task(poller.run())
        await poller.stop()  # run 尚未開始執行
        await asyncio.wait_for(run_task, 1)
        await asyncio.sleep(0)
        assert poll_tasks() == []


async def test_cancelled_run_cleans_up_tasks(network, make_service):
    network.add("t1", make_service())
    config = make_config(["t1"])
    async with network.client() as client:
        poller = Poller(config, TargetStore(config), client)
        run_task = asyncio.create_task(poller.run())
        await wait_until(lambda: len(poll_tasks()) == 1)
        run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task
        assert poll_tasks() == []


async def test_run_twice_raises_and_keeps_single_set(network, make_service):
    network.add("t1", make_service())
    config = make_config(["t1"])
    async with network.client() as client:
        poller = Poller(config, TargetStore(config), client)
        run_task = asyncio.create_task(poller.run())
        await wait_until(lambda: len(poll_tasks()) == 1)
        with pytest.raises(RuntimeError):
            await poller.run()
        assert len(poll_tasks()) == 1
        await poller.stop()
        await asyncio.wait_for(run_task, 1)
        assert poll_tasks() == []


async def test_run_after_stop_returns_immediately(network, make_service):
    network.add("t1", make_service())
    config = make_config(["t1"])
    async with network.client() as client:
        poller = Poller(config, TargetStore(config), client)
        run_task = asyncio.create_task(poller.run())
        await wait_until(lambda: len(poll_tasks()) == 1)
        await poller.stop()
        await asyncio.wait_for(run_task, 1)
        await asyncio.wait_for(poller.run(), 1)  # 停止後的 run 立刻返回，不建立 task
        await asyncio.sleep(0)
        assert poll_tasks() == []


async def test_failure_handler_exception_does_not_end_target_task(network, make_service):
    svc = make_service()
    svc.mode = "http500"
    network.add("t1", svc)
    config = make_config(["t1"])
    store = TargetStore(config)
    original = store.apply_failure
    calls = {"n": 0}

    def flaky(tid, code):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("store broke")
        original(tid, code)

    store.apply_failure = flaky
    async with network.client() as client:
        poller = Poller(config, store, client)
        task = asyncio.create_task(poller.run())
        try:
            await reaches(store, "offline")  # 前兩次 apply_failure 拋例外後仍繼續
            assert len(poll_tasks()) == 1
        finally:
            await poller.stop()
            await task
