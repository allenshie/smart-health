"""edge 架構（規格書 8.1）與其模擬執行緒。"""
import time

from smart_health_record import HealthMonitor

from ..context import SimContext
from ..scenarios import (EDGE_MESSAGING_DOWN, EDGE_NO_FRAME, EDGE_SCENARIOS, FAKE_PASSWORD_TEXT,
                         FAKE_RTSP_URL, STARTING)
from ..settings import Settings
from . import Built

SCENARIOS = EDGE_SCENARIOS
WORKER_PERIOD_S = 1 / 30
MAIN_PERIOD_S = 1 / 15
ERROR_PERIOD_S = 0.2


def has_frame(scenario: str) -> bool:
    return scenario not in EDGE_NO_FRAME


def build(settings: Settings, ctx: SimContext) -> Built:
    monitor = HealthMonitor("edge", settings.instance, tick_interval_s=settings.tick_interval_s)
    monitor.add_lane("main", "Main", sequential=True)
    monitor.add_lane("ingest-bg", "Ingest worker", parent="ingest")
    monitor.add_lane("stream-bg", "Stream output", parent="stream")

    common = dict(stale_after_s=settings.stale_after_s,
                  startup_grace_s=settings.startup_grace_s,
                  error_window_s=settings.error_window_s)

    def stream_sink():  # 有畫面才判斷，避免相機斷線被誤判成推流問題
        scenario = ctx.scenario
        if not has_frame(scenario):
            return None
        return scenario != "stream_sink_down"

    def messaging():
        return ctx.scenario not in EDGE_MESSAGING_DOWN

    def stream_enabled():
        return ctx.scenario != "stream_disabled"

    worker = monitor.add_node("ingest-worker", "Ingest worker", "ingest-bg",
                              stale_reason="no_new_frame", **common)
    ingest = monitor.add_node("ingest", "Ingest", "main", upstream=["ingest-worker"], **common)
    infer = monitor.add_node("infer", "Infer", "main", upstream=["ingest"],
                             stuck_after_s=settings.stuck_after_s, **common)
    stream = monitor.add_node("stream", "Stream", "main", upstream=["infer"],
                              enabled=stream_enabled, **common)
    output = monitor.add_node("stream-output", "Stream output", "stream-bg",
                              upstream=["stream"], dependencies={"stream_sink": stream_sink},
                              enabled=stream_enabled, **common)
    publish = monitor.add_node("publish", "Publish", "main", upstream=["infer"],
                               dependencies={"messaging": messaging}, **common)

    def worker_loop() -> None:
        fatal = False
        last_error = 0.0
        while not ctx.stopped:
            scenario = ctx.scenario
            if scenario == "worker_fatal":
                if not fatal:
                    worker.set_fatal("worker_crashed", f"worker crashed: {FAKE_RTSP_URL}")
                    fatal = True
            else:
                if fatal:
                    worker.clear_fatal()
                    fatal = False
                if has_frame(scenario):
                    worker.record_success()
                    now = time.monotonic()
                    if scenario == "read_errors" and now - last_error >= ERROR_PERIOD_S:
                        worker.record_error("read_failed", f"read failed: {FAKE_RTSP_URL}")
                        last_error = now
            ctx.wait(WORKER_PERIOD_S)

    def main_pass(scenario: str, state: dict) -> None:
        with ingest.track():
            pass
        with infer.track():
            if scenario == "infer_stuck":
                ctx.wait_while("infer_stuck")
            elif scenario == "infer_exception":
                raise RuntimeError(f"infer failed: {FAKE_PASSWORD_TEXT}")
        if scenario != "stream_disabled":
            with stream.track():
                pass
        with publish.track():
            pass
        now = time.monotonic()
        if scenario == "publish_errors" and now - state["error_at"] >= ERROR_PERIOD_S:
            publish.record_error("publish_failed", f"publish failed: {FAKE_RTSP_URL}")
            state["error_at"] = now

    def main_loop() -> None:
        state = {"error_at": 0.0}
        while not ctx.stopped:
            scenario = ctx.scenario
            if scenario != STARTING and has_frame(scenario):
                try:
                    main_pass(scenario, state)
                except Exception:  # noqa: BLE001 - 例外已由 track() 記錄，該輪後面的節點不執行
                    pass
            ctx.wait(MAIN_PERIOD_S)

    def output_loop() -> None:
        while not ctx.stopped:
            if ctx.scenario not in (STARTING, "stream_sink_down", "stream_disabled"):
                output.record_success()
            ctx.wait(MAIN_PERIOD_S)

    return Built(monitor, [worker_loop, main_loop, output_loop])
