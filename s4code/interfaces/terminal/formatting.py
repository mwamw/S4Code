from __future__ import annotations
from typing import Any, Optional
from urllib.parse import urlparse


def _normalize_cache_accounting(item: dict[str, Any]) -> tuple[int, int, int]:
    """Normalize provider cache counters from an EasyAgent LLMInvoke payload."""

    input_tokens = int(item.get("inputTokens") or item.get("input_tokens") or 0)
    cached_tokens = int(
        item.get("cachedInputTokens")
        or item.get("cached_input_tokens")
        or item.get("cacheReadTokens")
        or item.get("cache_read_tokens")
        or 0
    )
    cached_tokens = min(max(cached_tokens, 0), max(input_tokens, 0))
    return input_tokens, max(input_tokens - cached_tokens, 0), cached_tokens


def _deep_merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _extract_last_compaction_state(usage: dict[str, Any]) -> dict[str, Any]:
    compaction_raw = usage.get("last_history_compaction")
    if not isinstance(compaction_raw, dict):
        container = usage.get("compaction")
        if isinstance(container, dict) and isinstance(container.get("last"), dict):
            compaction_raw = container.get("last") or {}
        else:
            compaction_raw = container or {}
    compaction = dict(compaction_raw or {})
    if "max_tokens" not in compaction and compaction.get("budget") is not None:
        compaction["max_tokens"] = compaction.get("budget")
    return compaction


def _safe_provider_endpoint(value: Any) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.hostname:
        return raw.split("?", 1)[0]
    host = parsed.hostname
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return f"{parsed.scheme}://{host}{parsed.path.rstrip('/')}"
