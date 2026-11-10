"""測試共用的假 clock、logger 擷取工具與 HealthMonitor fixture。

--import-mode=importlib 不會把測試目錄加入 sys.path，所以在這裡加入，
讓測試可以 ``from monitor_support import ...``。
"""
import logging
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402
from monitor_support import Records  # noqa: E402

from smart_health_record import HealthMonitor  # noqa: E402


class FakeClock:
    """可手動推進的假 monotonic clock。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def log_handler() -> ListHandler:
    return ListHandler()


@pytest.fixture
def logger(log_handler: ListHandler) -> logging.Logger:
    log = logging.getLogger("test.smart_health_record.recorder")
    log.handlers = [log_handler]
    log.setLevel(logging.DEBUG)
    log.propagate = False
    return log


@pytest.fixture
def rec(clock, logger):
    from smart_health_record import NodeRecorder

    return NodeRecorder("n1", clock, logger)


class FakeWallClock:
    """可手動調整的假 wall clock（含時區）。"""

    def __init__(self) -> None:
        import datetime as _dt

        self.tz = _dt.timezone(_dt.timedelta(hours=8))
        self.now = _dt.datetime(2026, 11, 5, 10, 0, 0, tzinfo=self.tz)

    def __call__(self):
        return self.now

    def advance(self, seconds: float) -> None:
        import datetime as _dt

        self.now += _dt.timedelta(seconds=seconds)


@pytest.fixture
def wall() -> FakeWallClock:
    return FakeWallClock()


def build_edge(monitor, stream_sink=lambda: True, messaging=lambda: True):
    """依 contract/fixtures/topology_edge.json 建立 edge 架構。"""
    monitor.add_lane("main", "Main", sequential=True)
    monitor.add_lane("ingest-bg", "Ingest worker", parent="ingest")
    monitor.add_lane("stream-bg", "Stream output", parent="stream")
    monitor.add_node("ingest-worker", "Ingest worker", "ingest-bg")
    monitor.add_node("ingest", "Ingest", "main", upstream=["ingest-worker"])
    monitor.add_node("infer", "Infer", "main", upstream=["ingest"])
    monitor.add_node("stream", "Stream", "main", upstream=["infer"])
    monitor.add_node("stream-output", "Stream output", "stream-bg", upstream=["stream"],
                     dependencies={"stream_sink": stream_sink})
    monitor.add_node("publish", "Publish", "main", upstream=["infer"],
                     dependencies={"messaging": messaging})
    return monitor


@pytest.fixture
def edge_builder():
    return build_edge


@pytest.fixture
def records():
    return Records()


@pytest.fixture
def log(records):
    lg = logging.getLogger("test.smart_health_record.monitor")
    lg.handlers = [records]
    lg.setLevel(logging.DEBUG)
    lg.propagate = False
    return lg


@pytest.fixture
def make(clock, wall, log):
    """建立監控器；teardown 一定停止執行緒。"""
    created = []

    def factory(instance="inst", **kw):
        kw.setdefault("clock", clock)
        kw.setdefault("wall_clock", wall)
        kw.setdefault("logger", log)
        m = HealthMonitor("edge", instance, **kw)
        created.append(m)
        return m

    yield factory
    for m in created:
        m.stop()


@pytest.fixture
def gates():
    """阻塞用 Event；teardown 一律釋放，避免殘留執行緒。"""
    events = []

    def new():
        e = threading.Event()
        events.append(e)
        return e

    yield new
    for e in events:
        e.set()
