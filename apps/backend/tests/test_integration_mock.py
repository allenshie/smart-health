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

    async def set_scenario(self, name: str) -> None:
        """透過控制接口切換情境；用 AsyncClient，避免阻塞事件迴圈（後端 poller 也在其中）。"""
        async with httpx.AsyncClient(timeout=3) as http:
            resp = await http.post(f"http://127.0.0.1:{self.control_port}/scenario", json={"name": name})
        assert resp.status_code == 200, resp.text


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


async def wait_detail(client, predicate, tid="edge", what="條件", timeout=15.0):
    async def poll():
        return predicate(await detail(client, tid))

    deadline = asyncio.get_running_loop().time() + timeout
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
        await edge.set_scenario("camera_down")
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
        await edge.set_scenario("camera_down")
        await wait_detail(client, lambda b: b["summary_color"] == "red", what="紅")
        await edge.set_scenario("normal")
        body = await wait_detail(client, lambda b: b["summary_color"] == "green", what="恢復全綠")
        assert set(colors(body).values()) == {"green"}
        trans = (await client.get("/api/targets/edge/transitions")).json()
        assert trans[0]["to"] == "ok"  # 最新在前


# 情境 -> 會帶出遮蔽後帳密訊息的節點（以 mock 的實際行為為準）
MASKED_NODE = {
    "worker_fatal": "ingest-worker",
    "read_errors": "ingest-worker",
    "infer_exception": "infer",
    "publish_errors": "publish",
}
MASK_WAIT_S = 15.0  # 等遮蔽後訊息出現的上限；改成 0 可驗證測試會失敗


@pytest.mark.parametrize("scenario,node", list(MASKED_NODE.items()))
async def test_no_credentials_in_backend_response(start_edge, scenario, node):
    # 每個情境用全新的 mock：錯誤窗口內的舊訊息不會殘留到下一個情境
    edge = start_edge()
    app = create_app(config_for({"edge": edge.url}))
    async with api_client(app) as client:
        await wait_detail(client, lambda b: b["summary_color"] == "green", what="全綠")
        await edge.set_scenario(scenario)
        # 先確認帶帳密的訊息已到達後端（且已遮蔽），才檢查回應不含帳密
        await wait_detail(client, lambda b: "***" in (b["nodes"][node]["message"] or ""),
                          what=f"{scenario}：{node} 出現遮蔽後的訊息", timeout=MASK_WAIT_S)
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
