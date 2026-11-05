"""評估規則（規格書第 3 節）：不含執行緒與 I/O 的純函式。

時間皆為 monotonic 秒數；「超過」一律使用嚴格大於。
"""
from typing import Collection, Dict, Iterable, Mapping, Optional, Sequence, Set, Tuple

from .recorder import RecorderSnapshot
from .topology import LaneSpec, NodeSpec

_READY_STATES = ("ok", "degraded")

MSG_STARTING = "啟動中，尚未有成功紀錄"
MSG_STUCK = "工作進行中超過時限"
MSG_LANE_BLOCKED = "同一條循序 lane 有節點卡住"
MSG_UPSTREAM = "上游尚未就緒"
MSG_NEVER_SUCCEEDED = "從未有成功紀錄"


def is_stuck(spec: NodeSpec, snapshot: RecorderSnapshot, now: float) -> bool:
    """只判斷進行中時間（規則 4）；不含規則 1～3 的優先順序。"""
    if spec.stuck_after_s is None or snapshot.in_progress_since is None:
        return False
    return now - snapshot.in_progress_since > spec.stuck_after_s


def _is_starting(spec: NodeSpec, snapshot: RecorderSnapshot, now: float,
                 started_at: float) -> bool:
    return snapshot.last_success_at is None and now - started_at <= spec.startup_grace_s


def blocks_lane(spec: NodeSpec, snapshot: RecorderSnapshot, *, now: float,
                started_at: float, enabled: bool) -> bool:
    """節點是否會以規則 4 命中（規則 1～3 優先），因而擋住所屬 sequential lane。"""
    if not enabled or snapshot.fatal_reason is not None:
        return False
    if _is_starting(spec, snapshot, now, started_at):
        return False
    return is_stuck(spec, snapshot, now)


def lane_blocked_nodes(lanes: Iterable[LaneSpec], stuck: Collection[str]) -> Set[str]:
    """回傳被擋住的節點：同一條 sequential lane 內，有「其他」節點卡住。"""
    blocked: Set[str] = set()
    for lane in lanes:
        if not lane.sequential:
            continue
        stuck_here = [n for n in lane.nodes if n in stuck]
        for node_id in lane.nodes:
            if any(s != node_id for s in stuck_here):
                blocked.add(node_id)
    return blocked


def evaluate_node(
    spec: NodeSpec,
    snapshot: RecorderSnapshot,
    *,
    now: float,
    started_at: float,
    enabled: bool,
    dependencies: Mapping[str, Optional[bool]],
    upstream_states: Mapping[str, str],
    lane_blocked: bool,
) -> Tuple[str, Optional[str], Optional[str]]:
    """依規格書第 3 節由上往下判斷，回傳 (state, reason, message)。"""
    if not enabled:  # 1
        return "disabled", "disabled", None
    if snapshot.fatal_reason is not None:  # 2
        return "unavailable", snapshot.fatal_reason, snapshot.fatal_message
    if _is_starting(spec, snapshot, now, started_at):  # 3
        return "waiting", "starting", MSG_STARTING
    if is_stuck(spec, snapshot, now):  # 4
        return "unavailable", "stuck", MSG_STUCK
    for name, value in dependencies.items():  # 5：只有 False 才算失敗，None 視同通過
        if value is False:
            return "unavailable", "dependency_unavailable", f"依賴 {name} 無法使用"
    if lane_blocked:  # 6
        return "waiting", "lane_blocked", MSG_LANE_BLOCKED
    if any(state not in _READY_STATES for state in upstream_states.values()):  # 7
        return "waiting", "upstream_not_ready", MSG_UPSTREAM
    if spec.stale_after_s is not None:
        if snapshot.last_success_at is None:  # 8
            return "unavailable", "never_succeeded", MSG_NEVER_SUCCEEDED
        elapsed = now - snapshot.last_success_at
        if elapsed > spec.stale_after_s:  # 9
            return "unavailable", spec.stale_reason, f"已 {int(elapsed)} 秒沒有成功紀錄"
    if (snapshot.last_error_at is not None
            and now - snapshot.last_error_at <= spec.error_window_s):  # 10
        return "degraded", snapshot.last_error_reason, snapshot.last_error_message
    return "ok", None, None  # 11


def apply_rules(
    nodes: Mapping[str, NodeSpec],
    order: Sequence[str],
    lanes: Iterable[LaneSpec],
    snapshots: Mapping[str, RecorderSnapshot],
    enabled: Mapping[str, bool],
    dependencies: Mapping[str, Mapping[str, Optional[bool]]],
    *,
    now: float,
    started_at: float,
) -> Dict[str, Tuple[str, Optional[str], Optional[str]]]:
    """依拓樸順序評估所有節點；上游使用同一輪的結果。"""
    blockers = {
        n for n, spec in nodes.items()
        if blocks_lane(spec, snapshots[n], now=now, started_at=started_at, enabled=enabled[n])
    }
    blocked = lane_blocked_nodes(lanes, blockers)
    results: Dict[str, Tuple[str, Optional[str], Optional[str]]] = {}
    for node_id in order:
        spec = nodes[node_id]
        results[node_id] = evaluate_node(
            spec, snapshots[node_id], now=now, started_at=started_at,
            enabled=enabled[node_id], dependencies=dependencies[node_id],
            upstream_states={u: results[u][0] for u in spec.upstream},
            lane_blocked=node_id in blocked,
        )
    return results
