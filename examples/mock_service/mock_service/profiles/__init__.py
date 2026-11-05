"""各 profile 實作 ``SCENARIOS`` 與 ``build(settings, ctx) -> Built``。"""
from dataclasses import dataclass
from typing import Callable, List

from smart_health_record import HealthMonitor


@dataclass
class Built:
    monitor: HealthMonitor
    loops: List[Callable[[], None]]  # 每個都是一條模擬執行緒，直到 ctx.stopped
