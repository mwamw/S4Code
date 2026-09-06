"""Terminal wording for structured Core compaction events."""

from typing import Any


class CompactionPresenter:
    @staticmethod
    def present(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        if event_type == "compaction_start":
            before, budget = data.get("tokens_before"), data.get("max_tokens")
            return {
                "type": event_type,
                **data,
                "content": f"Compacting history (tokens={before}, budget={budget}).",
            }
        return {
            "type": event_type,
            "compaction": data,
            "content": CompactionPresenter._format_compaction_message(data),
        }

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
