"""uvicorn 進入點（PEP 562 的模組 app）依 SMART_HEALTH_STATIC_DIR 提供前端靜態檔（SPEC §6.2 的 GET /）。"""

from __future__ import annotations

import importlib

import pytest
from api_support import api_client

pytestmark = pytest.mark.anyio

# 連線會立即被拒絕的位址：lifespan 會啟動 poller，但不連外部網路
CONFIG_TEXT = "targets:\n  - id: a\n    name: A\n    base_url: http://127.0.0.1:9\n"
INDEX_HTML = "<!doctype html><title>前端</title><div id=root>前端首頁</div>"


@pytest.fixture
def entry_module(tmp_path, monkeypatch):
    """設定檔就緒、快取已清空的進入點模組；測試結束後也清空快取。"""
    cfg = tmp_path / "targets.yaml"
    cfg.write_text(CONFIG_TEXT, encoding="utf-8")
    monkeypatch.setenv("SMART_HEALTH_CONFIG", str(cfg))
    monkeypatch.delenv("SMART_HEALTH_STATIC_DIR", raising=False)
    module = importlib.reload(importlib.import_module("smart_health_backend.app"))
    yield module
    module._cached_app = None


def static_dir(tmp_path):
    path = tmp_path / "static"
    path.mkdir()
    (path / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    return path


async def test_static_dir_env_serves_index_and_keeps_api(entry_module, tmp_path, monkeypatch):
    monkeypatch.setenv("SMART_HEALTH_STATIC_DIR", str(static_dir(tmp_path)))
    app = getattr(entry_module, "app")
    async with api_client(app) as client:
        page = await client.get("/")
        health = await client.get("/healthz")
        cfg = await client.get("/api/config")
        targets = await client.get("/api/targets")
        missing = await client.get("/api/nothing")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "前端首頁" in page.text
    assert health.status_code == 200 and health.json() == {"status": "ok"}
    assert cfg.json() == {"poll_interval_s": 5}
    assert [t["id"] for t in targets.json()] == ["a"]
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/json")


async def test_without_static_dir_env_root_is_404(entry_module):
    app = getattr(entry_module, "app")
    async with api_client(app) as client:
        page = await client.get("/")
        health = await client.get("/healthz")
    assert page.status_code == 404
    assert health.status_code == 200


def test_missing_static_dir_fails_at_startup(entry_module, tmp_path, monkeypatch):
    missing = tmp_path / "no-such-dir"
    monkeypatch.setenv("SMART_HEALTH_STATIC_DIR", str(missing))
    with pytest.raises(RuntimeError, match="does not exist"):
        getattr(entry_module, "app")
    assert entry_module._cached_app is None
