from __future__ import annotations

import pytest

from smart_health_backend.colors import color_for_state, summary_color


@pytest.mark.parametrize(
    ("state", "color"),
    [
        ("ok", "green"),
        ("degraded", "yellow"),
        ("unavailable", "red"),
        ("waiting", "gray"),
        ("disabled", "gray"),
        (None, "gray"),
    ],
)
def test_state_color_mapping(state, color):
    assert color_for_state(state) == color


def test_summary_priority():
    assert summary_color("online", ["green", "yellow", "red", "gray"]) == "red"
    assert summary_color("online", ["green", "yellow", "gray"]) == "yellow"
    assert summary_color("online", ["gray", "green"]) == "green"
    assert summary_color("online", ["gray", "gray"]) == "gray"
    assert summary_color("online", []) == "gray"


@pytest.mark.parametrize(
    "connection", ["unknown", "offline", "stale", "incompatible", "invalid_response"]
)
def test_summary_gray_when_not_online(connection):
    assert summary_color(connection, ["red", "green"]) == "gray"
