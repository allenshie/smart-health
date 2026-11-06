"""測試共用工具：契約 fixtures 讀取、假服務與等待。"""

from __future__ import annotations

import asyncio
import copy
import json
import time
from collections.abc import Callable
from pathlib import Path

import httpx
from smart_health_backend.config import AppConfig, TargetConfig

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "contract" / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeService:
    """可程式化的被監控服務；用 MockTransport 接上 httpx。"""

    def __init__(self, topology: dict, status: dict) -> None:
        self.topology = copy.deepcopy(topology)
        self.status = copy.deepcopy(status)
        self.mode = "ok"  # ok | hang | http500 | redirect | raw_status | raw_topology
        self.raw_body: bytes = b""
        self.requests: list[str] = []

    def count(self, path: str) -> int:
        return sum(1 for r in self.requests if r == path)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        if self.mode == "hang":
            await asyncio.sleep(3600)
        if self.mode == "http500":
            return httpx.Response(500, json={"error": "boom"})
        if self.mode == "redirect":
            return httpx.Response(302, headers={"location": "http://elsewhere.test/status"})
        if self.mode == "raw_status" and path == "/status":
            return httpx.Response(200, content=self.raw_body)
        if self.mode == "raw_topology" and path == "/topology":
            return httpx.Response(200, content=self.raw_body)
        if path == "/topology":
            return httpx.Response(200, json=self.topology)
        if path == "/status":
            return httpx.Response(200, json=self.status)
        return httpx.Response(404)


class FakeNetwork:
    """依 host 分派到各 FakeService，並記錄所有請求的 host。"""

    def __init__(self) -> None:
        self.services: dict[str, FakeService] = {}
        self.hosts_seen: list[str] = []

    def add(self, host: str, service: FakeService) -> None:
        self.services[host] = service

    async def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        self.hosts_seen.append(host)
        service = self.services.get(host)
        if service is None:
            return httpx.Response(404)
        return await service.handle(request)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def make_config(
    hosts: list[str],
    *,
    interval: float = 0.05,
    timeout: float = 0.05,
    stale: float = 10,
    history: int = 200,
) -> AppConfig:
    return AppConfig(
        poll_interval_s=interval,
        request_timeout_s=timeout,
        evaluation_stale_after_s=stale,
        history_limit=history,
        targets=[TargetConfig(id=h, name=h.upper(), base_url=f"http://{h}:8000") for h in hosts],
    )


async def wait_until(predicate: Callable[[], bool], limit: float = 3.0) -> None:
    """輪詢到條件成立；超過上限就失敗，不用固定 sleep。"""
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("等待條件逾時")
