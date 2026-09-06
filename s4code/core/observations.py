"""Product runtime facts; no terminal messages or rendering policy."""

from typing import Any, Callable

from easyagent.hooks import BaseHook


class RuntimeObservationHook(BaseHook):
    def __init__(self) -> None:
        self._emit: Callable[[dict[str, Any]], None] | None = None
        self._pending = False

    def bind(self, emitter: Callable[[dict[str, Any]], None] | None) -> None:
        self._emit = emitter
        self._pending = False

    def before_compaction(self, payload: dict[str, Any]):
        if self._emit is not None:
            self._pending = True
            self._emit(
                {
                    "type": "compaction_start",
                    "data": {
                        "operation": payload.get("operation"),
                        "max_tokens": payload.get("max_tokens"),
                        "tokens_before": payload.get(
                            "tokens_before", payload.get("estimated_tokens")
                        ),
                        "force": bool(payload.get("force")),
                    },
                }
            )

    def flush(self, usage: dict[str, Any] | Callable[[], dict[str, Any]]) -> None:
        if not self._pending or self._emit is None:
            return
        if callable(usage):
            usage = usage()
        compaction = dict(
            usage.get("last_history_compaction") or usage.get("compaction") or {}
        )
        if "max_tokens" not in compaction and "budget" in compaction:
            compaction["max_tokens"] = compaction["budget"]
        self._emit({"type": "compaction_result", "data": compaction})
        self._pending = False
