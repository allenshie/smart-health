"""edge 模擬服務的 loading、loading_fatal 情境（規格書 8.2，wait_for_ready=True）。"""
import pytest

from support import assert_holds, wait_until
from mock_service.scenarios import FAKE_SECRET

NODES = ["ingest-worker", "ingest", "infer", "stream", "stream-output", "publish"]
ALL_OK = {n: "ok" for n in NODES}
WAITING = {n: "waiting" for n in NODES}
NOT_READY = "服務啟動中，尚未就緒"

# 寬限期與 stale 門檻都很短：就緒前若照一般規則判定，很快就會離開 waiting
FAST = dict(tick_interval_s=0.1, stuck_after_s=0.5, stale_after_s=1.0,
            startup_grace_s=1, error_window_s=30)


def enter(svc, name, expected):
    """切到會重建的情境，等到新的 monitor 產出預期狀態。"""
    before = svc.status()["started_at"]
    svc.set_scenario(name)
    wait_until(lambda: svc.status()["started_at"] != before and svc.states() == expected,
               15.0, what=f"{name} 重建完成")


def test_loading_stays_waiting_although_successes_are_recorded(mock_service):
    svc = mock_service("edge", **FAST)
    svc.wait_states(ALL_OK)
    enter(svc, "loading", WAITING)
    # 2 秒以上：超過 startup_grace_s + stale_after_s 仍維持 waiting
    assert_holds(lambda: svc.states() == WAITING, "loading 維持 waiting", reads=25, gap=0.1)
    status = svc.status()
    assert status["ready_at"] is None
    assert {(n["reason"], n["message"]) for n in status["nodes"].values()} == {("starting", NOT_READY)}


def test_loading_fatal_marks_only_worker_unavailable(mock_service):
    svc = mock_service("edge", **FAST)
    svc.wait_states(ALL_OK)
    expected = dict(WAITING, **{"ingest-worker": "unavailable"})
    enter(svc, "loading_fatal", expected)
    assert_holds(lambda: svc.states() == expected, "loading_fatal 維持", reads=25, gap=0.1)
    status = svc.status()
    assert status["ready_at"] is None
    reasons = svc.reasons()
    assert reasons.pop("ingest-worker") == "worker_crashed"
    assert set(reasons.values()) == {"starting"}
    assert FAKE_SECRET not in str(status)


@pytest.mark.parametrize("name,expected", [
    ("loading", WAITING),
    ("loading_fatal", dict(WAITING, **{"ingest-worker": "unavailable"})),
])
def test_leaving_loading_marks_ready_without_rebuild(mock_service, name, expected):
    svc = mock_service("edge", **FAST)
    svc.wait_states(ALL_OK)
    enter(svc, name, expected)
    started = svc.status()["started_at"]
    svc.set_scenario("normal")
    svc.wait_states(ALL_OK)
    status = svc.status()
    assert status["started_at"] == started  # 不重建
    assert status["ready_at"] is not None and status["ready_at"] > started
    svc.set_scenario("messaging_down")
    svc.wait_states(dict(ALL_OK, publish="unavailable"))
    assert svc.status()["started_at"] == started


def test_ready_at_equals_started_at_without_wait_for_ready(mock_service):
    svc = mock_service("edge", **FAST)
    svc.wait_states(ALL_OK)
    status = svc.status()
    assert status["ready_at"] == status["started_at"]  # 初始 monitor
    enter(svc, "loading", WAITING)
    svc.set_scenario("starting")  # 對照組：以 wait_for_ready=False 重建
    wait_until(lambda: svc.status()["ready_at"] is not None, 15.0, what="starting 重建")
    status = svc.status()
    assert status["ready_at"] == status["started_at"]


def test_loading_again_rebuilds(mock_service):
    svc = mock_service("edge", **FAST)
    svc.wait_states(ALL_OK)
    enter(svc, "loading", WAITING)
    svc.set_scenario("normal")
    svc.wait_states(ALL_OK)
    enter(svc, "loading", WAITING)
    assert svc.status()["ready_at"] is None
