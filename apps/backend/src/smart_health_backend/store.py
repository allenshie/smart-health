"""各目標最新狀態與狀態變化的記憶體儲存。

Poller 是唯一寫入者；所有存取都在同一個 event loop，不需要鎖。
檢視（TargetSummary、TargetDetail）在讀取時依連線狀態、架構與狀態組出，
因此「不是 online 一律灰色」只有一個實作位置。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from .colors import GRAY, color_for_state, summary_color
from .config import AppConfig, TargetConfig
from .contract import StatusDoc, TopologyDoc
from .models import NodeView, TargetDetail, TargetSummary, TopologyView, Transition

log = logging.getLogger(__name__)

TransitionKey = tuple[str, str, str]


@dataclass
class _TargetState:
    config: TargetConfig
    connection: str = "unknown"
    last_success_at: str | None = None
    topology: TopologyDoc | None = None
    status: StatusDoc | None = None
    transitions: list[Transition] = field(default_factory=list)  # 新到舊（依收到順序）
    stored_keys: set[TransitionKey] = field(default_factory=set)
    last_response_keys: set[TransitionKey] = field(default_factory=set)
    extra_nodes: frozenset[str] = frozenset()


def _now() -> datetime:
    return datetime.now().astimezone()


class TargetStore:
    def __init__(self, config: AppConfig, clock: Callable[[], datetime] | None = None) -> None:
        self._history_limit = config.history_limit
        self._clock = clock or _now
        self._targets = {t.id: _TargetState(t) for t in config.targets}

    # ---- 寫入（只有 Poller 呼叫） ----

    def set_topology(self, target_id: str, topology: TopologyDoc) -> None:
        self._targets[target_id].topology = topology

    def apply_failure(self, target_id: str, connection: str) -> None:
        """本輪失敗：只更新連線代碼，保留架構。"""
        self._targets[target_id].connection = connection

    def apply_status(self, target_id: str, status: StatusDoc, connection: str) -> None:
        """通過驗證的 /status（connection 為 online 或 stale）。"""
        state = self._targets[target_id]
        state.connection = connection
        state.status = status
        if connection == "online":
            state.last_success_at = self._clock().isoformat(timespec="milliseconds")
        self._note_extra_nodes(state, status)
        self._merge_transitions(state, status)

    def _note_extra_nodes(self, state: _TargetState, status: StatusDoc) -> None:
        known = {n.id for n in state.topology.nodes} if state.topology else set()
        extra = frozenset(status.nodes) - known
        if extra != state.extra_nodes and extra:
            log.info("目標 %s 的狀態含架構未列的節點，已忽略: %s", state.config.id, sorted(extra))
        state.extra_nodes = extra

    def _merge_transitions(self, state: _TargetState, status: StatusDoc) -> None:
        known = {n.id for n in state.topology.nodes} if state.topology else set()
        response_keys: set[TransitionKey] = set()
        batch: list[Transition] = []
        for item in status.recent_transitions:  # 服務給的順序：新到舊
            key = (item.node, item.at, item.to)
            response_keys.add(key)
            if item.node not in known:
                continue
            if key in state.stored_keys or key in state.last_response_keys:
                continue
            state.last_response_keys.add(key)  # 同一批內重複也只收一次
            batch.append(
                Transition(node=item.node, from_=item.from_, to=item.to, reason=item.reason, at=item.at)
            )
        merged = (batch + state.transitions)[: self._history_limit]
        state.transitions = merged
        state.stored_keys = {(t.node, t.at, t.to) for t in merged}
        state.last_response_keys = response_keys

    # ---- 讀取 ----

    def _node_views(self, state: _TargetState) -> dict[str, NodeView]:
        if state.topology is None:
            return {}
        online = state.connection == "online" and state.status is not None
        views: dict[str, NodeView] = {}
        for node in state.topology.nodes:
            if not online:
                reason = state.connection
                views[node.id] = NodeView(
                    state=None, reason=reason, message=None, since=None, metrics={}, color=GRAY
                )
                continue
            current = state.status.nodes.get(node.id)
            if current is None:
                views[node.id] = NodeView(
                    state=None, reason="status_missing", message=None, since=None, metrics={}, color=GRAY
                )
            else:
                views[node.id] = NodeView(
                    state=current.state,
                    reason=current.reason,
                    message=current.message,
                    since=current.since,
                    metrics=dict(current.metrics),
                    color=color_for_state(current.state),
                )
        return views

    def _summary(self, state: _TargetState, nodes: dict[str, NodeView]) -> TargetSummary:
        return TargetSummary(
            id=state.config.id,
            name=state.config.name,
            connection=state.connection,
            summary_color=summary_color(state.connection, (n.color for n in nodes.values())),
            last_success_at=state.last_success_at,
        )

    def list_views(self) -> list[TargetSummary]:
        return [self._summary(s, self._node_views(s)) for s in self._targets.values()]

    def get_view(self, target_id: str) -> TargetDetail | None:
        state = self._targets.get(target_id)
        if state is None:
            return None
        nodes = self._node_views(state)
        topology = None
        if state.topology is not None:
            t = state.topology
            topology = TopologyView(
                service=t.service,
                instance=t.instance,
                topology_version=t.topology_version,
                lanes=t.lanes,
                nodes=t.nodes,
            )
        summary = self._summary(state, nodes)
        return TargetDetail(**summary.model_dump(), topology=topology, nodes=nodes)

    def get_transitions(self, target_id: str, limit: int) -> list[Transition] | None:
        state = self._targets.get(target_id)
        if state is None:
            return None
        return state.transitions[:limit]
