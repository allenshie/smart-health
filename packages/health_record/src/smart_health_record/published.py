"""一輪評估的發布結果：發布後不再修改（規格書 4.3）。"""
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .safelog import LogBuffer
from .schema import MAX_MESSAGE_LENGTH
from .tracker import TransitionTracker

MAX_REPORTED_TRANSITIONS = 50


class PublishedRound:
    __slots__ = ("evaluated_at", "published_mono", "nodes", "transitions")

    def __init__(self, evaluated_at: str, published_mono: float, nodes: dict,
                 transitions: list) -> None:
        self.evaluated_at = evaluated_at
        self.published_mono = published_mono
        self.nodes = nodes
        self.transitions = transitions


def build_published(
    node_ids: Sequence[str],
    results: Mapping[str, Tuple[str, Optional[str], Optional[str]]],
    snapshots: Mapping[str, Any],
    tracker: TransitionTracker,
    at: str,
    published_mono: float,
    logs: LogBuffer,
) -> PublishedRound:
    """更新追蹤器並組出全新的結果物件（不共用任何可變內部狀態）。"""
    nodes_out: Dict[str, dict] = {}
    for node_id in node_ids:
        state, reason, message = results[node_id]
        if isinstance(message, str):
            message = message[:MAX_MESSAGE_LENGTH]
        since = tracker.update(node_id, state, reason, at, logs)
        nodes_out[node_id] = {
            "state": state, "reason": reason, "message": message, "since": since,
            "metrics": dict(snapshots[node_id].metrics),
        }
    return PublishedRound(at, published_mono, nodes_out,
                          tracker.recent(MAX_REPORTED_TRANSITIONS))
