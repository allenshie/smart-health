from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time

import pytest
from support import make_config, wait_until

from smart_health_backend.poller import Poller
from smart_health_backend.store import TargetStore


pytestmark = pytest.mark.anyio


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


async def test_connection_unknown_before_first_poll(network, make_service):
    svc = make_service()
    svc.mode = "hang"
    network.add("t1", svc)
    async with running(make_config(["t1"], timeout=5), network) as (store, _):
        await wait_until(lambda: svc.count("/topology") >= 1)  # 第一輪已開始但未完成
        assert conn(store) == "unknown"
        assert store.list_views()[0].summary_color == "gray"


async def test_connection_online(network, make_service):
    network.add("t1", make_service())
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "online")
        view = store.get_view("t1")
        assert view.nodes["ingest-worker"].color == "red"
        assert view.nodes["ingest-worker"].state == "unavailable"
        assert view.last_success_at is not None
        assert view.summary_color == "red"


async def test_timeout_marks_offline(network, make_service):
    svc = make_service()
    svc.mode = "hang"
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "offline")


async def test_http_500_marks_offline(network, make_service):
    svc = make_service()
    svc.mode = "http500"
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "offline")


async def test_invalid_json_marks_invalid_response(network, make_service):
    svc = make_service()
    svc.mode, svc.raw_body = "raw_status", b"<html>not json</html>"
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "invalid_response")


async def test_nan_in_response_marks_invalid_response(network, make_service):
    svc = make_service()
    svc.mode, svc.raw_body = "raw_status", b'{"schema_version": 1, "evaluation_age_s": NaN}'
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "invalid_response")


async def test_contract_violation_marks_invalid_response(network, make_service):
    svc = make_service()
    svc.status["nodes"]["ingest"]["state"] = "exploded"
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "invalid_response")


async def test_unsupported_schema_marks_incompatible(network, make_service):
    svc = make_service()
    svc.status["schema_version"] = 2
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "incompatible")


async def test_incompatible_topology(network, make_service):
    svc = make_service()
    svc.topology["schema_version"] = 7
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "incompatible")
        assert store.get_view("t1").topology is None


async def test_evaluation_age_over_limit_marks_stale(network, make_service):
    svc = make_service()
    svc.status["evaluation_age_s"] = 11.0
    network.add("t1", svc)
    async with running(make_config(["t1"], stale=10), network) as (store, _):
        await reaches(store, "stale")
        view = store.get_view("t1")
        assert view.summary_color == "gray"
        assert view.last_success_at is None
        svc.status["evaluation_age_s"] = 10.0  # 等於門檻不算 stale
        await reaches(store, "online")


async def test_not_online_makes_all_nodes_gray(network, make_service):
    svc = make_service()
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "online")
        before = store.get_view("t1")
        assert any(n.color == "red" for n in before.nodes.values())
        svc.mode = "hang"
        await reaches(store, "offline")
        after = store.get_view("t1")
        assert list(after.nodes) == list(before.nodes)
        assert after.topology == before.topology
        assert all(n.color == "gray" for n in after.nodes.values())
        assert after.summary_color == "gray"


async def test_not_online_node_payload(network, make_service):
    svc = make_service()
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "online")
        svc.mode = "http500"
        await reaches(store, "offline")
        for node in store.get_view("t1").nodes.values():
            assert node.state is None
            assert node.message is None
            assert node.since is None
            assert node.metrics == {}
            assert node.reason == "offline"
            assert node.color == "gray"


async def test_status_before_first_evaluation_is_status_missing(
    network, make_service, status_before_first
):
    svc = make_service()
    svc.status = status_before_first
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "online")
        view = store.get_view("t1")
        assert len(view.nodes) == 6
        assert all(n.reason == "status_missing" and n.color == "gray" for n in view.nodes.values())
        assert view.summary_color == "gray"


async def test_blocked_first_evaluation_becomes_stale(network, make_service, status_before_first):
    svc = make_service()
    svc.status = status_before_first
    svc.status["evaluation_age_s"] = 30.0
    network.add("t1", svc)
    async with running(make_config(["t1"], stale=10), network) as (store, _):
        await reaches(store, "stale")


async def test_topology_fetched_once_while_unchanged(network, make_service):
    svc = make_service()
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await wait_until(lambda: svc.count("/status") >= 4)
        assert svc.count("/topology") == 1


async def test_topology_refetched_on_version_change(network, make_service, topology_edge):
    svc = make_service()
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "online")
        svc.topology["topology_version"] = "aaaaaaaaaaaaaaaa"
        svc.topology["nodes"][0]["label"] = "Renamed"
        svc.status["topology_version"] = "aaaaaaaaaaaaaaaa"
        await wait_until(
            lambda: store.get_view("t1").topology.topology_version == "aaaaaaaaaaaaaaaa"
        )
        assert svc.count("/topology") == 2
        assert conn(store) == "online"
        assert store.get_view("t1").topology.nodes[0].label == "Renamed"


async def test_topology_refetched_on_restart(network, make_service):
    svc = make_service()
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "online")
        assert svc.count("/topology") == 1
        svc.topology["nodes"][0]["label"] = "AfterRestart"  # 版本字串不變，只有重啟
        svc.status["started_at"] = "2026-11-05T11:00:00+08:00"
        await wait_until(lambda: svc.count("/topology") == 2)
        await wait_until(lambda: store.get_view("t1").topology.nodes[0].label == "AfterRestart")
        await asyncio.sleep(0.2)
        assert svc.count("/topology") == 2


async def test_version_still_mismatched_after_refetch_is_invalid(network, make_service):
    svc = make_service()
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "online")
        before = store.get_view("t1").topology
        # status 說 B，重新取得的 /topology 卻是第三個版本 C
        svc.status["topology_version"] = "bbbbbbbbbbbbbbbb"
        svc.topology["topology_version"] = "cccccccccccccccc"
        svc.topology["nodes"][0]["label"] = "VersionC"
        await reaches(store, "invalid_response")
        await wait_until(lambda: svc.count("/topology") >= 3)  # 之後每輪仍會重取
        assert store.get_view("t1").topology == before
        assert conn(store) == "invalid_response"


async def test_old_nodes_disappear_after_topology_change(network, make_service):
    svc = make_service()
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "online")
        assert "publish" in store.get_view("t1").nodes
        svc.topology["nodes"] = [n for n in svc.topology["nodes"] if n["id"] != "publish"]
        svc.topology["lanes"][0]["nodes"].remove("publish")
        svc.topology["topology_version"] = svc.status["topology_version"] = "dddddddddddddddd"
        await wait_until(lambda: "publish" not in store.get_view("t1").nodes)
        assert len(store.get_view("t1").nodes) == 5


async def test_hanging_target_does_not_delay_others(network, make_service):
    hang, good = make_service(), make_service()
    hang.mode = "hang"
    network.add("bad", hang)
    network.add("good", good)
    config = make_config(["bad", "good"], interval=0.05, timeout=0.2)
    async with running(config, network) as (store, _):
        await reaches(store, "online", "good")
        start = time.monotonic()
        base = good.count("/status")
        await wait_until(lambda: good.count("/status") >= base + 3)
        # 0.5 秒（10 個間隔）內至少 3 次更新；若被掛起目標拖慢，每輪會多 0.2 秒逾時
        assert time.monotonic() - start < 0.5
        assert conn(store, "bad") != "online"


async def test_redirect_not_followed(network, make_service):
    svc, elsewhere = make_service(), make_service()
    svc.mode = "redirect"
    network.add("t1", svc)
    network.add("elsewhere.test", elsewhere)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "offline")
        await asyncio.sleep(0.15)
    assert "elsewhere.test" not in network.hosts_seen
    assert elsewhere.requests == []


async def test_interval_subtracts_request_time(network, make_service):
    svc = make_service()
    svc.delay = 0.08  # 每個請求花 0.08 秒
    network.add("t1", svc)
    config = make_config(["t1"], interval=0.2, timeout=0.5)
    async with running(config, network):
        await wait_until(lambda: len(svc.status_times) >= 5)
    times = svc.status_times[1:5]  # 第一輪多一個 /topology 請求，從第二輪起算
    gaps = [b - a for a, b in zip(times, times[1:])]
    # 每輪起點間隔約等於 interval；若沒有扣掉耗時會是 0.28 以上
    assert all(0.18 <= g < 0.26 for g in gaps), gaps


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


async def test_transitions_collected_through_poller(network, make_service):
    svc = make_service()
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "online")
        await wait_until(lambda: svc.count("/status") >= 4)  # 多輪拉取
        assert len(store.get_transitions("t1", 100)) == 6


@pytest.mark.parametrize("n", [3])
async def test_many_targets_independent(network, make_service, n):
    hosts = [f"h{i}" for i in range(n)]
    for h in hosts:
        network.add(h, make_service())
    async with running(make_config(hosts), network) as (store, _):
        for h in hosts:
            await reaches(store, "online", h)


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


async def test_overflow_float_marks_invalid_response(network, make_service):
    svc = make_service()
    svc.mode = "raw_status"
    svc.raw_body = json.dumps(svc.status).replace('"fps": 0.0', '"fps": 1e400').encode()
    assert b"1e400" in svc.raw_body
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "invalid_response")
