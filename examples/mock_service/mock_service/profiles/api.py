"""api 架構（規格書 8.3）：非 Edge 命名、多依賴、多上游、巢狀 lane、閒置仍為 ok。"""
from smart_health_record import HealthMonitor

from ..context import SimContext
from ..scenarios import API_DEPENDENCY_DOWN, API_FATAL_NODE, API_SCENARIOS, FAKE_RTSP_URL
from ..settings import Settings
from . import Built

SCENARIOS = API_SCENARIOS
CONTROL_PERIOD_S = 0.05


def build(settings: Settings, ctx: SimContext) -> Built:
    monitor = HealthMonitor("api", settings.instance, tick_interval_s=settings.tick_interval_s)
    monitor.add_lane("main", "Request path", sequential=True)
    monitor.add_lane("workers", "Background workers", parent="handler")
    monitor.add_lane("batch", "Batch jobs", parent="job-runner")

    common = dict(stale_after_s=None, stuck_after_s=None,
                  startup_grace_s=settings.startup_grace_s,
                  error_window_s=settings.error_window_s)

    def down(dependency: str):
        return lambda: API_DEPENDENCY_DOWN.get(ctx.scenario) != dependency

    recorders = {
        "gateway": monitor.add_node("gateway", "Gateway", "main", **common),
        "handler": monitor.add_node(
            "handler", "Handler", "main", upstream=["gateway", "cache-warmer"],
            dependencies={"database": down("database"), "cache": down("cache")}, **common),
        "response": monitor.add_node("response", "Response", "main",
                                     upstream=["handler"], **common),
        "job-runner": monitor.add_node(
            "job-runner", "Job runner", "workers", upstream=["handler"],
            dependencies={"database": down("database")}, **common),
        "cache-warmer": monitor.add_node(
            "cache-warmer", "Cache warmer", "workers",
            dependencies={"cache": down("cache")}, **common),
        "batch-export": monitor.add_node(
            "batch-export", "Batch export", "batch",
            upstream=["job-runner", "cache-warmer"], **common),
    }

    def control_loop() -> None:
        """閒置服務不記錄成功；只依情境設定或解除 fatal。"""
        fatal_nodes = set()
        while not ctx.stopped:
            target = API_FATAL_NODE.get(ctx.scenario)
            for node_id, rec in recorders.items():
                if node_id == target and node_id not in fatal_nodes:
                    rec.set_fatal("worker_crashed", f"{node_id} crashed: {FAKE_RTSP_URL}")
                    fatal_nodes.add(node_id)
                elif node_id != target and node_id in fatal_nodes:
                    rec.clear_fatal()
                    fatal_nodes.discard(node_id)
            ctx.wait(CONTROL_PERIOD_S)

    return Built(monitor, [control_loop])
