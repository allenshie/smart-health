"""可用命令列調短的門檻。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    instance: str
    host: str = "127.0.0.1"
    port: int = 18081
    stale_after_s: float = 5.0
    stuck_after_s: float = 3.0
    startup_grace_s: float = 30.0
    error_window_s: float = 30.0
    tick_interval_s: float = 1.0
