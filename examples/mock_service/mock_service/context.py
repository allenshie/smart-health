"""模擬執行緒共用的情境與停止訊號。每次重建都建立新的 context。"""
import threading


class SimContext:
    def __init__(self, scenario: str) -> None:
        self._cond = threading.Condition()
        self._scenario = scenario
        self._version = 0
        self._stopped = False

    @property
    def scenario(self) -> str:
        return self._scenario

    @property
    def stopped(self) -> bool:
        return self._stopped

    def set_scenario(self, name: str) -> None:
        with self._cond:
            self._scenario = name
            self._version += 1
            self._cond.notify_all()

    def stop(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify_all()

    def wait(self, timeout: float) -> None:
        """休息 timeout 秒；情境改變或停止時提早返回。"""
        with self._cond:
            version = self._version
            self._cond.wait_for(lambda: self._stopped or self._version != version, timeout)

    def wait_while(self, name: str) -> None:
        """阻塞到情境不再是 name 或停止（用來模擬卡住，但不會卡死程序）。"""
        with self._cond:
            self._cond.wait_for(lambda: self._stopped or self._scenario != name)
