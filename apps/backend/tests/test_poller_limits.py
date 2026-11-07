"""回應大小上限 max_response_bytes 與逾時涵蓋讀取本文（SPEC §6.1）。"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx
import pytest
from poller_support import conn, reaches, running
from support import make_config, wait_until

pytestmark = pytest.mark.anyio

CHUNK = 100
LIMIT = 1000
MARKER = "BODY-CONTENT-MARKER"


class Body:
    """可計數的 async 本文產生器；記錄每個請求的本文被拉取幾次。"""

    def __init__(self, data: bytes = b"", *, chunk: bytes | None = None, delay: float = 0.0,
                 infinite: bool = False) -> None:
        self.data, self.chunk, self.delay, self.infinite = data, chunk, delay, infinite
        self.pulls: list[int] = []  # 每個請求一個計數

    def stream(self):
        index = len(self.pulls)
        self.pulls.append(0)

        async def gen():
            if self.data:
                self.pulls[index] += 1
                yield self.data
            while self.infinite:
                await asyncio.sleep(self.delay)  # 0 也讓出事件迴圈，如同真實網路讀取
                self.pulls[index] += 1
                yield self.chunk or b" " * CHUNK

        return gen()


def padded_status(svc, size: int) -> bytes:
    """把 /status 的 JSON 以尾端空白補到剛好 size 位元組（仍是合法 JSON）。"""
    body = json.dumps(svc.status).encode()
    assert len(body) <= size
    return body + b" " * (size - len(body))


def status_only(response_factory):
    return lambda request: response_factory() if request.url.path == "/status" else None


@pytest.mark.parametrize("declared", [True, False], ids=["content-length", "chunked"])
async def test_body_at_limit_online_and_one_byte_over_invalid(network, make_service, declared):
    svc = make_service()
    size = max(len(json.dumps(svc.topology)), len(json.dumps(svc.status))) + 50
    state = {"size": size}

    def respond():
        body = padded_status(svc, state["size"])
        if declared:
            return httpx.Response(200, content=body)
        return httpx.Response(200, content=Body(body).stream())

    svc.responder = status_only(respond)
    network.add("t1", svc)
    async with running(make_config(["t1"], max_bytes=size), network) as (store, _):
        await reaches(store, "online")
        before = store.get_view("t1")
        state["size"] = size + 1  # 剛好超過上限一個位元組
        await reaches(store, "invalid_response")
        after = store.get_view("t1")
        assert after.topology == before.topology  # 架構保留
        assert list(after.nodes) == list(before.nodes)
        assert all(n.color == "gray" and n.reason == "invalid_response"
                   for n in after.nodes.values())


async def test_content_length_over_limit_reads_no_body(network, make_service):
    svc = make_service()
    body = Body(b"x", infinite=True)
    svc.responder = status_only(lambda: httpx.Response(
        200, headers={"Content-Length": str(LIMIT * 10)}, content=body.stream()))
    network.add("t1", svc)
    async with running(make_config(["t1"], max_bytes=LIMIT * 5), network) as (store, _):
        await reaches(store, "invalid_response")
        await wait_until(lambda: len(body.pulls) >= 3)
    assert set(body.pulls) == {0}


async def test_unbounded_chunked_body_stops_near_limit(network, make_service):
    svc = make_service()
    svc.status["nodes"]["ingest"]["message"] = MARKER
    body = Body(json.dumps(svc.status).encode(), chunk=MARKER.encode() * 5, infinite=True)
    svc.responder = status_only(lambda: httpx.Response(200, content=body.stream()))
    network.add("t1", svc)
    config = make_config(["t1"], timeout=5, max_bytes=len(body.data) + LIMIT)
    start = time.monotonic()
    async with running(config, network) as (store, _):
        await reaches(store, "invalid_response")
        elapsed = time.monotonic() - start
        await wait_until(lambda: len(body.pulls) >= 3)
    assert elapsed < 1.0  # 遠小於 5 秒逾時：是上限而不是逾時讓讀取停止
    per_chunk = len(body.chunk)
    assert max(body.pulls) <= 1 + LIMIT // per_chunk + 1  # 開頭本文 + 上限內的 chunk + 超出的一個


async def test_topology_over_limit_is_invalid_and_not_adopted(network, make_service):
    svc = make_service()
    svc.responder = lambda request: (
        httpx.Response(200, content=Body(b"{", infinite=True).stream())
        if request.url.path == "/topology" else None
    )
    network.add("t1", svc)
    async with running(make_config(["t1"], max_bytes=LIMIT), network) as (store, _):
        await reaches(store, "invalid_response")
        assert store.get_view("t1").topology is None
        assert svc.count("/status") == 0


async def test_non_2xx_with_large_body_is_offline_without_reading(network, make_service):
    svc = make_service()
    body = Body(b"x", infinite=True)
    svc.responder = status_only(lambda: httpx.Response(
        500, headers={"Content-Length": str(LIMIT * 10)}, content=body.stream()))
    network.add("t1", svc)
    async with running(make_config(["t1"], max_bytes=LIMIT), network) as (store, _):
        await reaches(store, "offline")
        await wait_until(lambda: len(body.pulls) >= 2)
    assert set(body.pulls) == {0}


async def test_slow_drip_body_is_cut_by_request_timeout(network, make_service):
    svc = make_service()
    body = Body(b"{", chunk=b" ", delay=0.05, infinite=True)  # 每 50 ms 一個位元組
    svc.responder = status_only(lambda: httpx.Response(200, content=body.stream()))
    network.add("t1", svc)
    async with running(make_config(["t1"], timeout=0.2), network) as (store, _):
        start = time.monotonic()
        await reaches(store, "offline")
        assert time.monotonic() - start < 0.4
        assert max(body.pulls) < 10


async def test_oversized_target_does_not_delay_others(network, make_service):
    big, good = make_service(), make_service()
    big.responder = status_only(
        lambda: httpx.Response(200, content=Body(b"{", infinite=True).stream()))
    network.add("big", big)
    network.add("good", good)
    config = make_config(["big", "good"], interval=0.05, timeout=0.5, max_bytes=LIMIT * 50)
    async with running(config, network) as (store, _):
        await reaches(store, "online", "good")
        await reaches(store, "invalid_response", "big")
        start = time.monotonic()
        base = good.count("/status")
        await wait_until(lambda: good.count("/status") >= base + 3)
        assert time.monotonic() - start < 0.5
        assert conn(store, "good") == "online"


async def test_oversize_log_has_no_body_content(network, make_service, caplog):
    svc = make_service()
    body = Body(MARKER.encode() * 100)
    svc.responder = status_only(lambda: httpx.Response(200, content=body.stream()))
    network.add("t1", svc)
    with caplog.at_level(logging.INFO, logger="smart_health_backend"):
        async with running(make_config(["t1"], max_bytes=LIMIT), network) as (store, _):
            await reaches(store, "invalid_response")
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "超過上限" in warnings[0]
    assert MARKER not in warnings[0]


async def test_requests_uncompressed_body(network, make_service):
    """要求不壓縮，上限計算的就是實際傳輸的位元組。"""
    svc = make_service()
    seen: list[str | None] = []
    svc.responder = lambda request: seen.append(request.headers.get("accept-encoding"))
    network.add("t1", svc)
    async with running(make_config(["t1"]), network) as (store, _):
        await reaches(store, "online")
    assert seen and set(seen) == {"identity"}
