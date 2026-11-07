"""Poller 的 log：只在連線代碼改變時記錄，detail 不含換行。"""

from __future__ import annotations

import asyncio
import logging

import pytest
from poller_support import reaches, running
from support import make_config, wait_until

pytestmark = pytest.mark.anyio


async def test_failure_logged_once_per_change_and_recovery(network, make_service, caplog):
    svc = make_service()
    svc.mode = "http500"
    network.add("t1", svc)
    with caplog.at_level(logging.INFO, logger="smart_health_backend"):
        async with running(make_config(["t1"]), network) as (store, _):
            await reaches(store, "offline")
            await wait_until(lambda: svc.count("/topology") >= 5)
            warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
            assert len(warnings) == 1
            svc.mode = "ok"
            await reaches(store, "online")
            await asyncio.sleep(0)
    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(infos) == 1


async def test_failure_log_detail_has_no_newlines(network, make_service, caplog):
    svc = make_service()
    svc.status["nodes"]["evil\nnode"] = svc.status["nodes"]["ingest"]
    network.add("t1", svc)
    with caplog.at_level(logging.INFO, logger="smart_health_backend"):
        async with running(make_config(["t1"]), network) as (store, _):
            await reaches(store, "invalid_response")
    assert caplog.records
    assert all("\n" not in r.getMessage() for r in caplog.records)


async def test_apply_status_failure_not_logged_as_recovery(network, make_service, caplog):
    """apply_status 拋例外時不能記「已恢復 online」，traceback 也只在代碼改變時輸出一次。"""
    svc = make_service()
    network.add("t1", svc)
    config = make_config(["t1"])
    with caplog.at_level(logging.INFO, logger="smart_health_backend"):
        async with running(config, network) as (store, _):
            calls = {"n": 0}

            def broken(*_args):
                calls["n"] += 1
                raise RuntimeError("store broke")

            store.apply_status = broken
            await wait_until(lambda: calls["n"] >= 5)
    records = [r for r in caplog.records if r.name.startswith("smart_health_backend")]
    assert not [r for r in records if "恢復" in r.getMessage()]
    assert len([r for r in records if r.exc_info is not None]) == 1
    assert len([r for r in records if r.levelno == logging.WARNING]) == 1


async def test_unexpected_error_after_offline_logged_once_per_episode(network, make_service, caplog):
    """先因連線失敗變 offline，之後 apply_status 每輪拋例外：traceback 仍要輸出一次。

    成功一輪後再拋例外，算新的一次，要再輸出一次。
    """
    svc = make_service()
    svc.mode = "http500"
    network.add("t1", svc)
    with caplog.at_level(logging.INFO, logger="smart_health_backend"):
        async with running(make_config(["t1"]), network) as (store, _):
            await reaches(store, "offline")
            original = store.apply_status
            calls = {"n": 0}

            def broken(*_args):
                calls["n"] += 1
                raise RuntimeError("store broke")

            def tracebacks():
                return [r for r in caplog.records if r.exc_info is not None]

            store.apply_status = broken
            svc.mode = "ok"
            await wait_until(lambda: calls["n"] >= 5)
            assert len(tracebacks()) == 1

            store.apply_status = original
            await reaches(store, "online")
            store.apply_status = broken
            base = calls["n"]
            await wait_until(lambda: calls["n"] >= base + 5)
            assert len(tracebacks()) == 2
