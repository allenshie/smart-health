"""HealthMonitor.recorder(node_id)（規格書 5.1、5.2）：依 id 取得 add_node() 回傳的同一個物件。"""
import threading
import time

import pytest
from monitor_support import WAIT_S, call_with_timeout, simple, wait_until


# ---------------------------------------------------------------- 同一個物件

def test_recorder_returns_object_from_add_node(make):
    m = make()
    m.add_lane("main", "Main")
    a = m.add_node("a", "A", "main")
    b = m.add_node("b", "B", "main")
    assert m.recorder("a") is a
    assert m.recorder("b") is b


def test_recorder_records_into_same_node(make):
    m = make()
    simple(m, startup_grace_s=0)
    m.recorder("a").set_fatal("broken", "壞了")
    m.evaluate_once()
    node = m.status()["nodes"]["a"]
    assert (node["state"], node["reason"]) == ("unavailable", "broken")


# ---------------------------------------------------------------- 各時期

def test_recorder_before_start(make):
    m = make()
    a = simple(m)
    assert m.recorder("a") is a


def test_recorder_while_running(make):
    m = make(tick_interval_s=0.01)
    a = simple(m)
    m.start()
    wait_until(lambda: m.status()["evaluated_at"] is not None)  # 評估執行緒已在執行
    assert m.recorder("a") is a


def test_recorder_after_stop(make):
    m = make(tick_interval_s=0.01)
    a = simple(m)
    m.start()
    m.stop()
    assert m.recorder("a") is a


def test_recorder_after_implicit_start(make):
    m = make()
    a = simple(m)
    m.evaluate_once()
    assert m.recorder("a") is a


def test_recorder_does_not_wait_for_evaluation(make, gates):
    """評估卡住時，recorder() 仍要立即回傳（不碰評估鎖）。"""
    entered, block = gates(), gates()

    def blocking_dependency():
        entered.set()
        block.wait(WAIT_S)
        return True

    m = make(tick_interval_s=0.01)
    m.add_lane("main", "Main")
    a = m.add_node("a", "A", "main", dependencies={"dep": blocking_dependency})
    m.start()
    assert entered.wait(WAIT_S)  # 評估執行緒持有評估鎖，卡在 callable
    assert call_with_timeout(lambda: m.recorder("a"), timeout=1.0) is a


# ---------------------------------------------------------------- 不存在

def test_unknown_id_raises_key_error_with_id(make):
    m = make()
    simple(m)
    with pytest.raises(KeyError) as info:
        m.recorder("missing")
    assert info.value.args == ("node 'missing' 不存在",)


def test_unknown_id_before_any_node(make):
    m = make()
    with pytest.raises(KeyError):
        m.recorder("a")


@pytest.mark.parametrize("bad", [None, 1, b"a", ["a"], {"a": 1}, ("a",)])
def test_non_string_id_raises_key_error(make, bad):
    m = make()
    simple(m)
    with pytest.raises(KeyError) as info:
        m.recorder(bad)
    assert info.value.args == (f"node {bad!r} 不存在",)


def test_failed_add_node_is_not_registered(make):
    m = make()
    m.add_lane("main", "Main")
    with pytest.raises(ValueError):
        m.add_node("a", "A", "no-such-lane")
    with pytest.raises(KeyError):
        m.recorder("a")


# ---------------------------------------------------------------- 執行緒安全

def test_concurrent_add_node_and_recorder(make):
    m = make()
    m.add_lane("main", "Main")
    ids = [f"n{i}" for i in range(200)]
    added, found, errors = {}, {}, []
    go = threading.Event()

    def writer(chunk):
        go.wait(WAIT_S)
        for node_id in chunk:
            added[node_id] = m.add_node(node_id, node_id, "main")

    def reader(chunk):
        go.wait(WAIT_S)
        pending = list(chunk)
        # 以實際經過的時間判斷逾時。go 已經 set，go.wait() 會立刻回傳，不能用來等待。
        deadline = time.monotonic() + WAIT_S
        while pending and time.monotonic() < deadline:
            node_id = pending[0]
            try:
                found[node_id] = m.recorder(node_id)
                pending.pop(0)
            except KeyError:
                time.sleep(0.0005)  # 尚未新增：稍等再試
            except BaseException as exc:  # noqa: BLE001 - 轉交給測試主執行緒
                errors.append(exc)
                return

    chunks = [ids[i::4] for i in range(4)]
    threads = ([threading.Thread(target=writer, args=(c,)) for c in chunks]
               + [threading.Thread(target=reader, args=(c,)) for c in chunks])
    for t in threads:
        t.start()
    go.set()
    for t in threads:
        t.join(WAIT_S * 2)
    assert not any(t.is_alive() for t in threads)
    assert errors == []
    assert sorted(found) == sorted(ids)
    assert all(found[i] is added[i] for i in ids)
