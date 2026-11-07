"""HealthMonitor 測試的共用工具：讀取契約、有上限的等待、log 擷取。

fixture（records、log、make、gates）在 conftest.py。
"""
import json
import logging
import threading
from pathlib import Path

from jsonschema import Draft202012Validator

CONTRACT = Path(__file__).resolve().parents[3] / "contract"
WAIT_S = 5.0


def load(name):
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


def wait_until(pred, timeout=WAIT_S):
    gate = threading.Event()
    waited = 0.0
    while not pred():
        if waited >= timeout:
            raise AssertionError("條件在時限內未成立")
        gate.wait(0.005)
        waited += 0.005
    return True


def call_with_timeout(fn, timeout=WAIT_S):
    """在另一條執行緒呼叫 fn，逾時代表被卡住。"""
    box = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - 轉交給測試主執行緒
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    assert not t.is_alive(), "呼叫被卡住"
    if "error" in box:
        raise box["error"]
    return box["value"]


class Records(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def texts(self):
        return [r.getMessage() for r in self.records]

    def at(self, level):
        return [r for r in self.records if r.levelno == level]


def simple(m, **node_kw):
    m.add_lane("main", "Main")
    return m.add_node("a", "A", "main", **node_kw)


def status_validator():
    return Draft202012Validator(load("status.schema.json"))


def _eval_threads(instance):
    return [t for t in threading.enumerate()
            if t.name.startswith("smart-health-") and instance in t.name and t.is_alive()]
