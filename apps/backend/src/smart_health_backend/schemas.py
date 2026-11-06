"""API 專用的回應模型；目標相關的模型直接重用 models.py。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class ConfigResponse(_Frozen):
    poll_interval_s: float


class HealthResponse(_Frozen):
    status: str


class ErrorResponse(_Frozen):
    detail: str
