"""狀態變化追蹤器（規格書 2.1、4.3）：只保存 since 與變化紀錄。

只在評估鎖內使用。reason、message 改變不更新 since、不算一筆變化。
"""
import logging
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from .safelog import LogBuffer


class TransitionTracker:
    def __init__(self, max_transitions: int) -> None:
        self._current: Dict[str, Tuple[str, str]] = {}  # node -> (state, since)
        self._transitions: Deque[dict] = deque(maxlen=max_transitions)

    def update(self, node: str, state: str, reason: Optional[str], at: str,
               logs: LogBuffer) -> str:
        """回傳該節點目前的 since。"""
        prev = self._current.get(node)
        if prev is not None and prev[0] == state:
            return prev[1]
        self._current[node] = (state, at)
        self._transitions.append({
            "node": node, "from": prev[0] if prev else None,
            "to": state, "reason": reason, "at": at,
        })
        level = logging.WARNING if state == "unavailable" else logging.INFO
        logs.add(level, "node %s: %s -> %s (reason=%s)",
                 node, prev[0] if prev else None, state, reason)
        return at

    def recent(self, limit: int = 50) -> List[dict]:
        """由新到舊，最多 limit 筆；回傳新建的 dict。"""
        items = list(self._transitions)[-limit:] if limit > 0 else []
        return [dict(t) for t in reversed(items)]
