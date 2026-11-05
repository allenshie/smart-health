"""HealthMonitor：架構註冊、評估執行緒、快取（規格書 2.1、5.1、5.2）。

鎖的規則：
- ``_lock``：保護註冊資料、啟動狀態與評估結果快取；只短暫持有，``status()`` 只用這把鎖。
- ``_eval_lock``：只用於防止 ``evaluate_once()`` 與執行緒同時評估，``status()`` 絕不碰它。
- 使用者的 callable 不在 ``_lock`` 內呼叫（只持有 ``_eval_lock``）；
  log 於放掉所有鎖之後才寫出。
"""
import copy
import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .evaluator import apply_rules
from .recorder import NodeRecorder
from .safelog import CallableGuard, LogBuffer, describe_exception
from .published import PublishedRound, build_published
from .tracker import TransitionTracker
from .topology import (
    LaneSpec,
    NodeSpec,
    build_topology,
    check_id,
    check_instance,
    check_label,
    check_non_negative,
    check_positive,
    check_reason_code,
    topological_order,
    validate_graph,
)

SCHEMA_VERSION = 1


def _local_now() -> datetime:
    return datetime.now().astimezone()


class HealthMonitor:
    _STOP_JOIN_TIMEOUT_S = 5.0

    def __init__(self, service: str, instance: str, *,
                 tick_interval_s: float = 1.0,
                 max_transitions: int = 200,
                 logger: Optional[logging.Logger] = None,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], datetime] = _local_now) -> None:
        self._service = check_id(service, "service")
        self._instance = check_instance(instance)
        self._tick = check_positive(tick_interval_s, "tick_interval_s")
        if self._tick > threading.TIMEOUT_MAX:  # 否則 Event.wait 會拋 OverflowError
            raise ValueError("tick_interval_s 過大")
        if isinstance(max_transitions, bool) or not isinstance(max_transitions, int):
            raise ValueError("max_transitions 必須是整數")
        check_non_negative(max_transitions, "max_transitions")
        self._logger = logger or logging.getLogger("smart_health_record")
        self._clock = clock
        self._wall_clock = wall_clock

        self._lock = threading.Lock()
        self._eval_lock = threading.Lock()

        # 註冊資料（_lock 保護；啟動後凍結）
        self._lanes: Dict[str, LaneSpec] = {}
        self._lane_nodes: Dict[str, List[str]] = {}
        self._nodes: Dict[str, NodeSpec] = {}
        self._recorders: Dict[str, NodeRecorder] = {}
        self._dep_fns: Dict[str, Dict[str, Callable[[], Optional[bool]]]] = {}
        self._enabled: Dict[str, Any] = {}

        # 啟動後才有值
        self._started = False
        self._started_mono = 0.0
        self._started_at = ""
        self._topology: Dict[str, Any] = {}
        self._final_lanes: Tuple[LaneSpec, ...] = ()
        self._order: Tuple[str, ...] = ()

        self._cache: Optional[PublishedRound] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 僅在 _eval_lock 內使用
        self._guard = CallableGuard()
        self._tracker: Optional[TransitionTracker] = None  # 啟動時建立
        self._max_transitions = max_transitions

        # 僅由評估執行緒的迴圈讀寫（不在 _eval_lock 內）：目前是否處於連續失敗
        self._round_failing = False

    # ------------------------------------------------------------ 註冊

    def add_lane(self, lane_id: str, label: str, *,
                 parent: Optional[str] = None, sequential: bool = False) -> None:
        check_id(lane_id, "lane id")
        check_label(label, f"lane {lane_id}")
        if parent is not None:
            check_id(parent, f"lane {lane_id} 的 parent")
        with self._lock:
            self._require_not_started()
            if lane_id in self._lanes:
                raise ValueError(f"lane {lane_id} 重複")
            self._lanes[lane_id] = LaneSpec(lane_id, label, parent, bool(sequential))
            self._lane_nodes[lane_id] = []

    def add_node(self, node_id: str, label: str, lane: str, *,
                 upstream: Sequence[str] = (),
                 dependencies: Optional[Mapping[str, Callable[[], Optional[bool]]]] = None,
                 enabled: Any = True,
                 stale_after_s: Optional[float] = None,
                 stuck_after_s: Optional[float] = None,
                 startup_grace_s: float = 30.0,
                 error_window_s: float = 30.0,
                 stale_reason: str = "stale_success") -> NodeRecorder:
        check_id(node_id, "node id")
        check_label(label, f"node {node_id}")
        check_id(lane, f"node {node_id} 的 lane")
        if isinstance(upstream, str):
            raise ValueError("upstream 必須是 id 序列，不可為單一字串")
        ups = tuple(check_id(u, f"node {node_id} 的 upstream") for u in upstream)
        deps = dict(dependencies or {})
        for name, fn in deps.items():
            check_id(name, f"node {node_id} 的 dependency")
            if not callable(fn):
                raise ValueError(f"dependency {name} 必須是 callable")
        if not isinstance(enabled, bool) and not callable(enabled):
            raise ValueError("enabled 必須是 bool 或 callable")
        spec = NodeSpec(
            id=node_id, label=label, lane=lane, upstream=ups, dependencies=tuple(deps),
            stale_after_s=check_non_negative(stale_after_s, "stale_after_s", allow_none=True),
            stuck_after_s=check_non_negative(stuck_after_s, "stuck_after_s", allow_none=True),
            startup_grace_s=check_non_negative(startup_grace_s, "startup_grace_s"),
            error_window_s=check_non_negative(error_window_s, "error_window_s"),
            stale_reason=check_reason_code(stale_reason, "stale_reason"),
        )
        recorder = NodeRecorder(node_id, self._clock, self._logger)
        with self._lock:
            self._require_not_started()
            if node_id in self._nodes:
                raise ValueError(f"node {node_id} 重複")
            if lane not in self._lanes:
                raise ValueError(f"lane {lane} 不存在")
            self._nodes[node_id] = spec
            self._recorders[node_id] = recorder
            self._dep_fns[node_id] = deps
            self._enabled[node_id] = enabled
            self._lane_nodes[lane].append(node_id)
        return recorder

    def _require_not_started(self) -> None:
        if self._started:
            raise ValueError("已開始（start 或 evaluate_once）後不可再新增 lane 或節點")

    # ------------------------------------------------------------ 生命週期

    def _now_wall(self) -> datetime:
        wall = self._wall_clock()
        return wall if wall.tzinfo is not None else wall.astimezone()

    def _ensure_started(self) -> None:
        """驗證並凍結架構；已開始則什麼都不做（沿用原本的開始時間）。"""
        with self._lock:
            if self._started:
                return
            validate_graph(self._lanes, self._nodes)
            lanes = tuple(
                LaneSpec(l.id, l.label, l.parent, l.sequential, tuple(self._lane_nodes[l.id]))
                for l in self._lanes.values()
            )
            topology = build_topology(self._service, self._instance, lanes,
                                      tuple(self._nodes.values()))
            order = tuple(topological_order(self._nodes))
            started_mono = self._clock()
            started_at = self._now_wall().isoformat(timespec="milliseconds")
            tracker = TransitionTracker(self._max_transitions)
            self._final_lanes, self._topology, self._order = lanes, topology, order
            self._started_mono, self._started_at = started_mono, started_at
            self._tracker = tracker
            self._started = True

    def start(self) -> None:
        self._ensure_started()
        with self._lock:
            thread = self._thread
            if thread is not None and thread.is_alive() and not self._stop_event.is_set():
                return
            self._stop_event = threading.Event()
            self._thread = threading.Thread(
                target=self._run, args=(self._stop_event,), daemon=True,
                name=f"smart-health-{self._service}-{self._instance}",
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread, self._thread = self._thread, None
            self._stop_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(self._STOP_JOIN_TIMEOUT_S)  # 逾時就放棄，callable 卡住不能拖住 stop()

    def _run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            self._guarded_round(stop)
            stop.wait(self._tick)

    def _guarded_round(self, stop: Optional[threading.Event] = None) -> None:
        """執行一輪並攔截所有例外（含 BaseException）；連續失敗只記一次，成功後重置。"""
        try:
            self._run_round(stop)
            self._round_failing = False
        except BaseException as exc:
            if self._round_failing:
                return
            self._round_failing = True
            try:
                self._logger.error("evaluation failed: %s", describe_exception(exc))
            except BaseException:
                pass  # 最後防線：log 失敗也不能讓執行緒結束

    # ------------------------------------------------------------ 評估

    def evaluate_once(self) -> None:
        self._run_round(None)

    def _run_round(self, stop: Optional[threading.Event]) -> None:
        self._ensure_started()
        logs = LogBuffer()
        try:
            with self._eval_lock:
                if stop is not None and stop.is_set():
                    return  # 等鎖期間已被 stop，不再跑這一輪
                self._evaluate(logs)
        finally:
            logs.emit(self._logger)

    def _resolve_callables(self, logs: LogBuffer):
        """在 _lock 之外呼叫使用者的 callable；失敗時 enabled 視為 True、dependency 視為 None。"""
        enabled: Dict[str, bool] = {}
        deps: Dict[str, Dict[str, Optional[bool]]] = {}
        for node_id in self._nodes:
            flag = self._enabled[node_id]
            enabled[node_id] = (
                bool(self._guard.call((node_id, "enabled"), lambda f=flag: bool(f()), True, logs))
                if callable(flag) else flag
            )
            deps[node_id] = {
                name: self._guard.call((node_id, f"dependency {name}"), fn, None, logs)
                for name, fn in self._dep_fns[node_id].items()
            }
        return enabled, deps

    def _evaluate(self, logs: LogBuffer) -> None:
        enabled, deps = self._resolve_callables(logs)
        # callable 結束後才取快照與時間，避免阻塞造成誤判
        snaps = {node_id: rec.snapshot() for node_id, rec in self._recorders.items()}
        results = apply_rules(self._nodes, self._order, self._final_lanes, snaps, enabled,
                              deps, now=self._clock(), started_at=self._started_mono)
        self._publish(results, snaps, logs)

    def _publish(self, results: Dict[str, Tuple[str, Optional[str], Optional[str]]],
                 snaps: Dict[str, Any], logs: LogBuffer) -> None:
        """整輪算完才更新追蹤器，並以短暫持鎖換掉快取。"""
        at = self._now_wall().isoformat(timespec="milliseconds")
        cache = build_published(tuple(self._nodes), results, snaps, self._tracker, at,
                                self._clock(), logs)
        with self._lock:
            self._cache = cache

    # ------------------------------------------------------------ 讀取

    def topology(self) -> dict:
        with self._lock:
            if not self._started:
                raise RuntimeError("HealthMonitor 尚未開始")
            topo = self._topology
        return copy.deepcopy(topo)

    def status(self) -> dict:
        with self._lock:
            if not self._started:
                raise RuntimeError("HealthMonitor 尚未開始")
            cache = self._cache
            version = self._topology["topology_version"]
            started_at, started_mono = self._started_at, self._started_mono
        base = cache.published_mono if cache is not None else started_mono
        age = round(max(0.0, self._clock() - base), 3)
        return {
            "schema_version": SCHEMA_VERSION,
            "service": self._service,
            "instance": self._instance,
            "topology_version": version,
            "started_at": started_at,
            "evaluated_at": cache.evaluated_at if cache is not None else None,
            "evaluation_age_s": age,
            "nodes": copy.deepcopy(cache.nodes) if cache is not None else {},
            "recent_transitions": copy.deepcopy(cache.transitions) if cache is not None else [],
        }
