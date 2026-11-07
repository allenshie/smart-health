"""每個目標一個獨立 asyncio task，定期拉取 /topology 與 /status（SPEC §6.1）。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TypeVar

import httpx

from .config import AppConfig, TargetConfig
from .contract import ContractError, TopologyDoc, parse_status, parse_topology
from .store import TargetStore

log = logging.getLogger(__name__)

_T = TypeVar("_T")
_DETAIL_LIMIT = 200
# 要求不壓縮：上限計算的就是實際傳輸的位元組，也避免小型壓縮資料解壓後暴增
_REQUEST_HEADERS = {"Accept-Encoding": "identity"}


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
        self._running = False
        # 每個目標：目前採用的架構版本、上一次成功的 started_at、上一輪的連線代碼
        self._versions: dict[str, str] = {}
        self._started_at: dict[str, str] = {}
        self._last_code: dict[str, str] = {}

    async def run(self) -> None:
        """啟動全部目標的拉取，直到 stop() 或本協程被取消。

        結束時（無論原因）一定取消並等待自己建立的 task。
        已經 stop() 之後呼叫 run() 會立刻返回，不建立任何 task；
        重複呼叫（前一次 run 尚未結束）拋 RuntimeError。
        """
        if self._running:
            raise RuntimeError("Poller.run() 已在執行")
        if self._stopped.is_set():
            return
        self._running = True
        try:
            self._tasks = [
                asyncio.create_task(self._loop(t), name=f"poll-{t.id}")
                for t in self._config.targets
            ]
            await self._stopped.wait()
        finally:
            await self._cancel_tasks()
            self._running = False

    async def stop(self) -> None:
        """停止拉取並等待所有 task 結束；可在 run() 開始前或重複呼叫。"""
        self._stopped.set()
        await self._cancel_tasks()

    async def _cancel_tasks(self) -> None:
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _loop(self, target: TargetConfig) -> None:
        loop = asyncio.get_running_loop()
        interval = self._config.poll_interval_s
        while True:
            started = loop.time()
            try:
                await self._poll_once(target)
            except Exception:  # 任何錯誤（含寫入 store 失敗）都不能讓目標的 task 結束
                log.exception("目標 %s 的拉取迴圈發生未預期錯誤", target.id)
            await asyncio.sleep(max(0.0, interval - (loop.time() - started)))

    async def _poll_once(self, target: TargetConfig) -> None:
        try:
            await self._round(target)
        except _PollFailure as failure:
            self._note_code(target.id, failure.code, failure)
            self._store.apply_failure(target.id, failure.code)
        except Exception:
            log.exception("目標 %s 拉取時發生未預期錯誤", target.id)
            self._note_code(target.id, "offline", None)
            self._store.apply_failure(target.id, "offline")

    def _note_code(self, tid: str, code: str, failure: Exception | None) -> None:
        """連線代碼改變時才記 log：失敗記 warning，恢復 online 記一次 info。"""
        previous = self._last_code.get(tid)
        self._last_code[tid] = code
        if code == previous:
            return
        if code == "online":
            if previous is not None:
                log.info("目標 %s 已恢復 online（先前為 %s）", tid, previous)
        else:
            detail = repr(str(failure)[:_DETAIL_LIMIT]) if failure is not None else "未預期錯誤"
            log.warning("目標 %s 連線狀態變為 %s: %s", tid, code, detail)

    async def _round(self, target: TargetConfig) -> None:
        tid = target.id
        if tid not in self._versions:
            self._adopt_topology(tid, await self._get(target, "/topology", parse_topology))
        status = await self._get(target, "/status", parse_status)
        if (
            status.topology_version != self._versions[tid]
            or status.started_at != self._started_at.get(tid, status.started_at)
        ):
            fresh = await self._get(target, "/topology", parse_topology)
            if fresh.topology_version != status.topology_version:
                # 重新取得的版本仍與 /status 不一致：不採用，保留上一份架構
                raise _PollFailure("invalid_response", "重新取得架構後版本仍與 /status 不一致")
            self._adopt_topology(tid, fresh)
        self._started_at[tid] = status.started_at
        stale = status.evaluation_age_s > self._config.evaluation_stale_after_s
        connection = "stale" if stale else "online"
        self._note_code(tid, connection, _PollFailure("stale", "評估過久未更新") if stale else None)
        self._store.apply_status(tid, status, connection)

    def _adopt_topology(self, tid: str, topology: TopologyDoc) -> None:
        self._store.set_topology(tid, topology)
        self._versions[tid] = topology.topology_version

    async def _get(
        self, target: TargetConfig, path: str, parse: Callable[[bytes], _T]
    ) -> _T:
        timeout = self._config.request_timeout_s
        url = target.base_url.rstrip("/") + path
        try:
            # asyncio.timeout 是「request_timeout_s 涵蓋整個請求，含讀取本文」的保證（SPEC §6.1）：
            # httpx 的 timeout 是逐階段計算，慢速滴漏（每次只送幾個位元組）的本文不會觸發它
            async with asyncio.timeout(timeout):
                body = await self._read_limited(url, path, timeout)
        except _PollFailure:
            raise
        except (TimeoutError, httpx.HTTPError, OSError) as exc:
            raise _PollFailure("offline", f"{path}: {type(exc).__name__}") from exc
        try:
            return parse(body)
        except ContractError as exc:
            raise _PollFailure(exc.code, f"{path}: {exc.detail}") from exc

    async def _read_limited(self, url: str, path: str, timeout: float) -> bytes:
        """串流讀取本文，超過 max_response_bytes 就停止（SPEC §6.1）。

        失敗一律在 `async with` 內拋出，httpx 會關閉這條連線，不會放回連線池。
        log 的 detail 只寫超過上限，不帶入本文內容。
        """
        limit = self._config.max_response_bytes
        async with self._client.stream(
            "GET", url, headers=_REQUEST_HEADERS, follow_redirects=False, timeout=timeout
        ) as response:
            if not response.is_success:  # 非 2xx 不讀本文
                raise _PollFailure("offline", f"{path}: HTTP {response.status_code}")
            declared = response.headers.get("content-length")
            if declared is not None and declared.isdigit() and int(declared) > limit:
                raise _PollFailure("invalid_response", f"{path}: Content-Length 超過上限")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > limit:  # 嚴格大於：剛好等於上限可接受
                    raise _PollFailure("invalid_response", f"{path}: 本文超過上限")
        return bytes(body)
