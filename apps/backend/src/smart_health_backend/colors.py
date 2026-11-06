"""狀態與連線結果對應的顏色（SPEC §6.2）。"""

from __future__ import annotations

from collections.abc import Iterable

GRAY = "gray"

_STATE_COLORS = {
    "ok": "green",
    "degraded": "yellow",
    "unavailable": "red",
    "waiting": GRAY,
    "disabled": GRAY,
}

# 由嚴重到輕微；gray 為最後備援
_SEVERITY = ("red", "yellow", "green")


def color_for_state(state: str | None) -> str:
    """節點狀態轉顏色；沒有狀態或未知狀態一律灰色。"""
    if state is None:
        return GRAY
    return _STATE_COLORS.get(state, GRAY)


def summary_color(connection: str, colors: Iterable[str]) -> str:
    """目標摘要顏色：不是 online 為灰色，否則取最嚴重的顏色。"""
    if connection != "online":
        return GRAY
    present = set(colors)
    for color in _SEVERITY:
        if color in present:
            return color
    return GRAY
