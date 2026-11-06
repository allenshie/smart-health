"""對外回傳的檢視模型（Task 7 的路由直接序列化）。

不含 base_url 與原始錯誤字串；錯誤只以 connection 代碼呈現。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .contract import Lane, TopologyNode


class TargetSummary(BaseModel):
    id: str
    name: str
    connection: str
    summary_color: str
    last_success_at: str | None


class TopologyView(BaseModel):
    service: str
    instance: str
    topology_version: str
    lanes: list[Lane]
    nodes: list[TopologyNode]


class NodeView(BaseModel):
    state: str | None
    reason: str | None
    message: str | None
    since: str | None
    metrics: dict[str, int | float | str | bool | None]
    color: str


class TargetDetail(TargetSummary):
    topology: TopologyView | None
    nodes: dict[str, NodeView]


class Transition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    node: str
    from_: str | None = Field(alias="from")
    to: str
    reason: str | None
    at: str
