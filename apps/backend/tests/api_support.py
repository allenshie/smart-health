"""API 測試共用工具：不經 TestClient 的 ASGI 用戶端與子程序管理。

starlette 的 TestClient 在 -W error 下會因 httpx 棄用警告而無法 import，
所以改用 httpx.ASGITransport，並手動進入 lifespan。
"""

from __future__ import annotations

import contextlib
import copy
import socket
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[3]
MOCK_SERVICE_DIR = ROOT / "examples" / "mock_service"
RAW_MOCK = ROOT / "examples" / "raw_mock" / "raw_mock.py"


@contextlib.asynccontextmanager
async def api_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """進入 app 的 lifespan（啟動 poller），並提供呼叫 app 的用戶端。"""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


def transitions_status(status: dict, prefix: str, count: int) -> dict:
    """複製 status，recent_transitions 換成 count 筆（新到舊）互不相同的 infer 變化。"""
    doc = copy.deepcopy(status)
    doc["recent_transitions"] = [
        {
            "node": "infer",
            "from": "ok",
            "to": "waiting" if i % 2 else "ok",
            "reason": None,
            "at": f"2026-11-05T10:{prefix}:{count - i:02d}+08:00",
        }
        for i in range(count)
    ]
    return doc


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Proc:
    """以子程序執行真實 CLI；stop() 保證結束。"""

    def __init__(self, args: list, tmp_path: Path, name: str, env: dict | None = None) -> None:
        self._out = open(tmp_path / f"{name}.log", "wb")
        self.popen = subprocess.Popen(
            [str(a) for a in args],
            stdout=self._out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
        )

    def stop(self) -> None:
        if self.popen.poll() is None:
            self.popen.terminate()
            try:
                self.popen.wait(8)
            except subprocess.TimeoutExpired:
                self.popen.kill()
                self.popen.wait()
        self._out.close()


def mock_service_args(profile: str, instance: str, port: int, control_port: int, **opts) -> list:
    args = [
        sys.executable, "-m", "mock_service", "--profile", profile, "--instance", instance,
        "--host", "127.0.0.1", "--port", port, "--control-port", control_port,
    ]
    for key, value in opts.items():
        args += [f"--{key.replace('_', '-')}", value]
    return args
