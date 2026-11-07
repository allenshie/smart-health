"""後端 API（SPEC §6.2）：用 FakeNetwork 注入假服務，不連真實網路。"""

from __future__ import annotations

import asyncio
import importlib
import logging
import sys

import httpx
import pytest
from api_support import api_client, transitions_status
from fastapi import FastAPI
from support import make_config, wait_until

from smart_health_backend.app import create_app
from smart_health_backend.config import ConfigError

pytestmark = pytest.mark.anyio

ALL_PATHS = ["/api/config", "/api/targets", "/api/targets/edge-a", "/api/targets/edge-a/transitions", "/healthz"]


def build(network, make_service, **config_kwargs):
    service = make_service()
    network.add("edge-a", service)
    config = make_config(["edge-a"], **config_kwargs)
    app = create_app(config, transport=httpx.MockTransport(network.handler))
    return app, service, config


async def online(app):
    await wait_until(lambda: app.state.store.list_views()[0].connection == "online")


async def test_get_config(network, make_service):
    app, _, _ = build(network, make_service, interval=0.2)
    async with api_client(app) as client:
        resp = await client.get("/api/config")
    assert resp.status_code == 200
    assert resp.json() == {"poll_interval_s": 0.2}


async def test_targets_list_shape(network, make_service):
    network.add("edge-b", make_service())
    config = make_config(["edge-b", "edge-a"])
    network.add("edge-a", make_service())
    app = create_app(config, transport=httpx.MockTransport(network.handler))
    async with api_client(app) as client:
        resp = await client.get("/api/targets")
    body = resp.json()
    assert resp.status_code == 200
    assert [t["id"] for t in body] == ["edge-b", "edge-a"]
    assert set(body[0]) == {"id", "name", "connection", "summary_color", "last_success_at"}


async def test_target_detail_has_topology_and_colors(network, make_service):
    app, _, _ = build(network, make_service)
    async with api_client(app) as client:
        await online(app)
        body = (await client.get("/api/targets/edge-a")).json()
    assert body["topology"]["service"] == "edge"
    assert [n["id"] for n in body["topology"]["nodes"]]
    assert body["nodes"]["ingest-worker"]["color"] == "red"
    assert body["nodes"]["infer"]["color"] == "gray"
    assert body["summary_color"] == "red"
    assert set(body["nodes"]["infer"]) == {"state", "reason", "message", "since", "metrics", "color"}


async def test_unknown_target_returns_404(network, make_service):
    app, _, _ = build(network, make_service)
    async with api_client(app) as client:
        for path in ("/api/targets/nope", "/api/targets/nope/transitions"):
            resp = await client.get(path)
            assert resp.status_code == 404
            assert resp.json() == {"detail": "target_not_found"}


async def test_unknown_api_path_returns_404_json_even_with_static(network, make_service, tmp_path):
    (tmp_path / "index.html").write_text("<h1>頁面</h1>", encoding="utf-8")
    network.add("edge-a", make_service())
    app = create_app(make_config(["edge-a"]), tmp_path, transport=httpx.MockTransport(network.handler))
    async with api_client(app) as client:
        missing = await client.get("/api/nothing")
        page = await client.get("/")
        health = await client.get("/healthz")
        cfg = await client.get("/api/config")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/json")
    assert "頁面" in page.text
    assert health.status_code == 200
    assert cfg.json() == {"poll_interval_s": 0.05}


async def test_transitions_limit_default_and_max(network, make_service, status_edge):
    app, service, _ = build(network, make_service, history=70)
    path = "/api/targets/edge-a/transitions"
    service.status = transitions_status(status_edge, "01", 50)
    async with api_client(app) as client:
        await wait_until(lambda: len(app.state.store.get_transitions("edge-a", 1000)) == 50)
        service.status = transitions_status(status_edge, "02", 50)
        await wait_until(lambda: len(app.state.store.get_transitions("edge-a", 1000)) == 70)
        default = (await client.get(path)).json()
        over = (await client.get(path, params={"limit": 1000})).json()
        five = (await client.get(path, params={"limit": 5})).json()
    assert len(default) == 50
    assert len(over) == 70  # 壓到 history_limit
    assert len(five) == 5
    assert default[0]["at"] == "2026-11-05T10:02:50+08:00"  # 最新在前
    assert set(default[0]) == {"node", "from", "to", "reason", "at"}  # 鍵為 from，不是 from_


@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5"])
async def test_transitions_limit_below_one_returns_422(network, make_service, value):
    app, _, _ = build(network, make_service)
    async with api_client(app) as client:
        resp = await client.get("/api/targets/edge-a/transitions", params={"limit": value})
        unknown = await client.get("/api/targets/nope/transitions", params={"limit": value})
    assert resp.status_code == 422
    assert unknown.status_code == 422


async def test_response_excludes_base_url(network, make_service):
    app, service, config = build(network, make_service)
    service.mode = "raw_status"
    service.raw_body = b"http://edge-a:8000 not json"
    async with api_client(app) as client:
        await wait_until(lambda: app.state.store.list_views()[0].connection == "invalid_response")
        texts = [(await client.get(p)).text for p in ALL_PATHS]
    for text in texts:
        assert config.targets[0].base_url not in text
        assert "edge-a:8000" not in text
        assert "not json" not in text


async def test_healthz(network, make_service):
    app, _, _ = build(network, make_service)
    async with api_client(app) as client:
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        # run task 意外結束時回 503
        app.state.run_task.cancel()
        await asyncio.gather(app.state.run_task, return_exceptions=True)
        down = await client.get("/healthz")
    assert down.status_code == 503
    assert down.json() == {"status": "poller_stopped"}


async def test_app_starts_and_stops_poller(network, make_service):
    app, service, _ = build(network, make_service)
    async with api_client(app):
        await wait_until(lambda: service.count("/status") >= 2)
        client = app.state.client
        assert not client.is_closed
        assert any(t.get_name() == "poll-edge-a" for t in asyncio.all_tasks())
    assert client.is_closed
    assert app.state.run_task.done()
    assert not [t for t in asyncio.all_tasks() if t.get_name().startswith("poll-")]
    seen = service.count("/status")
    await asyncio.sleep(0.15)
    assert service.count("/status") == seen


async def test_lifespan_restarts_cleanly(network, make_service):
    app, service, _ = build(network, make_service)
    for _ in range(2):
        async with api_client(app):
            await wait_until(lambda: service.count("/status") >= 1)
            service.requests.clear()
    assert not [t for t in asyncio.all_tasks() if t.get_name().startswith("poll-")]


def test_module_app_loads_config_lazily(tmp_path, monkeypatch):
    cfg = tmp_path / "targets.yaml"
    cfg.write_text("targets:\n  - id: a\n    name: A\n    base_url: http://a:1\n", encoding="utf-8")
    monkeypatch.setenv("SMART_HEALTH_CONFIG", str(cfg))
    module = importlib.import_module("smart_health_backend.app")
    module = importlib.reload(module)
    app = getattr(module, "app")
    assert isinstance(app, FastAPI)
    assert getattr(module, "app") is app  # 快取
    with pytest.raises(AttributeError):
        getattr(module, "no_such_attr")


def test_module_app_invalid_config_raises(tmp_path, monkeypatch):
    cfg = tmp_path / "targets.yaml"
    cfg.write_text("poll_interval_s: -1\ntargets: []\n", encoding="utf-8")
    monkeypatch.setenv("SMART_HEALTH_CONFIG", str(cfg))
    module = importlib.reload(importlib.import_module("smart_health_backend.app"))
    with pytest.raises(ConfigError, match="poll_interval_s"):
        getattr(module, "app")


def test_import_create_app_does_not_read_config(monkeypatch):
    monkeypatch.setenv("SMART_HEALTH_CONFIG", "/nonexistent/x.yaml")
    monkeypatch.delitem(sys.modules, "smart_health_backend.app", raising=False)
    module = importlib.import_module("smart_health_backend.app")
    assert callable(module.create_app)


async def test_docs_endpoints_are_disabled(network, make_service):
    app, _, _ = build(network, make_service)
    async with api_client(app) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await client.get(path)).status_code == 404, path


async def test_run_task_crash_is_logged(network, make_service, monkeypatch, caplog):
    async def boom(self):
        raise RuntimeError("poller 內部錯誤 XYZ")

    monkeypatch.setattr(create_app.__globals__["Poller"], "run", boom)
    app, _, _ = build(network, make_service)
    with caplog.at_level(logging.ERROR):
        async with api_client(app) as client:
            await wait_until(lambda: app.state.run_task.done())
            await asyncio.sleep(0)  # 讓 done callback 執行
            assert (await client.get("/healthz")).status_code == 503
    records = [r for r in caplog.records if r.levelno >= logging.ERROR and "XYZ" in r.getMessage() + str(r.exc_info)]
    assert records, "run task 意外結束時必須記錄 error 與例外資訊"


async def test_lifespan_startup_failure_closes_client(network, make_service, monkeypatch):
    import httpx as httpx_module

    created = []

    class RecordingClient(httpx_module.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

    def fail(*args, **kwargs):
        raise RuntimeError("store 建立失敗")

    # 其他測試會重新載入模組，所以直接改 create_app 實際使用的全域字典
    app_globals = create_app.__globals__
    monkeypatch.setitem(app_globals, "httpx", type("H", (), {"AsyncClient": RecordingClient}))
    monkeypatch.setitem(app_globals, "TargetStore", fail)
    app, _, _ = build(network, make_service)
    with pytest.raises(RuntimeError, match="store 建立失敗"):
        async with api_client(app):
            pass
    assert len(created) == 1
    assert created[0].is_closed
