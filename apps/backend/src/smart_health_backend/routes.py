"""後端 API 路由（SPEC §6.2）。狀態從 request.app.state 取得，路由本身不含業務邏輯。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .models import TargetDetail, TargetSummary, Transition
from .schemas import ConfigResponse, ErrorResponse, HealthResponse

DEFAULT_TRANSITIONS_LIMIT = 50
NOT_FOUND = {404: {"model": ErrorResponse}}

router = APIRouter()


@router.get("/api/config", response_model=ConfigResponse)
async def get_config(request: Request) -> ConfigResponse:
    return ConfigResponse(poll_interval_s=request.app.state.config.poll_interval_s)


@router.get("/api/targets", response_model=list[TargetSummary])
async def list_targets(request: Request) -> list[TargetSummary]:
    return request.app.state.store.list_views()


@router.get("/api/targets/{target_id}", response_model=TargetDetail, responses=NOT_FOUND)
async def get_target(target_id: str, request: Request) -> TargetDetail:
    view = request.app.state.store.get_view(target_id)
    if view is None:
        raise HTTPException(status_code=404, detail="target_not_found")
    return view


@router.get(
    "/api/targets/{target_id}/transitions", response_model=list[Transition], responses=NOT_FOUND
)
async def get_transitions(
    target_id: str,
    request: Request,
    limit: Annotated[int, Query(ge=1)] = DEFAULT_TRANSITIONS_LIMIT,
) -> list[Transition]:
    state = request.app.state
    items = state.store.get_transitions(target_id, min(limit, state.config.history_limit))
    if items is None:
        raise HTTPException(status_code=404, detail="target_not_found")
    return items


@router.get("/healthz", response_model=HealthResponse)
async def healthz(request: Request) -> JSONResponse:
    task = request.app.state.run_task
    if task.done():
        return JSONResponse({"status": "poller_stopped"}, status_code=503)
    return JSONResponse({"status": "ok"})


@router.get("/api/{rest:path}", include_in_schema=False)
async def api_not_found(rest: str) -> JSONResponse:
    """未知的 /api 路徑一律回 404 JSON，不被靜態檔掛載遮住。"""
    return JSONResponse({"detail": "not_found"}, status_code=404)
