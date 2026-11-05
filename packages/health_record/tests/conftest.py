"""測試共用的假 clock 與 logger 擷取工具。"""
import logging

import pytest


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
