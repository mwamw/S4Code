"""S4Code product-side runtime hooks."""

from __future__ import annotations

from typing import Any, Callable, Optional

from ._easyagent_bootstrap import ensure_easyagent_environment

ensure_easyagent_environment()

from core.hooks import BaseHook


class S4RuntimeNoticeHook(BaseHook):
    """Publishes product-visible runtime notices such as history compaction."""

    def __init__(self) -> None:
        self._emitter: Optional[Callable[[dict[str, Any]], None]] = None
        self._pending_compactions = 0

    @property
    def has_pending_compactions(self) -> bool:
        return self._pending_compactions > 0

    def bind_emitter(self, emitter: Optional[Callable[[dict[str, Any]], None]]) -> None:
        self._emitter = emitter

    def before_compaction(self, payload: dict[str, Any]):
        self._pending_compactions += 1
        if self._emitter is not None:
            tokens_before = payload.get("tokens_before")
            budget = payload.get("max_tokens")
            detail = ""
            if tokens_before is not None and budget is not None:
                detail = f" (tokens={tokens_before}, budget={budget})"
            self._emitter(
                {
                    "type": "compaction_start",
                    "operation": payload.get("operation"),
                    "max_tokens": budget,
                    "tokens_before": tokens_before,
                    "force": bool(payload.get("force")),
                    "content": (
                        f"Compacting history with the active LLM compressor "
                        f"using the current context budget{detail}."
                    ),
                }
            )
        return None

    @staticmethod
    def _extract_compaction_state(agent: Any) -> dict[str, Any]:
        usage = {}
        try:
            usage = dict(agent.get_context_usage() or {})
        except Exception:
            usage = {}
        compaction_raw = usage.get("last_history_compaction")
        if not isinstance(compaction_raw, dict):
            compaction_raw = usage.get("compaction") or {}
        compaction = dict(compaction_raw or {})
        if "max_tokens" not in compaction and compaction.get("budget") is not None:
            compaction["max_tokens"] = compaction.get("budget")
        return compaction

    @staticmethod
    def _format_compaction_message(compaction: dict[str, Any]) -> str:
        if not compaction:
            return "History compaction finished."
        if compaction.get("hook_blocked"):
            detail = str(compaction.get("hook_message") or "blocked by a runtime hook")
            return f"History compaction blocked: {detail}"
        budget = compaction.get("max_tokens", "?")
        before = compaction.get("tokens_before", "?")
        after = compaction.get("tokens_after", "?")
        if bool(compaction.get("was_compacted", False)):
            return (
                f"History compaction finished: "
                f"{before} -> {after} (budget={budget}, changed=True)."
            )
        if compaction.get("compaction_possible") is False:
            return (
                f"History compaction not needed: "
                f"{before} token(s) already fit within the budget ({budget})."
            )
        return f"History compaction finished without changes (budget={budget})."

    def flush_compaction_result(self, agent: Any) -> None:
        if self._pending_compactions <= 0 or self._emitter is None:
            return
        compaction = self._extract_compaction_state(agent)
        self._emitter(
            {
                "type": "compaction_result",
                "content": self._format_compaction_message(compaction),
                "compaction": compaction,
            }
        )
        self._pending_compactions -= 1
