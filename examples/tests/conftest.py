"""pytest fixtures：啟動 mock_service、raw_mock 子程序，失敗時也會清理。

--import-mode=importlib 不會把測試目錄加入 sys.path，所以在這裡加入，
讓測試可以 ``from support import ...``。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from support import (MOCK_SERVICE_DIR, RAW_MOCK, MockService, Proc, RawMock,  # noqa: E402,F401
                     free_port, http_request, port_open, wait_until)


@pytest.fixture
def procs(tmp_path):
    started = []

    def spawn(args, name, env=None):
        proc = Proc([str(a) for a in args], tmp_path, f"{name}{len(started)}", env)
        started.append(proc)
        return proc

    yield spawn
    for proc in started:  # 失敗時也要終止
        proc.stop()


@pytest.fixture
def mock_service(procs):
    def start(profile, *, instance="mock-1", expect_ready=True, **opts):
        port, control_port = free_port(), free_port()
        args = [sys.executable, "-m", "mock_service", "--profile", profile,
                "--instance", instance, "--host", "127.0.0.1",
                "--port", port, "--control-port", control_port]
        for key, value in opts.items():
            args += [f"--{key.replace('_', '-')}", value]
        env = dict(os.environ, PYTHONPATH=str(MOCK_SERVICE_DIR))
        svc = MockService(procs(args, "mock", env), "127.0.0.1", port, control_port)
        if expect_ready:
            svc.wait_ready()
        return svc

    return start


@pytest.fixture
def raw_mock(procs):
    def start(mode, **opts):
        port = free_port()
        args = [sys.executable, RAW_MOCK, "--mode", mode, "--port", port]
        for key, value in opts.items():
            args += [f"--{key.replace('_', '-')}", value]
        mock = RawMock(procs(args, f"raw_{mode}"), port)
        if mode != "hang":
            wait_until(lambda: http_request(f"{mock.url}/topology")[0] in (200, 500),
                       10.0, what="raw_mock 啟動")
        else:
            wait_until(lambda: port_open(port), 10.0, what="raw_mock 啟動")
        return mock

    return start


