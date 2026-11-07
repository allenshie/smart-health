"""後端 log 設定：root 沒有 handler 時才設定，httpx／httpcore 只輸出 WARNING 以上。"""

from __future__ import annotations

import logging
import re
import subprocess
import sys

import httpx
import pytest
from api_support import api_client
from support import make_config, wait_until

from smart_health_backend.app import create_app

pytestmark = pytest.mark.anyio

STAMP = r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} "


def line(level: str, text: str) -> str:
    """一行 log 的 regex：時間、level、logger 名稱、訊息。"""
    return STAMP + f"{level} smart_health_backend\\.poller: {re.escape(text)}"


@pytest.fixture
def bare_root(monkeypatch):
    """回傳一個函式：在測試本體內暫時拿掉 root logger 的 handler，模擬 uvicorn 啟動時的狀態。

    pytest 在 call 階段才把自己的 handler 掛到 root，所以必須在測試本體內呼叫。
    """
    root = logging.getLogger()

    def clear() -> logging.Logger:
        monkeypatch.setattr(root, "handlers", [])
        monkeypatch.setattr(root, "level", logging.WARNING)
        return root

    yield clear
    for handler in root.handlers:
        handler.close()


@pytest.fixture(autouse=True)
def restore_library_levels():
    names = ("httpx", "httpcore")
    saved = {n: logging.getLogger(n).level for n in names}
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


async def test_poller_info_is_emitted_when_root_unconfigured(bare_root, capsys, network,
                                                             make_service):
    service = make_service()
    service.mode = "http500"
    network.add("edge-a", service)
    root = bare_root()
    app = create_app(make_config(["edge-a"]), transport=httpx.MockTransport(network.handler))
    assert root.level == logging.INFO and len(root.handlers) == 1
    async with api_client(app):
        store = app.state.store
        await wait_until(lambda: store.get_view("edge-a").connection == "offline")
        service.mode = "ok"
        await wait_until(lambda: store.get_view("edge-a").connection == "online")
    err = capsys.readouterr().err
    assert re.search(line("WARNING", "目標 edge-a 連線狀態變為 offline"), err, re.M)
    assert re.search(line("INFO", "目標 edge-a 已恢復 online"), err, re.M), err


def test_existing_root_handler_is_kept(monkeypatch):
    root = logging.getLogger()
    custom = logging.NullHandler()
    monkeypatch.setattr(root, "handlers", [custom])
    monkeypatch.setattr(root, "level", logging.ERROR)
    create_app(make_config(["edge-a"]))
    assert root.handlers == [custom]
    assert root.level == logging.ERROR


def test_http_client_loggers_are_warning(bare_root):
    bare_root()
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.NOTSET)
    create_app(make_config(["edge-a"]))
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).level == logging.WARNING, name


def test_import_does_not_configure_logging():
    code = (
        "import logging, smart_health_backend.app as m; "
        "r = logging.getLogger(); "
        "print(len(r.handlers), r.level, logging.getLogger('httpx').level)"
    )
    out = subprocess.run([sys.executable, "-W", "error", "-c", code], capture_output=True,
                         text=True, timeout=30, check=True).stdout.split()
    assert out == ["0", str(logging.WARNING), str(logging.NOTSET)]
