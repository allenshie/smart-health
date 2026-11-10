"""等待就緒（規格書 3.1）：不含執行緒與 I/O 的純函式。

- 就緒之前只判定 fatal，其他一律 ``waiting``／``starting``。
- ``wait_for_ready=True`` 就緒之後，時間相關的判斷從就緒時刻起算：
  把快照中的事件時間調整為「事件時間」與「就緒時刻」中較晚的一個，
  再交給第 3 節的規則（``evaluator``），規則本身不變。
"""
import dataclasses
from typing import Optional, Tuple

from .recorder import RecorderSnapshot

MSG_NOT_READY = "服務啟動中，尚未就緒"


def pre_ready_result(snapshot: RecorderSnapshot) -> Tuple[str, Optional[str], Optional[str]]:
    """就緒之前的評估：只看 fatal，不看其他事實，也不需要 enabled、dependencies。"""
    if snapshot.fatal_reason is not None:
        return "unavailable", snapshot.fatal_reason, snapshot.fatal_message
    return "waiting", "starting", MSG_NOT_READY


def clamp_to_ready(snapshot: RecorderSnapshot, ready: float) -> RecorderSnapshot:
    """事件時間取 max(事件時間, 就緒時刻)；就緒之前的錯誤不計入（剛好在就緒時刻的要計入）。

    ``last_success_at`` 仍保留非 None，所以「是否曾經成功」包含就緒之前的成功紀錄。
    """
    success = snapshot.last_success_at
    in_progress = snapshot.in_progress_since
    changes = {
        "last_success_at": None if success is None else max(success, ready),
        "in_progress_since": None if in_progress is None else max(in_progress, ready),
    }
    if snapshot.last_error_at is not None and snapshot.last_error_at < ready:
        changes.update(last_error_at=None, last_error_reason=None, last_error_message=None)
    return dataclasses.replace(snapshot, **changes)
