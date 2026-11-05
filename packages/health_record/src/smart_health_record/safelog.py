"""安全的 log 輔助：延後寫出、不洩漏未遮蔽內容、連續失敗只警告一次。

評估期間先把 log 收集在 LogBuffer，放掉所有鎖之後才一次寫出。
"""
import logging
from typing import Any, Callable, List, Set, Tuple

from .masking import mask_text


def describe_exception(exc: BaseException) -> str:
    """例外類型加上遮蔽後的訊息；str(exc) 本身失敗也不會再拋例外。"""
    try:
        text = mask_text(str(exc))
    except Exception:
        text = "<訊息無法取得>"
    return f"{type(exc).__name__}: {text}"


class LogBuffer:
    def __init__(self) -> None:
        self._items: List[Tuple[int, str, tuple]] = []

    def add(self, level: int, fmt: str, *args: Any) -> None:
        self._items.append((level, fmt, args))

    def emit(self, logger: logging.Logger) -> None:
        for level, fmt, args in self._items:
            try:
                logger.log(level, fmt, *args)
            except Exception:
                pass
        self._items = []


class CallableGuard:
    """呼叫使用者提供的 callable；失敗時回傳預設值，同一個 callable 連續失敗只警告一次。

    只在評估鎖內使用，不需要自己的鎖。
    """

    def __init__(self) -> None:
        self._failing: Set[Tuple[str, str]] = set()

    def call(self, key: Tuple[str, str], fn: Callable[[], Any], default: Any,
             logs: LogBuffer) -> Any:
        try:
            value = fn()
        except BaseException as exc:  # 評估執行緒不能因 callable 結束（含 SystemExit）
            if key not in self._failing:
                self._failing.add(key)
                logs.add(logging.WARNING, "node %s: %s callable raised %s; using default",
                         key[0], key[1], describe_exception(exc))
            return default
        self._failing.discard(key)
        return value
