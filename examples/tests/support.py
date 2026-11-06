"""模擬服務測試的共用工具：啟動子程序、真實 HTTP 讀取、有上限的輪詢。

測試一律以子程序執行真實 CLI，並透過真實 HTTP 互動。
"""
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MOCK_SERVICE_DIR = ROOT / "examples" / "mock_service"
RAW_MOCK = ROOT / "examples" / "raw_mock" / "raw_mock.py"
FIXTURES = ROOT / "contract" / "fixtures"
SCHEMAS = ROOT / "contract"

# 讓測試能直接 import mock_service.scenarios 取得常數（只含常數，不含執行邏輯）
if str(MOCK_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(MOCK_SERVICE_DIR))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def http_request(url, *, method="GET", body=None, raw_body=None, timeout=3.0):
    """回傳 (HTTP 狀態碼, 內容文字)；連線失敗時拋例外。"""
    data = raw_body if raw_body is not None else (
        None if body is None else json.dumps(body).encode("utf-8"))
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        with err:
            return err.code, err.read().decode("utf-8")


def get_json(url, timeout=3.0):
    code, text = http_request(url, timeout=timeout)
    return code, json.loads(text)


def wait_until(predicate, timeout=15.0, interval=0.05, what="條件"):
    """輪詢到 predicate 為真；predicate 拋例外視為尚未符合。逾時則 fail。"""
    deadline = time.monotonic() + timeout
    last = None
    while True:
        try:
            result = predicate()
            if result:
                return result
            last = result
        except Exception as exc:  # noqa: BLE001 - 重建期間連線失敗是預期
            last = exc
        if time.monotonic() >= deadline:
            pytest.fail(f"等待逾時 {timeout}s：{what}（最後結果：{last!r}）")
        time.sleep(interval)


def assert_holds(predicate, what, reads=8, gap=0.1):
    """連續多次讀取都要符合，避免只是短暫符合。"""
    for i in range(reads):
        assert predicate(), f"第 {i + 1} 次讀取不符合：{what}"
        time.sleep(gap)


class Proc:
    def __init__(self, args, tmp_path, name, env=None):
        self.out_path = tmp_path / f"{name}.out"
        self.err_path = tmp_path / f"{name}.err"
        self._out = open(self.out_path, "wb")
        self._err = open(self.err_path, "wb")
        self.popen = subprocess.Popen(args, stdout=self._out, stderr=self._err,
                                      stdin=subprocess.DEVNULL, env=env)

    def stop(self, timeout=8.0):
        """SIGTERM 後等待結束並回傳 returncode；逾時改 kill。"""
        if self.popen.poll() is None:
            self.popen.terminate()
            try:
                self.popen.wait(timeout)
            except subprocess.TimeoutExpired:
                self.popen.kill()
                self.popen.wait()
        self._out.close()
        self._err.close()
        return self.popen.returncode

    def output(self):
        return (self.out_path.read_text(errors="replace")
                + self.err_path.read_text(errors="replace"))


class MockService:
    def __init__(self, proc, host, port, control_port):
        self.proc, self.port, self.control_port = proc, port, control_port
        self.url = f"http://{host}:{port}"
        self.control_url = f"http://{host}:{control_port}"

    def status(self):
        return get_json(f"{self.url}/status")[1]

    def topology(self):
        return get_json(f"{self.url}/topology")[1]

    def states(self):
        return {n: v["state"] for n, v in self.status()["nodes"].items()}

    def reasons(self):
        return {n: v["reason"] for n, v in self.status()["nodes"].items()}

    def scenario(self):
        return get_json(f"{self.control_url}/scenario")[1]["name"]

    def set_scenario(self, name):
        code, body = http_request(f"{self.control_url}/scenario", method="POST",
                                  body={"name": name})
        assert code == 200, (code, body)
        assert json.loads(body) == {"name": name}

    def wait_states(self, expected, timeout=15.0):
        wait_until(lambda: self.states() == expected, timeout,
                   what=f"狀態 {expected}")

    def wait_ready(self):
        wait_until(lambda: self.scenario() == "normal" and self.status()["nodes"],
                   10.0, what="mock 啟動")


class RawMock:
    def __init__(self, proc, port):
        self.proc, self.port = proc, port
        self.url = f"http://127.0.0.1:{port}"


def port_open(port):
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0
