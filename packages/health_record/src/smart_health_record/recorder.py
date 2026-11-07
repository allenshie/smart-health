"""NodeRecorder：在工作執行緒記錄事實（規格書 2.1、5.1、5.2）。

設計重點：
- 公開方法絕不拋例外進業務執行緒。
- 單一 lock 保護欄位；鎖內不做 I/O、不呼叫 clock、不寫 log。
- 只使用注入的 monotonic clock，不使用 wall clock。
"""
import logging
import math
import re
import threading
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional

from .masking import mask_text

_REASON_RE = re.compile(r"[a-z][a-z0-9_]*")
INVALID_REASON = "invalid_reason"


@dataclass(frozen=True)
class RecorderSnapshot:
    """某一時刻的事實快照；時間皆為 monotonic 秒數。metrics 為唯讀複本。"""

    last_success_at: Optional[float]
    last_error_at: Optional[float]
    last_error_reason: Optional[str]
    last_error_message: Optional[str]
    in_progress_since: Optional[float]
    fatal_reason: Optional[str]
    fatal_message: Optional[str]
    metrics: Mapping[str, Any]


_EMPTY = RecorderSnapshot(None, None, None, None, None, None, None, MappingProxyType({}))


def _safe_message(message: Any) -> Optional[str]:
    """遮蔽並截斷訊息；任何失敗都回傳 None。"""
    if message is None:
        return None
    try:
        text = message if isinstance(message, str) else str(message)
        return mask_text(text)
    except Exception:
        return None


class _Tracker:
    """track() 的 context manager；不使用 generator，避免任何例外洩漏。"""

    __slots__ = ("_rec",)

    def __init__(self, rec: "NodeRecorder") -> None:
        self._rec = rec

    def __enter__(self) -> None:
        self._rec.record_start()

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._rec.record_success()
        elif issubclass(exc_type, Exception):
            # str(exc) 失敗時以無訊息方式記錄（_safe_message 會吞掉例外）
            self._rec.record_error("exception", exc)
        else:
            # 取消（asyncio.CancelledError）或 Ctrl-C 等 BaseException：工作沒有完成也不算失敗，
            # 只清除進行中狀態，避免殘留成假的 stuck
            self._rec._clear_in_progress()
        return False  # 原例外原樣往外拋


class NodeRecorder:
    def __init__(self, node_id: str, clock: Callable[[], float], logger: logging.Logger) -> None:
        self._node_id = node_id
        self._clock = clock
        self._logger = logger
        self._lock = threading.Lock()
        self._warned: set = set()
        self._last_success_at: Optional[float] = None
        self._last_error_at: Optional[float] = None
        self._last_error_reason: Optional[str] = None
        self._last_error_message: Optional[str] = None
        self._in_progress_since: Optional[float] = None
        self._fatal_reason: Optional[str] = None
        self._fatal_message: Optional[str] = None
        self._metrics: dict = {}

    # ---- 內部工具 ----
    def _warn_once(self, category: str, text: str) -> None:
        """同一 recorder 同類問題只記一次；log 不含任何呼叫端傳入的值，且在鎖外寫入。"""
        try:
            with self._lock:
                if category in self._warned:
                    return
                self._warned.add(category)
            self._logger.warning("node %s: %s", self._node_id, text)
        except Exception:
            pass

    def _valid_reason(self, reason: Any) -> str:
        if isinstance(reason, str) and _REASON_RE.fullmatch(reason):
            return reason
        self._warn_once("reason", "invalid reason code replaced by invalid_reason")
        return INVALID_REASON

    def _clear_in_progress(self) -> None:
        """只清除進行中狀態，不記成功或錯誤；供 track() 遇到 BaseException 時使用。"""
        try:
            with self._lock:
                self._in_progress_since = None
        except Exception:
            pass

    # ---- 公開 API ----
    def record_start(self) -> None:
        try:
            now = self._clock()
            with self._lock:
                self._in_progress_since = now
        except Exception:
            pass

    def record_success(self) -> None:
        # 高頻呼叫：只寫時間戳，無 I/O、不配置物件
        try:
            now = self._clock()
            with self._lock:
                self._last_success_at = now
                self._in_progress_since = None
        except Exception:
            pass

    def record_error(self, reason: str, message: Optional[str] = None) -> None:
        try:
            code = self._valid_reason(reason)
            text = _safe_message(message)
            now = self._clock()
            with self._lock:
                self._last_error_at = now
                self._last_error_reason = code
                self._last_error_message = text
                self._in_progress_since = None
        except Exception:
            pass

    def set_fatal(self, reason: str, message: Optional[str] = None) -> None:
        try:
            code = self._valid_reason(reason)
            text = _safe_message(message)
            with self._lock:
                self._fatal_reason = code
                self._fatal_message = text
        except Exception:
            pass

    def clear_fatal(self) -> None:
        try:
            with self._lock:
                self._fatal_reason = None
                self._fatal_message = None
        except Exception:
            pass

    def set_metric(self, name: str, value: Any) -> None:
        try:
            if not isinstance(name, str):
                self._warn_once("metric_name", "metric ignored: name is not a string")
                return
            if isinstance(value, str):
                value = mask_text(value)
            elif value is None or isinstance(value, (bool, int)):
                pass
            elif isinstance(value, float) and math.isfinite(value):
                pass
            else:
                self._warn_once("metric_type", "metric ignored: unsupported value type")
                return
            with self._lock:
                self._metrics[name] = value
        except Exception:
            pass

    def track(self) -> _Tracker:
        return _Tracker(self)

    def snapshot(self) -> RecorderSnapshot:
        try:
            with self._lock:
                return RecorderSnapshot(
                    self._last_success_at,
                    self._last_error_at,
                    self._last_error_reason,
                    self._last_error_message,
                    self._in_progress_since,
                    self._fatal_reason,
                    self._fatal_message,
                    MappingProxyType(dict(self._metrics)),
                )
        except Exception:
            return _EMPTY
