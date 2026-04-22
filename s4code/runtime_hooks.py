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

    def flush_compaction_result(self, agent: Any) -> None:
        if self._pending_compactions <= 0 or self._emitter is None:
            return
        usage = {}
        try:
            usage = dict(agent.get_context_usage() or {})
        except Exception:
            usage = {}
        compaction = dict(usage.get("compaction") or {})
        if not bool(compaction.get("was_compacted", False)):
            self._pending_compactions -= 1
            return
        message = (
            f"History compaction finished: "
            f"{compaction.get('tokens_before', '?')} -> {compaction.get('tokens_after', '?')} "
            f"(budget={compaction.get('max_tokens', '?')}, changed={compaction.get('was_compacted', False)})."
        )
        self._emitter(
            {
                "type": "compaction_result",
                "content": message,
                "compaction": compaction,
            }
        )
        self._pending_compactions -= 1
