"""後端設定載入與驗證（SPEC §6）。設定無效時拋 ConfigError，訊息含欄位路徑。"""

from __future__ import annotations

import math
from collections.abc import Hashable
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

DEFAULTS: dict[str, float | int] = {
    "poll_interval_s": 5,
    "request_timeout_s": 2,
    "evaluation_stale_after_s": 10,
    "history_limit": 200,
    "max_response_bytes": 1048576,
}
_POSITIVE_NUMBERS = ("poll_interval_s", "request_timeout_s", "evaluation_stale_after_s")
_POSITIVE_INTS = ("history_limit", "max_response_bytes")
_TOP_KEYS = set(DEFAULTS) | {"targets"}
_TARGET_KEYS = {"id", "name", "base_url"}


class ConfigError(ValueError):
    """設定無效；訊息開頭為欄位路徑。"""


@dataclass(frozen=True)
class TargetConfig:
    id: str
    name: str
    base_url: str


@dataclass(frozen=True)
class AppConfig:
    poll_interval_s: float = 5
    request_timeout_s: float = 2
    evaluation_stale_after_s: float = 10
    history_limit: int = 200
    max_response_bytes: int = 1048576  # 單次回應本文的上限（SPEC §6.1）
    targets: list[TargetConfig] = field(default_factory=list)


class _UniqueKeyLoader(yaml.SafeLoader):
    """拒絕重複鍵的 SafeLoader；只用於本模組，不改全域行為。"""

    def construct_mapping(self, node, deep=False):  # type: ignore[no-untyped-def]
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            if not isinstance(key, Hashable):
                continue  # 交給父類別報錯
            if key in seen:
                raise ConfigError(f"重複的 YAML 鍵 {key!r}（第 {key_node.start_mark.line + 1} 行）")
            seen.add(key)
        return super().construct_mapping(node, deep)


def _check_unknown(mapping: dict[str, Any], allowed: set[str], path: str) -> None:
    for key in mapping:
        if key not in allowed:
            name = f"{path}.{key}" if path else str(key)
            raise ConfigError(f"{name}: 未知欄位")


def _positive_number(value: Any, path: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"{path}: 必須是正數")
    if not math.isfinite(value) or value <= 0:
        raise ConfigError(f"{path}: 必須是有限的正數")
    return value


def _positive_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{path}: 必須是正整數")
    return value


def _parse_target(raw: Any, index: int, seen: set[str]) -> TargetConfig:
    path = f"targets[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: 必須是 mapping")
    _check_unknown(raw, _TARGET_KEYS, path)
    for key in ("id", "name", "base_url"):
        if key not in raw:
            raise ConfigError(f"{path}.{key}: 必填")
    target_id, name, base_url = raw["id"], raw["name"], raw["base_url"]
    if not isinstance(target_id, str) or not _ID_RE.fullmatch(target_id):
        raise ConfigError(f"{path}.id: 必須符合 ^[a-z][a-z0-9_-]*$")
    if target_id in seen:
        raise ConfigError(f"{path}.id: 重複的 id {target_id!r}")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{path}.name: 必須是非空字串")
    if not isinstance(base_url, str):
        raise ConfigError(f"{path}.base_url: 必須是字串")
    if base_url != base_url.strip() or "?" in base_url or "#" in base_url:
        raise ConfigError(f"{path}.base_url: 不可含前後空白、query 或 fragment")
    try:
        parts = urlsplit(base_url)
        host = parts.hostname
        parts.port  # noqa: B018  觸發連接埠格式檢查
    except ValueError as exc:
        raise ConfigError(f"{path}.base_url: 格式無效") from exc
    if parts.scheme not in ("http", "https") or not host:
        raise ConfigError(f"{path}.base_url: 必須是含主機的 http 或 https 位址")
    if parts.username is not None or parts.password is not None:
        # /status 不需要驗證；含帳密的網址可能被 httpx 的 log 原樣印出
        raise ConfigError(f"{path}.base_url: 不可含帳密")
    seen.add(target_id)
    return TargetConfig(id=target_id, name=name, base_url=base_url)


def parse_config(data: Any) -> AppConfig:
    """驗證已解析的設定資料。"""
    if not isinstance(data, dict):
        raise ConfigError("設定頂層必須是 mapping")
    _check_unknown(data, _TOP_KEYS, "")
    values: dict[str, Any] = dict(DEFAULTS)
    values.update({k: data[k] for k in DEFAULTS if k in data})
    for key in _POSITIVE_NUMBERS:
        values[key] = _positive_number(values[key], key)
    for key in _POSITIVE_INTS:
        values[key] = _positive_int(values[key], key)
    if "targets" not in data:
        raise ConfigError("targets: 必填")
    raw_targets = data["targets"]
    if not isinstance(raw_targets, list):
        raise ConfigError("targets: 必須是清單")
    seen: set[str] = set()
    targets = [_parse_target(item, i, seen) for i, item in enumerate(raw_targets)]
    return AppConfig(targets=targets, **values)


def load_config(path: Path) -> AppConfig:
    """讀取並驗證 YAML 設定檔。"""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"無法讀取設定檔 {path}: {exc.strerror or exc}") from exc
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506  自訂 SafeLoader 子類
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML 語法錯誤: {exc}") from exc
    return parse_config(data)
