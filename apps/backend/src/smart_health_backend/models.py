"""對外回傳的檢視模型（Task 7 的路由直接序列化）。

不含 base_url 與原始錯誤字串；錯誤只以 connection 代碼呈現。
"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict, Field

from .contract import Lane, TopologyNode


class _Frozen(BaseModel):
    """檢視模型一律唯讀，避免呼叫端改到內部資料。"""

    model_config = ConfigDict(frozen=True)


class TargetSummary(_Frozen):
    id: str
    name: str
    connection: str
    summary_color: str
    last_success_at: str | None


class TopologyView(_Frozen):
    service: str
    instance: str
    topology_version: str
    lanes: list[Lane]
    nodes: list[TopologyNode]


class NodeView(_Frozen):
    state: str | None
    reason: str | None
    message: str | None
    since: str | None
    metrics: dict[str, int | float | str | bool | None]
    color: str


class TargetDetail(TargetSummary):
    topology: TopologyView | None
    nodes: dict[str, NodeView]


class Transition(_Frozen):
    model_config = ConfigDict(populate_by_name=True, frozen=True)

    node: str
    from_: str | None = Field(alias="from")
    to: str
    reason: str | None
    at: str
