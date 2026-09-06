"""CheckpointManager: terminal interaction responsibilities."""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Optional


class CheckpointManager:
    def __init__(self, controller):
        self.controller = controller
        self._checkpoints = []

    @property
    def count(self) -> int:
        return len(self._checkpoints)

    def _json_safe_copy(self, value: Any) -> Any:
        return copy.deepcopy(value)

    def _checkpoint_store(self) -> dict[str, Any]:
        return self.controller.core.read_extension("terminal")

    def _restore_checkpoints_from_overrides(self) -> None:
        store = self._checkpoint_store()
        legacy = self.controller.session_overrides.pop("_s4code", {})
        raw = store.get("checkpoints", legacy.get("checkpoints", []))
        self._checkpoints = [
            copy.deepcopy(item)
            for item in raw
            if isinstance(item, dict)
            and item.get("checkpoint_id")
            and (
                isinstance(item.get("history"), list)
                or isinstance(item.get("snapshot"), dict)
            )
        ][-30:]
        if legacy:
            self._persist_checkpoints_to_overrides()

    def _persist_checkpoints_to_overrides(self) -> None:
        store = self._checkpoint_store()
        store["checkpoints"] = self._json_safe_copy(self._checkpoints[-30:])
        self.controller.core.write_extension("terminal", store)

    def _public_checkpoint_payload(self, checkpoint: dict[str, Any]) -> dict[str, Any]:
        payload = dict(checkpoint)
        payload.pop("history", None)
        payload.pop("state", None)
        payload.pop("snapshot", None)
        return payload

    def create_checkpoint(
        self, label: Optional[str] = None, *, reason: str = "manual"
    ) -> dict[str, Any]:
        snapshot = self.controller.core.export_conversation()
        history = self.controller.core.inspector.read("history")
        checkpoint_number = (
            max(
                (
                    int(item["checkpoint_id"][3:])
                    for item in self._checkpoints
                    if item["checkpoint_id"].startswith("cp-")
                    and item["checkpoint_id"][3:].isdigit()
                ),
                default=0,
            )
            + 1
        )
        checkpoint = {
            "checkpoint_id": f"cp-{checkpoint_number:03d}",
            "label": str(label or "").strip() or f"checkpoint {checkpoint_number}",
            "reason": str(reason or "manual"),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "session_id": self.controller.session_id,
            "title": self.controller.title,
            "snapshot": snapshot.model_dump(mode="json"),
            "history_messages": len(history),
        }
        try:
            checkpoint["context"] = self.controller.core.inspector.read("context")
        except Exception:
            checkpoint["context"] = {}
        self._checkpoints.append(self._json_safe_copy(checkpoint))
        self._checkpoints = self._checkpoints[-30:]
        self._persist_checkpoints_to_overrides()
        self.controller._mark_session_dirty()
        self.controller.ensure_autosave()
        return self._public_checkpoint_payload(checkpoint)

    def get_checkpoint_choices(self) -> list[dict[str, Any]]:
        return [self._public_checkpoint_payload(item) for item in self._checkpoints]

    def get_transcript_history_cards(self, *, limit: int = 200) -> list[dict[str, Any]]:
        history = self.controller.core.inspector.read("history")
        if limit > 0:
            history = history[-limit:]
        cards: list[dict[str, Any]] = []
        for message in history:
            item = self._history_message_to_transcript_card(message)
            if item is not None:
                cards.append(item)
        return cards

    def _history_message_to_transcript_card(
        self, message: Any
    ) -> Optional[dict[str, Any]]:
        role, text = self._history_message_role_and_text(message)
        text = str(text or "").strip()
        if not text:
            return None
        if role == "user":
            return {"kind": "user", "title": "You", "body": text}
        if role == "assistant":
            return {"kind": "assistant", "title": "Model Response", "body": text}
        if role == "tool":
            return {
                "kind": "tool",
                "title": "Tool History",
                "body": text,
                "status": "done",
            }
        if role == "system":
            return {"kind": "system", "title": "System", "body": text}
        return {
            "kind": "system",
            "title": f"History · {role or 'message'}",
            "body": text,
        }

    def _history_message_role_and_text(self, message: Any) -> tuple[str, str]:
        if isinstance(message, dict):
            role = str(message.get("role") or message.get("type") or "assistant")
            content = message.get("text", message.get("content"))
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict):
                        text = (
                            item.get("text")
                            or item.get("thinking")
                            or item.get("content")
                        )
                        if text:
                            parts.append(str(text))
                    elif item is not None:
                        parts.append(str(item))
                return role, "\n".join(parts)
            return role, str(content or "")
        role = str(getattr(message, "role", "assistant"))
        content = getattr(message, "content", "")
        return role, str(content or "")

    def _resolve_checkpoint(self, target: Optional[str] = None) -> dict[str, Any]:
        if not self._checkpoints:
            raise ValueError("No checkpoints available.")
        normalized = str(target or "last").strip()
        if not normalized or normalized == "last":
            return self._checkpoints[-1]
        if normalized.isdigit():
            index = int(normalized)
            if index <= 0:
                raise ValueError(f"Invalid checkpoint index: {normalized}")
            if index <= len(self._checkpoints):
                return self._checkpoints[index - 1]
        for checkpoint in reversed(self._checkpoints):
            if (
                checkpoint.get("checkpoint_id") == normalized
                or checkpoint.get("label") == normalized
            ):
                return checkpoint
        raise ValueError(f"Checkpoint not found: {normalized}")

    def rewind_to_checkpoint(self, target: Optional[str] = None) -> str:
        checkpoint = self._resolve_checkpoint(target)
        snapshot = checkpoint.get("snapshot") or {
            "version": 1,
            "session_id": self.controller.session_id,
            "state": checkpoint.get("state")
            or {"history": {"canonical": checkpoint["history"]}},
        }
        self.controller.core.restore_conversation(copy.deepcopy(snapshot))
        return f"Rewound to {checkpoint['checkpoint_id']} | {checkpoint['label']}"

    def format_checkpoints(self) -> str:
        if not self._checkpoints:
            return "No checkpoints yet."
        lines = []
        for index, checkpoint in enumerate(self._checkpoints, start=1):
            lines.append(
                f"{index}. {checkpoint.get('checkpoint_id')} | {checkpoint.get('label') or '-'} | "
                f"{checkpoint.get('reason') or '-'} | messages={checkpoint.get('history_messages', 0)} | "
                f"{checkpoint.get('created_at') or '-'}"
            )
        lines.append("")
        lines.append("Usage: /rewind <checkpoint_id|index|last>")
        return "\n".join(lines)

    def format_timeline(self) -> str:
        lines = [
            f"Session: {self.controller.session_id}",
            f"Title: {self.controller.title}",
            f"Forked from: {self.controller.forked_from_session_id or '-'}",
            "",
            "Checkpoints:",
        ]
        if self._checkpoints:
            for checkpoint in self._checkpoints[-12:]:
                lines.append(
                    f"- {checkpoint.get('checkpoint_id')} | {checkpoint.get('created_at') or '-'} | "
                    f"{checkpoint.get('label') or '-'} | messages={checkpoint.get('history_messages', 0)}"
                )
        else:
            lines.append("- none")
        trace = self.controller.usage._trace_summaries(limit=5)
        if trace:
            lines.extend(["", "Recent Turns:"])
            for item in trace:
                label = str(
                    item.get("query")
                    or item.get("turnId")
                    or item.get("turn_id")
                    or "-"
                )
                status = str(item.get("status") or item.get("success") or "-")
                duration = item.get("durationMs") or item.get("duration_ms")
                suffix = f" | {duration}ms" if duration is not None else ""
                lines.append(f"- {label[:96]} | {status}{suffix}")
        return "\n".join(lines)
