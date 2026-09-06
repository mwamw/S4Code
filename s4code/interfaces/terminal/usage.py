"""Context budgets, usage metrics and execution trace presentation."""

from __future__ import annotations

import json
from typing import Any, Optional


from .formatting import _normalize_cache_accounting, _extract_last_compaction_state


class UsagePresenter:
    def __init__(self, controller):
        self.controller = controller

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            if value is None:
                return None
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _ratio(numerator: Any, denominator: Any) -> Optional[float]:
        left = UsagePresenter._safe_float(numerator)
        right = UsagePresenter._safe_float(denominator)
        if left is None or right is None or right <= 0:
            return None
        return max(min(left / right, 1.0), 0.0)

    @staticmethod
    def _format_percent(ratio: Any) -> str:
        value = UsagePresenter._safe_float(ratio)
        if value is None:
            return "-"
        return f"{value * 100:.0f}%"

    @staticmethod
    def _format_ratio_bar(ratio: Any, *, width: int = 16) -> str:
        value = UsagePresenter._safe_float(ratio)
        if value is None:
            return "[" + ("-" * max(int(width), 1)) + "]"
        bounded = max(min(value, 1.0), 0.0)
        slots = max(int(width), 1)
        filled = min(slots, int(round(bounded * slots)))
        return "[" + ("#" * filled) + ("-" * (slots - filled)) + "]"

    def _context_usage_summary(
        self, usage: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        payload = dict(usage or self.controller.core.inspector.read("context") or {})
        budget = dict(payload.get("budget") or {})
        request_estimate = dict(payload.get("requestEstimate") or {})
        token_breakdown = dict(payload.get("tokenBreakdown") or {})
        history_payload = dict(payload.get("history") or {})
        used_tokens = self._safe_int(payload.get("used_tokens"))
        estimated_request_tokens = self._safe_int(
            payload.get("estimated_request_tokens")
        )
        if estimated_request_tokens is None:
            estimated_request_tokens = self._safe_int(
                request_estimate.get("estimatedRequestTokens")
            )
        if estimated_request_tokens is None:
            estimated_request_tokens = self._safe_int(
                payload.get("estimatedRequestTokens")
            )
        if used_tokens is None:
            used_tokens = estimated_request_tokens
        max_tokens = self._safe_int(payload.get("max_tokens"))
        if max_tokens is None:
            max_tokens = self._safe_int(budget.get("maxTokens"))
        if max_tokens is None:
            max_tokens = self.controller.settings.context.max_tokens
        remaining_tokens = self._safe_int(payload.get("remaining_tokens"))
        if remaining_tokens is None:
            remaining_tokens = self._safe_int(budget.get("remainingTokens"))
        if (
            remaining_tokens is None
            and max_tokens is not None
            and used_tokens is not None
        ):
            remaining_tokens = max(max_tokens - used_tokens, 0)
        request_layers = dict(
            payload.get("request_layers") or payload.get("requestLayers") or {}
        )
        history_budget_tokens = self._safe_int(payload.get("history_budget_tokens"))
        if history_budget_tokens is None:
            history_budget_tokens = self._safe_int(budget.get("historyBudgetTokens"))
        history_tokens = self._safe_int(payload.get("history_tokens"))
        if history_tokens is None:
            history_tokens = self._safe_int(token_breakdown.get("historyTokens"))
        system_tokens = self._safe_int(payload.get("system_tokens"))
        if system_tokens is None:
            system_tokens = self._safe_int(token_breakdown.get("systemTokens"))
        tool_tokens = self._safe_int(payload.get("tool_tokens"))
        if tool_tokens is None:
            tool_tokens = self._safe_int(token_breakdown.get("toolTokens"))
        reasoning_tokens = self._safe_int(payload.get("reasoning_tokens"))
        if reasoning_tokens is None:
            reasoning_tokens = self._safe_int(token_breakdown.get("reasoningTokens"))
        ratio = self._ratio(
            used_tokens if used_tokens is not None else estimated_request_tokens,
            max_tokens,
        )
        compaction = _extract_last_compaction_state(payload)
        if not compaction:
            compaction = dict(
                getattr(self.controller, "_last_manual_compaction", {}) or {}
            )
        cache_state = dict(payload.get("cache") or {})
        return {
            "used_tokens": used_tokens,
            "max_tokens": max_tokens,
            "remaining_tokens": remaining_tokens,
            "estimated_request_tokens": estimated_request_tokens,
            "usage_ratio": ratio,
            "usage_percent": self._format_percent(ratio),
            "usage_bar": self._format_ratio_bar(ratio),
            "history_budget_tokens": history_budget_tokens,
            "history_tokens": history_tokens,
            "system_tokens": system_tokens,
            "tool_tokens": tool_tokens,
            "reasoning_tokens": reasoning_tokens,
            "request_layers": request_layers,
            "request_estimate_source": str(
                payload.get("request_estimate_source")
                or request_estimate.get("source")
                or ""
            ),
            "canonical_history_messages": self._safe_int(
                history_payload.get(
                    "canonicalMessages", payload.get("canonicalMessages")
                )
            ),
            "replay_history_messages": self._safe_int(
                history_payload.get("replayMessages", payload.get("replayMessages"))
            ),
            "pending_step_active": bool(
                history_payload.get("pendingStepActive")
                or payload.get("pending_step_active")
            ),
            "compaction": compaction,
            "cache": cache_state,
        }

    @staticmethod
    def _cache_summary_from_llm_items(
        llm_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prompt_tokens_total = 0
        prompt_tokens_uncached = 0
        prompt_tokens_cached = 0
        cached_input_tokens = 0
        cache_read_tokens = 0
        cache_creation_tokens = 0
        for item in llm_items:
            total_prompt, uncached_prompt, cached_prompt = _normalize_cache_accounting(
                item
            )
            prompt_tokens_total += int(total_prompt or 0)
            prompt_tokens_uncached += int(uncached_prompt or 0)
            prompt_tokens_cached += int(cached_prompt or 0)
            cached_input_tokens += int(
                item.get("cachedInputTokens") or item.get("cached_input_tokens") or 0
            )
            cache_read_tokens += int(
                item.get("cacheReadTokens") or item.get("cache_read_tokens") or 0
            )
            cache_creation_tokens += int(
                item.get("cacheCreationTokens")
                or item.get("cache_creation_tokens")
                or 0
            )
        cache_hit_ratio = None
        if prompt_tokens_total > 0:
            cache_hit_ratio = float(prompt_tokens_cached) / float(prompt_tokens_total)
        return {
            "prompt_tokens_total": prompt_tokens_total,
            "prompt_tokens_uncached": prompt_tokens_uncached,
            "prompt_tokens_cached": prompt_tokens_cached,
            "cache_hit_tokens": prompt_tokens_cached,
            "cache_hit_ratio": cache_hit_ratio,
            "cached_input_tokens": cached_input_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_creation_tokens": cache_creation_tokens,
        }

    def _format_context_meter_line(self, usage_summary: dict[str, Any]) -> str:
        used_tokens = usage_summary.get("used_tokens")
        max_tokens = usage_summary.get("max_tokens")
        remaining_tokens = usage_summary.get("remaining_tokens")
        return (
            "Context: "
            f"{usage_summary.get('usage_bar')} {usage_summary.get('usage_percent')} "
            f"({used_tokens if used_tokens is not None else '?'} / {max_tokens if max_tokens is not None else '?'} used, "
            f"{remaining_tokens if remaining_tokens is not None else '?'} remaining)"
        )

    def get_context_panel_payload(self) -> dict[str, Any]:
        usage_summary = self._context_usage_summary()
        compaction = dict(usage_summary.get("compaction") or {})
        cache_state = dict(usage_summary.get("cache") or {})
        return {
            **usage_summary,
            "last_compaction_changed": bool(compaction.get("was_compacted")),
            "last_compaction_before": self._safe_int(compaction.get("tokens_before")),
            "last_compaction_after": self._safe_int(compaction.get("tokens_after")),
            "last_compaction_budget": self._safe_int(compaction.get("max_tokens")),
            "cache_enabled": bool(cache_state.get("enabled")),
            "cache_anchor_active": bool(cache_state.get("anchorActive")),
            "cache_pending_anchor": bool(cache_state.get("pendingAnchorActive")),
            "cache_last_usage": dict(cache_state.get("lastCacheUsage") or {}),
            "cache_last_break": dict(cache_state.get("lastBreak") or {}),
            "cache_provider_capability": dict(
                cache_state.get("providerCapability") or {}
            ),
        }

    def _build_round_metrics(
        self,
        *,
        round_number: int,
        turn_started_at: float,
    ) -> dict[str, Any]:
        records = self._observability_records()
        record = next(
            (
                item
                for item in reversed(records)
                if (
                    self.controller._parse_iso_timestamp(item["stats"]["started_at"])
                    or 0
                )
                >= turn_started_at
            ),
            None,
        )
        if record is None:
            return {}
        llm_items = record["llm_invokes"]
        cache_summary = self._cache_summary_from_llm_items(
            [dict(item.get("stats") or {}) for item in llm_items]
        )
        context_summary = self._context_usage_summary()
        stats = record["stats"]

        return {
            "round": round_number,
            "llm_requests": stats["llm_calls"],
            "tool_calls": stats["tool_calls"],
            "llm_duration_ms": sum(
                item["stats"]["duration_ms"] for item in record["llm_invokes"]
            ),
            "tool_duration_ms": stats["tool_duration_ms"],
            "input_tokens": stats["input_tokens"],
            "output_tokens": stats["output_tokens"],
            "total_tokens": stats["total_tokens"],
            "estimated_cost_usd": stats["estimated_cost_usd"],
            "context_used_tokens": context_summary.get("used_tokens"),
            "context_max_tokens": context_summary.get("max_tokens"),
            "context_remaining_tokens": context_summary.get("remaining_tokens"),
            "context_usage_ratio": context_summary.get("usage_ratio"),
            "context_usage_percent": context_summary.get("usage_percent"),
            "prompt_tokens_total": cache_summary.get("prompt_tokens_total"),
            "prompt_tokens_cached": cache_summary.get("prompt_tokens_cached"),
            "prompt_tokens_uncached": cache_summary.get("prompt_tokens_uncached"),
            "cache_hit_tokens": cache_summary.get("cache_hit_tokens"),
            "cache_hit_ratio": cache_summary.get("cache_hit_ratio"),
            "cached_input_tokens": cache_summary.get("cached_input_tokens"),
            "cache_read_tokens": cache_summary.get("cache_read_tokens"),
            "cache_creation_tokens": cache_summary.get("cache_creation_tokens"),
            "tools_used": [],
        }

    def _observability_records(self) -> list[Any]:
        return self.controller.core.inspector.read("metrics", limit=10000)

    def _trace_summaries(self, *, limit: int) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for record in reversed(self._observability_records()[-max(int(limit), 0) :]):
            stats = record["stats"]
            summaries.append(
                {
                    "query": record["query"],
                    "status": stats["status"],
                    "success": stats["success"],
                    "durationMs": stats["duration_ms"],
                    "totalTokens": stats["total_tokens"],
                    "toolCalls": stats["tool_calls"],
                    "llmRequests": stats["llm_calls"],
                    "estimatedCostUsd": stats["estimated_cost_usd"],
                    "llmInvokes": record["llm_invokes"],
                }
            )
        return summaries

    def format_context(self) -> str:
        payload = self.get_context_panel_payload()
        lines = [
            "Context usage",
            f"- {self._format_context_meter_line(payload)}",
        ]
        estimate = payload.get("estimated_request_tokens")
        if estimate is not None:
            lines.append(f"- Estimated request size: {estimate} token(s)")
        breakdown_bits: list[str] = []
        for label, key in (
            ("history", "history_tokens"),
            ("system", "system_tokens"),
            ("tools", "tool_tokens"),
            ("reasoning", "reasoning_tokens"),
        ):
            value = payload.get(key)
            if value is not None:
                breakdown_bits.append(f"{label}={value}")
        if breakdown_bits:
            lines.append(f"- Breakdown: {', '.join(breakdown_bits)}")
        history_budget = payload.get("history_budget_tokens")
        history_tokens = payload.get("history_tokens")
        if history_budget is not None and history_tokens is not None:
            lines.append(f"- History budget: {history_tokens} / {history_budget}")
        canonical_messages = payload.get("canonical_history_messages")
        replay_messages = payload.get("replay_history_messages")
        if canonical_messages is not None or replay_messages is not None:
            lines.append(
                f"- Messages: canonical={canonical_messages if canonical_messages is not None else '?'}"
                f", replay={replay_messages if replay_messages is not None else '?'}"
            )
        estimate_source = str(payload.get("request_estimate_source") or "").strip()
        if estimate_source:
            lines.append(f"- Estimate source: {estimate_source}")
        compaction = dict(payload.get("compaction") or {})
        if compaction:
            if compaction.get("hook_blocked"):
                lines.append(
                    f"- Last compaction: blocked ({compaction.get('hook_message') or 'runtime hook'})"
                )
            elif compaction.get("was_compacted"):
                lines.append(
                    f"- Last compaction: {compaction.get('tokens_before', '?')} -> {compaction.get('tokens_after', '?')} "
                    f"(budget {compaction.get('max_tokens', '?')})"
                )
            elif compaction.get("compaction_possible") is False:
                lines.append("- Last compaction: not needed")
        cache_state = dict(payload.get("cache") or {})
        if cache_state:
            if cache_state.get("enabled"):
                lines.append(
                    f"- Cache: enabled | anchor={bool(cache_state.get('anchorActive'))} | "
                    f"pending={bool(cache_state.get('pendingAnchorActive'))}"
                )
            else:
                lines.append("- Cache: disabled")
            last_usage = dict(cache_state.get("lastCacheUsage") or {})
            usage_bits: list[str] = []
            for label, key in (
                ("cachedInput", "cachedInputTokens"),
                ("cacheRead", "cacheReadTokens"),
                ("cacheCreate", "cacheCreationTokens"),
            ):
                value = self._safe_int(last_usage.get(key))
                if value:
                    usage_bits.append(f"{label}={value}")
            if usage_bits:
                lines.append(f"- Last cache usage: {', '.join(usage_bits)}")
            last_break = dict(cache_state.get("lastBreak") or {})
            if last_break:
                reason = str(
                    last_break.get("reason") or last_break.get("type") or ""
                ).strip()
                field = str(
                    last_break.get("field") or last_break.get("cache_field") or ""
                ).strip()
                if reason or field:
                    extra = f" ({field})" if field else ""
                    lines.append(f"- Last cache break: {reason or 'changed'}{extra}")
        lines.extend(
            [
                "",
                "Next step:",
                "- Use `/compact` if the context meter is getting tight.",
                "- Use `/cost` to inspect cache hit rate and recent turn usage.",
            ]
        )
        return "\n".join(lines)

    def format_cost(self) -> str:
        records = self._observability_records()
        recent_turns = self._trace_summaries(limit=5)
        total_tokens = sum(item["stats"]["total_tokens"] for item in records)
        costs = [
            item["stats"]["estimated_cost_usd"]
            for item in records
            if item["stats"]["estimated_cost_usd"] is not None
        ]
        llm_stats = [llm["stats"] for item in records for llm in item["llm_invokes"]]
        cache = self._cache_summary_from_llm_items(llm_stats)
        lines = [
            "Usage and cache",
            f"- Total tokens: {total_tokens}",
            f"- Estimated cost: ${sum(costs):.4f}"
            if costs
            else "- Estimated cost: unavailable",
        ]
        cache_ratio = self._safe_float(cache.get("cache_hit_ratio"))
        if cache_ratio is not None:
            lines.append(
                f"- Cache hit rate: {self._format_percent(cache_ratio)} "
                f"({cache.get('cache_hit_tokens', 0)} cached prompt token(s))"
            )
        lines.append("")
        lines.append("Recent turns:")
        if recent_turns:
            for item in recent_turns[:5]:
                query = " ".join(str(item.get("query") or "").split())
                short_query = query[:48] + "..." if len(query) > 48 else query
                ratio_payload = self._cache_summary_from_llm_items(
                    [dict(llm.get("stats") or {}) for llm in item.get("llmInvokes", [])]
                )
                ratio = ratio_payload.get("cache_hit_ratio")
                cache_suffix = (
                    f" | cache {self._format_percent(ratio)}"
                    if ratio is not None
                    else ""
                )
                lines.append(
                    f"- {short_query or '[no prompt]'} | tokens {item.get('totalTokens', 0)} | "
                    f"tools {item.get('toolCalls', 0)}{cache_suffix}"
                )
        else:
            lines.append("- No completed turns yet.")
        return "\n".join(lines)

    def format_trace(self, *, limit_turns: int = 5) -> str:
        turns = self._trace_summaries(limit=limit_turns)
        if not turns:
            return "No recent turn summaries yet."
        lines = ["Recent turns"]
        for item in turns:
            query = " ".join(str(item.get("query") or "").split())
            short_query = query[:72] + "..." if len(query) > 72 else query
            lines.append(
                f"- {short_query or '[no prompt]'} | status={item.get('status') or 'completed'} | "
                f"tokens={item.get('totalTokens', 0)} | tools={item.get('toolCalls', 0)} | "
                f"llm={item.get('llmRequests', 0)}"
            )
        return "\n".join(lines)

    def format_recent_events(
        self, *, limit: int = 20, event_type: Optional[str] = None
    ) -> str:
        normalized = str(event_type or "agent").strip().lower()
        if normalized == "runtime":
            payload = self.controller.core.inspector.read("trace", limit=limit)
        elif normalized == "llm":
            payload = [
                llm
                for record in self._observability_records()
                for llm in record["llm_invokes"]
            ][-limit:]
        else:
            payload = self._observability_records()[-limit:]
        return json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
