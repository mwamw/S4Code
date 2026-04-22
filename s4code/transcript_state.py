"""Semantic transcript state for the S4Code TUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(slots=True)
class TranscriptCard:
    card_id: str
    kind: str
    title: str
    body: str
    status: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _RoundState:
    number: int
    thinking_card_id: Optional[str] = None
    content_card_id: Optional[str] = None


class S4TranscriptState:
    def __init__(self) -> None:
        self.cards: list[TranscriptCard] = []
        self._next_card_id = 0
        self._current_round: Optional[_RoundState] = None
        self._tool_card_ids: dict[str, str] = {}

    def clear(self) -> None:
        self.cards.clear()
        self._tool_card_ids.clear()
        self._current_round = None

    def append_card(
        self,
        kind: str,
        title: str,
        body: str,
        *,
        status: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> TranscriptCard:
        self._next_card_id += 1
        card = TranscriptCard(
            card_id=f"card-{self._next_card_id}",
            kind=kind,
            title=title,
            body=body,
            status=status,
            metadata=dict(metadata or {}),
        )
        self.cards.append(card)
        return card

    def find_card(self, card_id: str) -> Optional[TranscriptCard]:
        for card in self.cards:
            if card.card_id == card_id:
                return card
        return None

    def _find_tool_card(self, tool_id: str) -> Optional[TranscriptCard]:
        card_id = self._tool_card_ids.get(tool_id)
        if card_id is None:
            return None
        return self.find_card(card_id)

    def _ensure_round(self) -> _RoundState:
        if self._current_round is None:
            self.start_round(1)
        assert self._current_round is not None
        return self._current_round

    def start_round(self, number: int) -> None:
        if number > 1:
            self.append_card("round", f"Cycle {number}", "", metadata={"round": number})
        self._current_round = _RoundState(number=number)

    def _ensure_thinking_card(self) -> TranscriptCard:
        round_state = self._ensure_round()
        if round_state.thinking_card_id is not None:
            card = self.find_card(round_state.thinking_card_id)
            if card is not None:
                return card
        card = self.append_card("thinking", "Model Thinking", "", status="streaming")
        round_state.thinking_card_id = card.card_id
        return card

    def _ensure_content_card(self) -> TranscriptCard:
        round_state = self._ensure_round()
        if round_state.content_card_id is not None:
            card = self.find_card(round_state.content_card_id)
            if card is not None:
                return card
        card = self.append_card("assistant", "Model Response", "", status="streaming")
        round_state.content_card_id = card.card_id
        return card

    def consume_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        if event_type == "round_start":
            self.start_round(int(event.get("round") or 1))
            return
        if event_type == "thinking_delta":
            delta = str(event.get("delta") or "")
            if not delta:
                return
            card = self._ensure_thinking_card()
            card.body += delta
            card.status = "streaming"
            return
        if event_type == "text_delta":
            delta = str(event.get("delta") or "")
            if not delta:
                return
            card = self._ensure_content_card()
            card.body += delta
            card.status = "streaming"
            return
        if event_type == "tool_call":
            tool_name = str(event.get("tool_name") or "Tool")
            tool_id = str(event.get("tool_id") or f"tool-{len(self._tool_card_ids) + 1}")
            card = self.append_card(
                "tool",
                f"Tool · {tool_name}",
                self._format_tool_call_body(event.get("tool_args")),
                status="running",
                metadata={"tool_id": tool_id, "tool_name": tool_name},
            )
            self._tool_card_ids[tool_id] = card.card_id
            return
        if event_type == "tool_result":
            tool_name = str(event.get("tool_name") or "Tool")
            tool_id = str(event.get("tool_id") or "")
            existing = self._find_tool_card(tool_id) if tool_id else None
            body = self._format_tool_result_body(event.get("content"))
            if existing is None:
                self.append_card("tool", f"Tool · {tool_name}", body, status="done")
            else:
                existing.body = body
                existing.status = "done"
            return
        if event_type == "final":
            content = str(event.get("content") or "").strip()
            if not content:
                return
            card = self._ensure_content_card()
            card.body = content
            card.status = None
            thinking_card = None
            if self._current_round and self._current_round.thinking_card_id:
                thinking_card = self.find_card(self._current_round.thinking_card_id)
            if thinking_card is not None:
                thinking_card.status = None
            return
        if event_type == "interruption":
            self.append_card(
                "warning",
                "Warning",
                str(event.get("content") or event.get("message") or "Interrupted"),
            )
            return
        if event_type == "error":
            self.append_card("error", "Error", str(event.get("error") or "Unknown error"))

    def _format_tool_call_body(self, tool_args: Any) -> str:
        if not isinstance(tool_args, dict):
            return self._summarize_scalar(tool_args, max_chars=180)

        priority_keys = (
            "file_path",
            "path",
            "notebook_path",
            "directory",
            "cwd",
            "workspace_root",
            "command",
            "agent_id",
            "team_id",
            "recipient_id",
            "server",
            "uri",
            "name",
            "action",
            "description",
        )
        lines: list[str] = []
        for key in priority_keys:
            value = tool_args.get(key)
            if value in (None, "", [], {}, ()):
                continue
            lines.append(f"{key}: {self._summarize_scalar(value, max_chars=140)}")
            if len(lines) >= 4:
                break
        if lines:
            hidden = max(len(tool_args) - len(lines), 0)
            if hidden:
                lines.append(f"... {hidden} more field(s) hidden")
            return "\n".join(lines)
        return self._summarize_scalar(tool_args, max_chars=180)

    def _format_tool_result_body(self, content: Any) -> str:
        text = str(content or "").strip()
        if not text:
            return "Completed with no textual output."
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        first_line = lines[0] if lines else text
        summary = self._summarize_scalar(first_line, max_chars=180)
        hidden_lines = max(len(lines) - 1, 0)
        if hidden_lines > 0:
            return f"{summary}\n... {hidden_lines} more line(s) hidden"
        return summary

    def _summarize_scalar(self, value: Any, *, max_chars: int) -> str:
        text = str(value).replace("\n", " ").strip()
        text = " ".join(text.split())
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."
