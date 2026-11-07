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
