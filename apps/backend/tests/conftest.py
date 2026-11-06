"""pytest fixtures。"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from support import FakeNetwork, FakeService, load_fixture


@pytest.fixture
def topology_edge() -> dict:
    return load_fixture("topology_edge.json")


@pytest.fixture
def status_edge() -> dict:
    return load_fixture("status_edge_camera_down.json")


@pytest.fixture
def status_before_first() -> dict:
    return load_fixture("status_before_first_evaluation.json")


@pytest.fixture
def make_service(topology_edge, status_edge) -> Callable[[], FakeService]:
    return lambda: FakeService(topology_edge, status_edge)


@pytest.fixture
def network() -> FakeNetwork:
    return FakeNetwork()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
