"""FastAPI 應用程式：lifespan 管理 poller，uvicorn 進入點為 smart_health_backend.app:app。"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import AppConfig, load_config
from .poller import Poller
from .routes import router
from .store import TargetStore

CONFIG_ENV = "SMART_HEALTH_CONFIG"
DEFAULT_CONFIG_PATH = "config/targets.yaml"


def create_app(
    config: AppConfig,
    static_dir: Path | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """建立應用程式。transport 僅供測試注入假網路。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = httpx.AsyncClient(transport=transport)
        store = TargetStore(config)
        poller = Poller(config, store, client)
        run_task = asyncio.create_task(poller.run(), name="poller-run")
        app.state.client, app.state.store = client, store
        app.state.poller, app.state.run_task = poller, run_task
        try:
            yield
        finally:
            # 不取消 run_task：先 stop() 讓它自行收尾，再等它結束
            await poller.stop()
            await asyncio.gather(run_task, return_exceptions=True)  # run 先前意外結束也不阻礙關閉
            await client.aclose()

    app = FastAPI(title="smart_health backend", lifespan=lifespan)
    app.state.config = config
    app.include_router(router)
    if static_dir is not None:
        # 必須在所有 API 路由之後掛載
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


_cached_app: FastAPI | None = None


def __getattr__(name: str) -> Any:
    """延後建立 uvicorn 進入點的 app，避免 import 本模組就讀設定檔（PEP 562）。"""
    global _cached_app
    if name != "app":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if _cached_app is None:
        path = Path(os.environ.get(CONFIG_ENV, DEFAULT_CONFIG_PATH))
        _cached_app = create_app(load_config(path))
    return _cached_app
