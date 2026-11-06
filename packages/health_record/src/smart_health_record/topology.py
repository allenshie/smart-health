"""架構資料與驗證：規格書 4.1、4.2、5.2（啟動階段）。

只放純資料與純函式，不含執行緒、時鐘與 I/O。
"""
import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

_ID_RE = re.compile(r"[a-z][a-z0-9_-]*")
_REASON_RE = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True)
class LaneSpec:
    id: str
    label: str
    parent: Optional[str]
    sequential: bool
    nodes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class NodeSpec:
    id: str
    label: str
    lane: str
    upstream: Tuple[str, ...]
    dependencies: Tuple[str, ...]
    stale_after_s: Optional[float]
    stuck_after_s: Optional[float]
    startup_grace_s: float
    error_window_s: float
    stale_reason: str


# ---- 單一欄位驗證（拋 ValueError） ----

def check_id(value: Any, what: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{what} 格式錯誤，需符合 [a-z][a-z0-9_-]*")
    return value


def check_instance(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("instance 必須是非空字串")
    return value


def check_label(value: Any, what: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{what} 的 label 必須是字串")
    return value


def check_reason_code(value: Any, what: str) -> str:
    if not isinstance(value, str) or not _REASON_RE.fullmatch(value):
        raise ValueError(f"{what} 格式錯誤，需符合 [a-z][a-z0-9_]*")
    return value


def check_non_negative(value: Any, what: str, *, allow_none: bool = False) -> Any:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} 必須是數字")
    if not value >= 0 or math.isinf(value):  # `not >=` 可同時擋 NaN
        raise ValueError(f"{what} 不可為負、NaN 或無限大")
    return value


def check_positive(value: Any, what: str) -> Any:
    check_non_negative(value, what)
    if value <= 0:
        raise ValueError(f"{what} 必須大於 0")
    return value


# ---- 整體架構驗證 ----

def _find_cycle(edges: Mapping[str, Sequence[str]]) -> Optional[str]:
    """回傳位於循環中的某個節點，沒有循環則回 None（迭代式 DFS）。"""
    WHITE, GREY, BLACK = 0, 1, 2
    color = {k: WHITE for k in edges}
    for root in edges:
        if color[root] != WHITE:
            continue
        stack = [(root, iter(edges[root]))]
        color[root] = GREY
        while stack:
            key, it = stack[-1]
            for nxt in it:
                if color.get(nxt, BLACK) == GREY:
                    return nxt
                if color.get(nxt, BLACK) == WHITE:
                    color[nxt] = GREY
                    stack.append((nxt, iter(edges[nxt])))
                    break
            else:
                color[key] = BLACK
                stack.pop()
    return None


def validate_graph(lanes: Mapping[str, LaneSpec], nodes: Mapping[str, NodeSpec]) -> None:
    """檢查 upstream、parent 的存在性與循環。"""
    for node in nodes.values():
        for up in node.upstream:
            if up not in nodes:
                raise ValueError(f"node {node.id} 的 upstream {up} 不存在")
    for lane in lanes.values():
        if lane.parent is not None and lane.parent not in nodes:
            raise ValueError(f"lane {lane.id} 的 parent {lane.parent} 不存在")
    hit = _find_cycle({n.id: n.upstream for n in nodes.values()})
    if hit is not None:
        raise ValueError(f"upstream 形成循環（涉及 {hit}）")
    lane_edges = {
        lane.id: ([nodes[lane.parent].lane] if lane.parent is not None else [])
        for lane in lanes.values()
    }
    hit = _find_cycle(lane_edges)
    if hit is not None:
        raise ValueError(f"lane parent 形成循環（涉及 {hit}）")


def topological_order(nodes: Mapping[str, NodeSpec]) -> List[str]:
    """上游在前的節點順序；同層維持新增順序。需先通過 validate_graph。"""
    order: List[str] = []
    seen = set()

    def visit(root: str) -> None:
        stack = [(root, iter(nodes[root].upstream))]
        seen.add(root)
        while stack:
            key, it = stack[-1]
            for up in it:
                if up not in seen:
                    seen.add(up)
                    stack.append((up, iter(nodes[up].upstream)))
                    break
            else:
                order.append(key)
                stack.pop()

    for node_id in nodes:
        if node_id not in seen:
            visit(node_id)
    return order


def topology_version(lanes: List[dict], nodes: List[dict]) -> str:
    text = json.dumps({"lanes": lanes, "nodes": nodes}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build_topology(service: str, instance: str, lanes: Sequence[LaneSpec],
                   nodes: Sequence[NodeSpec]) -> Dict[str, Any]:
    lane_list = [
        {"id": ln.id, "label": ln.label, "parent": ln.parent,
         "sequential": ln.sequential, "nodes": list(ln.nodes)}
        for ln in lanes
    ]
    node_list = [
        {"id": n.id, "label": n.label, "upstream": list(n.upstream),
         "dependencies": list(n.dependencies)}
        for n in nodes
    ]
    return {
        "schema_version": 1,
        "service": service,
        "instance": instance,
        "topology_version": topology_version(lane_list, node_list),
        "lanes": lane_list,
        "nodes": node_list,
    }
