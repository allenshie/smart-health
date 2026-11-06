"""每個目標一個獨立 asyncio task，定期拉取 /topology 與 /status（SPEC §6.1）。"""

from __future__ import annotations

import asyncio
import logging

import httpx

from .config import AppConfig, TargetConfig
from .contract import ContractError, StatusDoc, TopologyDoc, parse_status, parse_topology
from .store import TargetStore

log = logging.getLogger(__name__)


class _PollFailure(Exception):
    """本輪失敗；code 為 connection 代碼。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


class Poller:
    def __init__(self, config: AppConfig, store: TargetStore, client: httpx.AsyncClient) -> None:
        self._config = config
        self._store = store
        self._client = client
        self._tasks: list[asyncio.Task[None]] = []
        self._stopped = asyncio.Event()
        # 每個目標：目前採用的架構版本，與上一次成功取得的 started_at
        self._versions: dict[str, str] = {}
        self._started_at: dict[str, str] = {}

    async def run(self) -> None:
        """啟動全部目標的拉取，直到 stop()。"""
        self._tasks = [
            asyncio.create_task(self._loop(t), name=f"poll-{t.id}") for t in self._config.targets
        ]
        await self._stopped.wait()

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        self._stopped.set()

    async def _loop(self, target: TargetConfig) -> None:
        loop = asyncio.get_running_loop()
        interval = self._config.poll_interval_s
        while True:
            started = loop.time()
            await self._poll_once(target)
            await asyncio.sleep(max(0.0, interval - (loop.time() - started)))

    async def _poll_once(self, target: TargetConfig) -> None:
        try:
            await self._round(target)
        except _PollFailure as failure:
            log.warning("目標 %s 拉取失敗: %s (%s)", target.id, failure.code, failure)
            self._store.apply_failure(target.id, failure.code)
        except Exception:  # 單一目標的未預期錯誤不能中止它的拉取迴圈
            log.exception("目標 %s 拉取時發生未預期錯誤", target.id)
            self._store.apply_failure(target.id, "offline")

    async def _round(self, target: TargetConfig) -> None:
        tid = target.id
        if tid not in self._versions:
            await self._fetch_topology(target)
        status = await self._fetch_status(target)
        if (
            status.topology_version != self._versions[tid]
            or status.started_at != self._started_at.get(tid, status.started_at)
        ):
            await self._fetch_topology(target)
            if status.topology_version != self._versions[tid]:
                raise _PollFailure("invalid_response", "重新取得架構後版本仍與 /status 不一致")
        self._started_at[tid] = status.started_at
        age_limit = self._config.evaluation_stale_after_s
        connection = "stale" if status.evaluation_age_s > age_limit else "online"
        self._store.apply_status(tid, status, connection)

    async def _fetch_topology(self, target: TargetConfig) -> None:
        topology: TopologyDoc = await self._get(target, "/topology", parse_topology)
        self._store.set_topology(target.id, topology)
        self._versions[target.id] = topology.topology_version

    async def _fetch_status(self, target: TargetConfig) -> StatusDoc:
        return await self._get(target, "/status", parse_status)

    async def _get(self, target: TargetConfig, path: str, parse):
        timeout = self._config.request_timeout_s
        url = target.base_url.rstrip("/") + path
        try:
            # MockTransport 不套用 httpx timeout，所以外層一律再包 asyncio.timeout
            async with asyncio.timeout(timeout):
                response = await self._client.get(url, follow_redirects=False, timeout=timeout)
        except (TimeoutError, httpx.HTTPError, OSError) as exc:
            raise _PollFailure("offline", f"{path}: {type(exc).__name__}") from exc
        if not response.is_success:
            raise _PollFailure("offline", f"{path}: HTTP {response.status_code}")
        try:
            return parse(response.content)
        except ContractError as exc:
            raise _PollFailure(exc.code, f"{path}: {exc.detail}") from exc
