"""以真實子程序（mock_service、raw_mock）驗證後端端到端拉取。"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import time

import httpx
import pytest
from api_support import (MOCK_SERVICE_DIR, RAW_MOCK, Proc, api_client, free_port,
                         mock_service_args)

from smart_health_backend.app import create_app
from smart_health_backend.config import AppConfig, TargetConfig

pytestmark = pytest.mark.anyio

FAKE_SECRET = "mock-s3cret"
EDGE_FAST = dict(tick_interval_s=0.1, stuck_after_s=0.5, stale_after_s=2.0,
                 startup_grace_s=30, error_window_s=30)


@pytest.fixture
def procs(tmp_path):
    started: list[Proc] = []

    def start(args, name, env=None):
        proc = Proc(args, tmp_path, f"{name}{len(started)}", env)
        started.append(proc)
        return proc

    yield start
    for proc in reversed(started):
        proc.stop()


class Edge:
    def __init__(self, port: int, control_port: int) -> None:
        self.port, self.control_port = port, control_port
        self.url = f"http://127.0.0.1:{port}"

    def set_scenario(self, name: str) -> None:
        req = httpx.post(f"http://127.0.0.1:{self.control_port}/scenario", json={"name": name}, timeout=3)
        assert req.status_code == 200, req.text


@pytest.fixture
def start_edge(procs):
    def start(instance="edge-1") -> Edge:
        port, control = free_port(), free_port()
        env = dict(os.environ, PYTHONPATH=str(MOCK_SERVICE_DIR))
        procs(mock_service_args("edge", instance, port, control, **EDGE_FAST), "mock", env)
        edge = Edge(port, control)

        def ready():
            return httpx.get(f"{edge.url}/status", timeout=1).json()["nodes"]

        end = time.monotonic() + 10
        while time.monotonic() < end:
            try:
                if ready():
                    return edge
            except Exception:  # noqa: BLE001 - 啟動中連線失敗是預期
                pass
            time.sleep(0.05)
        pytest.fail("mock_service 啟動逾時")

    return start


@pytest.fixture
def start_raw(procs):
    def start(mode: str) -> str:
        port = free_port()
        procs([sys.executable, RAW_MOCK, "--mode", mode, "--port", port], f"raw_{mode}")
        end = time.monotonic() + 10
        while time.monotonic() < end:
            with socket.socket() as sock:
                sock.settimeout(0.5)
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    return f"http://127.0.0.1:{port}"
            time.sleep(0.05)
        pytest.fail("raw_mock 啟動逾時")

    return start


def config_for(targets: dict[str, str]) -> AppConfig:
    return AppConfig(
        poll_interval_s=0.2,
        request_timeout_s=0.5,
        evaluation_stale_after_s=10,
        history_limit=200,
        targets=[TargetConfig(id=i, name=i.upper(), base_url=u) for i, u in targets.items()],
    )


async def detail(client, tid="edge"):
    return (await client.get(f"/api/targets/{tid}")).json()


async def wait_detail(client, predicate, tid="edge", what="條件"):
    async def poll():
        return predicate(await detail(client, tid))

    deadline = asyncio.get_running_loop().time() + 15
    while asyncio.get_running_loop().time() < deadline:
        if await poll():
            return await detail(client, tid)
        await asyncio.sleep(0.05)
    pytest.fail(f"等待逾時：{what}")


def colors(body):
    return {n: v["color"] for n, v in body["nodes"].items()}


async def test_camera_down_scenario_through_backend(start_edge):
    edge = start_edge()
    app = create_app(config_for({"edge": edge.url}))
    async with api_client(app) as client:
        await wait_detail(client, lambda b: b["connection"] == "online" and b["summary_color"] == "green",
                          what="全綠")
        edge.set_scenario("camera_down")
        body = await wait_detail(client, lambda b: colors(b).get("ingest-worker") == "red", what="相機中斷")
        assert body["summary_color"] == "red"
        assert body["nodes"]["ingest-worker"]["state"] == "unavailable"
        assert [c for n, c in colors(body).items() if n != "ingest-worker"] == ["gray"] * 5
        trans = (await client.get("/api/targets/edge/transitions")).json()
        assert any(t["node"] == "ingest-worker" and t["to"] == "unavailable" for t in trans)


async def test_recovery_returns_to_green(start_edge):
    edge = start_edge()
    app = create_app(config_for({"edge": edge.url}))
    async with api_client(app) as client:
        await wait_detail(client, lambda b: b["summary_color"] == "green", what="全綠")
        edge.set_scenario("camera_down")
        await wait_detail(client, lambda b: b["summary_color"] == "red", what="紅")
        edge.set_scenario("normal")
        body = await wait_detail(client, lambda b: b["summary_color"] == "green", what="恢復全綠")
        assert set(colors(body).values()) == {"green"}
        trans = (await client.get("/api/targets/edge/transitions")).json()
        assert trans[0]["to"] == "ok"  # 最新在前


async def test_no_credentials_in_backend_response(start_edge):
    edge = start_edge()
    app = create_app(config_for({"edge": edge.url}))
    async with api_client(app) as client:
        await wait_detail(client, lambda b: b["summary_color"] == "green", what="全綠")
        for scenario in ("worker_fatal", "infer_exception", "read_errors", "publish_errors"):
            edge.set_scenario(scenario)
            await asyncio.sleep(0.8)
            texts = [(await client.get(p)).text for p in
                     ("/api/config", "/api/targets", "/api/targets/edge",
                      "/api/targets/edge/transitions", "/healthz")]
            for text in texts:
                assert FAKE_SECRET not in text, scenario


async def test_hang_mode_does_not_block_other_targets(start_edge, start_raw):
    edge = start_edge()
    raw_url = start_raw("hang")
    app = create_app(config_for({"edge": edge.url, "raw": raw_url}))
    async with api_client(app) as client:
        first = await wait_detail(client, lambda b: b["last_success_at"] is not None, what="edge 上線")
        await wait_detail(client, lambda b: b["connection"] == "offline", tid="raw", what="raw offline")
        await wait_detail(client, lambda b: b["last_success_at"] not in (None, first["last_success_at"]),
                          what="edge 持續更新")
        for _ in range(5):
            body = await detail(client)
            assert body["connection"] == "online"
            assert (await detail(client, "raw"))["connection"] == "offline"
            await asyncio.sleep(0.2)
