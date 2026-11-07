"""Poller 測試共用工具：在背景執行 Poller，並等待目標的連線狀態。"""

from __future__ import annotations

import asyncio
import contextlib

from support import wait_until

from smart_health_backend.poller import Poller
from smart_health_backend.store import TargetStore


@contextlib.asynccontextmanager
async def running(config, network):
    store = TargetStore(config)
    async with network.client() as client:
        poller = Poller(config, store, client)
        task = asyncio.create_task(poller.run())
        try:
            yield store, poller
        finally:
            await poller.stop()
            await asyncio.wait_for(task, 2)


def conn(store, tid="t1"):
    return store.get_view(tid).connection


async def reaches(store, connection, tid="t1"):
    await wait_until(lambda: conn(store, tid) == connection)
