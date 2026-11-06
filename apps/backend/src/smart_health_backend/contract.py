"""通用契約 v1 的執行期驗證（Pydantic v2）。

規則與 contract/*.schema.json 一致，由 tests/test_contract.py 以同一組案例交叉驗證。
被監控服務的回應是不可信資料：只驗證、不重算 topology_version。
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

SUPPORTED_SCHEMA_VERSIONS: set[int] = {1}

IdStr = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]*$")]
ReasonStr = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
Timestamp = Annotated[
    str,
    StringConstraints(
        pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$"
    ),
]
VersionStr = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]
State = Literal["ok", "degraded", "unavailable", "waiting", "disabled"]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
MetricValue = int | FiniteFloat | str | bool | None


class ContractError(Exception):
    """回應不符契約。code 為 connection 代碼（invalid_response 或 incompatible）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, populate_by_name=True, frozen=True)


class Lane(_Model):
    id: IdStr
    label: str
    parent: IdStr | None
    sequential: bool
    nodes: list[IdStr]


class TopologyNode(_Model):
    id: IdStr
    label: str
    upstream: list[IdStr]
    dependencies: list[IdStr]


class TopologyDoc(_Model):
    schema_version: int
    service: IdStr
    instance: str = Field(min_length=1)
    topology_version: VersionStr
    lanes: list[Lane]
    nodes: list[TopologyNode]


class NodeStatus(_Model):
    state: State
    reason: ReasonStr | None
    message: str | None = Field(max_length=200)
    since: Timestamp
    metrics: dict[str, MetricValue]


class StatusTransition(_Model):
    node: IdStr
    from_: State | None = Field(alias="from")
    to: State
    reason: ReasonStr | None
    at: Timestamp


class StatusDoc(_Model):
    schema_version: int
    service: IdStr
    instance: str = Field(min_length=1)
    topology_version: VersionStr
    started_at: Timestamp
    evaluated_at: Timestamp | None
    evaluation_age_s: float = Field(ge=0, allow_inf_nan=False)
    nodes: dict[IdStr, NodeStatus]
    recent_transitions: list[StatusTransition] = Field(max_length=50)

    @model_validator(mode="after")
    def _empty_before_first_evaluation(self) -> StatusDoc:
        if self.evaluated_at is None and (self.nodes or self.recent_transitions):
            raise ValueError("evaluated_at 為 null 時 nodes 與 recent_transitions 必須為空")
        return self


def _reject_constant(name: str) -> Any:
    raise ValueError(f"不允許的 JSON 常數 {name}")


def _load(body: bytes | str) -> dict[str, Any]:
    """解析 JSON 並檢查 schema_version；失敗拋 ContractError。"""
    try:
        data = json.loads(body, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:  # 含 UnicodeDecodeError、JSONDecodeError
        raise ContractError("invalid_response", f"不是有效的 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError("invalid_response", "頂層不是物件")
    version = data.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ContractError("invalid_response", "schema_version 缺少或不是整數")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ContractError("incompatible", f"不支援的 schema_version {version}")
    return data


_M = TypeVar("_M", bound=_Model)


def _validate(model: type[_M], body: bytes | str) -> _M:
    data = _load(body)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise ContractError("invalid_response", f"{where}: {first['msg']}") from exc


def parse_topology(body: bytes | str) -> TopologyDoc:
    return _validate(TopologyDoc, body)


def parse_status(body: bytes | str) -> StatusDoc:
    return _validate(StatusDoc, body)
