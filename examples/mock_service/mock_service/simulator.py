"""模擬器：管理 HealthMonitor、StatusServer 與模擬執行緒的生命週期。

``starting`` 情境會把三者整組停掉再重建（函式庫沒有重置 API），綁定相同 port。
其他情境只改 context 內的情境名稱，由模擬執行緒自行反應。
"""
import threading
from types import ModuleType
from typing import List

from smart_health_record import StatusServer

from .context import SimContext
from .scenarios import STARTING
from .settings import Settings

_JOIN_TIMEOUT_S = 5.0


class UnknownScenario(ValueError):
    pass


class _Runtime:
    """一組 monitor + server + 模擬執行緒。"""

    def __init__(self, profile: ModuleType, settings: Settings, scenario: str) -> None:
        self.ctx = SimContext(scenario)
        built = profile.build(settings, self.ctx)
        self.monitor = built.monitor
        self.server = StatusServer(self.monitor, port=settings.port, host=settings.host)
        self.threads: List[threading.Thread] = [
            threading.Thread(target=loop, daemon=True, name=f"mock-sim-{i}")
            for i, loop in enumerate(built.loops)
        ]

    def start(self) -> None:
        self.server.start()  # 綁定失敗拋 OSError，此時尚未啟動其他東西
        self.monitor.start()
        for thread in self.threads:
            thread.start()

    def stop(self) -> None:
        self.ctx.stop()  # 同時喚醒卡住的 infer
        for thread in self.threads:
            if thread.is_alive():
                thread.join(_JOIN_TIMEOUT_S)
        self.server.stop()
        self.monitor.stop()


class Simulator:
    def __init__(self, profile: ModuleType, settings: Settings) -> None:
        self._profile = profile
        self._settings = settings
        self._lock = threading.Lock()  # 序列化切換與重建；讀取情境不用鎖
        self._scenario = "normal"
        self._runtime = _Runtime(profile, settings, self._scenario)

    @property
    def scenarios(self):
        return self._profile.SCENARIOS

    @property
    def scenario(self) -> str:
        return self._scenario

    def start(self) -> None:
        self._runtime.start()

    def set_scenario(self, name: str) -> None:
        if name not in self._profile.SCENARIOS:
            raise UnknownScenario(f"未知情境：{name}")
        with self._lock:
            if name == STARTING:
                self._rebuild(name)
            else:
                self._runtime.ctx.set_scenario(name)
            self._scenario = name

    def _rebuild(self, scenario: str) -> None:
        self._runtime.stop()
        runtime = _Runtime(self._profile, self._settings, scenario)
        runtime.start()
        self._runtime = runtime

    def stop(self) -> None:
        with self._lock:
            self._runtime.stop()
