"""Semantic transcript state for the S4Code TUI."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(slots=True)
class TranscriptCard:
    card_id: str
    kind: str
    title: str
    body: str
    status: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    revision: int = 0


@dataclass(slots=True)
class _RoundState:
    number: int
    round_card_id: str
    started_at: float
    tool_started_at: dict[str, float] = field(default_factory=dict)
    thinking_card_id: Optional[str] = None
    content_card_id: Optional[str] = None


class S4TranscriptState:
    def __init__(self, *, clock: Optional[Callable[[], float]] = None) -> None:
        self.cards: list[TranscriptCard] = []
        self._card_index: dict[str, TranscriptCard] = {}
        self._round_card_ids: dict[int, str] = {}
        self._dirty_card_ids: set[str] = set()
        self._next_card_id = 0
        self._current_round: Optional[_RoundState] = None
        self._tool_card_ids: dict[str, str] = {}
        self._compaction_card_id: Optional[str] = None
        self._runtime_card_id: Optional[str] = None
        self._pending_checkpoints: list[dict[str, Any]] = []
        self._clock = clock or time.monotonic

    def _touch(self, card: Optional[TranscriptCard]) -> None:
        if card is not None:
            card.revision += 1
            self._dirty_card_ids.add(card.card_id)

    def clear(self) -> None:
        self.cards.clear()
        self._card_index.clear()
        self._round_card_ids.clear()
        self._dirty_card_ids.clear()
        self._tool_card_ids.clear()
        self._current_round = None
        self._compaction_card_id = None
        self._runtime_card_id = None
        self._pending_checkpoints.clear()

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
        self._card_index[card.card_id] = card
        round_number = metadata.get("round") if isinstance(metadata, dict) else None
        if kind == "round" and isinstance(round_number, int):
            self._round_card_ids[round_number] = card.card_id
        self._dirty_card_ids.add(card.card_id)
        self._attach_pending_checkpoints(card)
        return card

    def find_card(self, card_id: str) -> Optional[TranscriptCard]:
        return self._card_index.get(card_id)

    def _remove_card(self, card_id: str) -> None:
        card = self._card_index.pop(card_id, None)
        if card is None:
            return
        self.cards = [item for item in self.cards if item.card_id != card_id]
        self._dirty_card_ids.discard(card_id)
        if card.kind == "round":
            round_number = card.metadata.get("round")
            if isinstance(round_number, int):
                self._round_card_ids.pop(round_number, None)
        stale_tool_ids = [tool_id for tool_id, value in self._tool_card_ids.items() if value == card_id]
        for tool_id in stale_tool_ids:
            self._tool_card_ids.pop(tool_id, None)

    def consume_dirty_card_ids(self) -> set[str]:
        dirty = set(self._dirty_card_ids)
        self._dirty_card_ids.clear()
        return dirty

    def mark_all_cards_dirty(self) -> None:
        self._dirty_card_ids.update(card.card_id for card in self.cards)

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

    @staticmethod
    def _new_round_metrics() -> dict[str, Any]:
        return {
            "tool_calls": 0,
            "running_tools": 0,
            "tool_errors": 0,
            "tool_pending": 0,
            "local_tool_seconds": 0.0,
            "llm_duration_ms": 0.0,
            "tool_duration_ms": 0.0,
            "llm_requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": None,
            "context_used_tokens": None,
            "context_max_tokens": None,
            "context_remaining_tokens": None,
            "context_usage_ratio": None,
            "context_usage_percent": None,
            "prompt_tokens_total": 0,
            "prompt_tokens_cached": 0,
            "prompt_tokens_uncached": 0,
            "cache_hit_tokens": 0,
            "cache_hit_ratio": None,
            "files_changed": [],
            "tools_used": [],
        }

    def _find_round_card_by_number(self, number: int) -> Optional[TranscriptCard]:
        card_id = self._round_card_ids.get(int(number))
        if card_id is None:
            return None
        return self.find_card(card_id)

    def _round_metrics_for_card(self, card: TranscriptCard) -> dict[str, Any]:
        metrics = card.metadata.get("metrics")
        if isinstance(metrics, dict):
            return metrics
        metrics = self._new_round_metrics()
        card.metadata["metrics"] = metrics
        return metrics

    def _current_round_card(self) -> Optional[TranscriptCard]:
        if self._current_round is None:
            return None
        return self.find_card(self._current_round.round_card_id)

    def _refresh_live_round_body(self) -> None:
        round_state = self._current_round
        if round_state is None:
            return
        card = self.find_card(round_state.round_card_id)
        if card is None:
            return
        body = self._format_active_round_body(
            round_state.started_at,
            now=self._clock(),
            metrics=self._round_metrics_for_card(card),
        )
        if body != card.body:
            card.body = body
            self._touch(card)

    def start_round(self, number: int) -> None:
        self._finalize_current_round()
        started_at = self._clock()
        card = self.append_card(
            "round",
            f"Cycle {number}",
            self._format_active_round_body(
                started_at,
                now=started_at,
                metrics=self._new_round_metrics(),
            ),
            metadata={
                "round": number,
                "started_at": started_at,
                "metrics": self._new_round_metrics(),
                "outcome": "running",
            },
        )
        self._current_round = _RoundState(
            number=number,
            round_card_id=card.card_id,
            started_at=started_at,
        )

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
        round_card = self.find_card(round_state.round_card_id)
        metrics = self._round_metrics_for_card(round_card) if round_card is not None else self._new_round_metrics()
        card = self.append_card(
            "assistant",
            "Model Response",
            "",
            status="streaming",
            metadata={"round": round_state.number},
        )
        footer = self._format_message_metrics_footer(metrics)
        if footer:
            card.metadata["footer_left"] = footer
        round_state.content_card_id = card.card_id
        return card

    def _find_round_message_card(self, round_number: int) -> Optional[TranscriptCard]:
        target = int(round_number or 0)
        if target <= 0:
            return None
        for card in reversed(self.cards):
            if card.kind != "assistant":
                continue
            if int(card.metadata.get("round") or 0) == target:
                return card
        return None

    def _sync_round_message_footer(self, round_number: int, metrics: dict[str, Any]) -> None:
        card = self._find_round_message_card(round_number)
        if card is None:
            return
        footer = self._format_message_metrics_footer(metrics)
        current = str(card.metadata.get("footer_left") or "")
        if footer:
            if footer != current:
                card.metadata["footer_left"] = footer
                self._touch(card)
        elif "footer_left" in card.metadata:
            card.metadata.pop("footer_left", None)
            self._touch(card)

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
            self._touch(card)
            return
        if event_type == "text_delta":
            delta = str(event.get("delta") or "")
            if not delta:
                return
            card = self._ensure_content_card()
            card.body += delta
            card.status = "streaming"
            self._touch(card)
            return
        if event_type == "tool_call":
            round_state = self._ensure_round()
            tool_name = str(event.get("tool_name") or "Tool")
            tool_id = str(event.get("tool_id") or f"tool-{len(self._tool_card_ids) + 1}")
            round_state.tool_started_at[tool_id] = self._clock()
            round_card = self.find_card(round_state.round_card_id)
            if round_card is not None:
                metrics = self._round_metrics_for_card(round_card)
                metrics["tool_calls"] = int(metrics.get("tool_calls") or 0) + 1
                metrics["running_tools"] = int(metrics.get("running_tools") or 0) + 1
                tools_used = {str(item) for item in list(metrics.get("tools_used") or []) if item}
                tools_used.add(tool_name)
                metrics["tools_used"] = sorted(tools_used)
                self._refresh_live_round_body()
            card = self.append_card(
                "tool",
                f"Tool · {tool_name}",
                self._format_tool_call_body(event.get("tool_args")),
                status="running",
                metadata={
                    "tool_id": tool_id,
                    "tool_name": tool_name,
                    "tool_args": dict(event.get("tool_args") or {}) if isinstance(event.get("tool_args"), dict) else {},
                    "round": round_state.number,
                },
            )
            self._tool_card_ids[tool_id] = card.card_id
            return
        if event_type == "tool_result":
            tool_name = str(event.get("tool_name") or "Tool")
            tool_id = str(event.get("tool_id") or "")
            existing = self._find_tool_card(tool_id) if tool_id else None
            body = self._format_tool_result_body(event)
            metadata = {
                "tool_id": tool_id,
                "tool_name": tool_name,
                **self._extract_tool_result_metadata(event),
            }
            status = self._resolve_tool_card_status(event)
            if existing is None:
                self.append_card("tool", f"Tool · {tool_name}", body, status=status, metadata=metadata)
            else:
                existing.body = body
                existing.status = status
                existing.metadata.update(metadata)
                self._touch(existing)
            round_state = self._current_round
            if round_state is not None:
                round_card = self.find_card(round_state.round_card_id)
                if round_card is not None:
                    metrics = self._round_metrics_for_card(round_card)
                    started_at = round_state.tool_started_at.pop(tool_id, self._clock())
                    duration = max(self._clock() - started_at, 0.0)
                    metrics["running_tools"] = max(int(metrics.get("running_tools") or 0) - 1, 0)
                    metrics["local_tool_seconds"] = float(metrics.get("local_tool_seconds") or 0.0) + duration
                    if status == "error":
                        metrics["tool_errors"] = int(metrics.get("tool_errors") or 0) + 1
                    elif status == "pending":
                        metrics["tool_pending"] = int(metrics.get("tool_pending") or 0) + 1
                    diff_payload = metadata.get("diff")
                    if isinstance(diff_payload, dict):
                        changed = {
                            str(item)
                            for item in list(metrics.get("files_changed") or [])
                            if str(item).strip()
                        }
                        label = str(diff_payload.get("relative_path") or diff_payload.get("file_path") or "").strip()
                        if label:
                            changed.add(label)
                        metrics["files_changed"] = sorted(changed)
                    self._refresh_live_round_body()
            return
        if event_type == "round_metrics":
            round_number = int(event.get("round") or 0)
            if round_number <= 0:
                return
            card = self._find_round_card_by_number(round_number)
            if card is None:
                return
            metrics = self._round_metrics_for_card(card)
            payload = dict(event.get("metrics") or {})
            for key, value in payload.items():
                if key in {"files_changed", "tools_used"}:
                    existing = {str(item) for item in list(metrics.get(key) or []) if str(item).strip()}
                    incoming = {str(item) for item in list(value or []) if str(item).strip()}
                    metrics[key] = sorted(existing | incoming)
                elif value is not None:
                    metrics[key] = value
            self._sync_round_message_footer(round_number, metrics)
            if self._current_round is not None and self._current_round.number == round_number:
                self._refresh_live_round_body()
            else:
                started_at = float(card.metadata.get("started_at") or 0.0)
                finished_at = float(card.metadata.get("finished_at") or started_at)
                outcome = str(card.metadata.get("outcome") or "completed")
                body = self._format_completed_round_body(
                    started_at,
                    finished_at,
                    metrics=metrics,
                    outcome=outcome,
                )
                if body != card.body:
                    card.body = body
                    self._touch(card)
            return
        if event_type == "runtime_snapshot":
            body = self._format_runtime_snapshot(event.get("snapshot"))
            existing = self.find_card(self._runtime_card_id) if self._runtime_card_id else None
            if existing is None:
                card = self.append_card(
                    "runtime",
                    "Runtime Snapshot",
                    body,
                    status="live" if self._current_round is not None else None,
                )
                self._runtime_card_id = card.card_id
            else:
                existing.body = body
                existing.status = "live" if self._current_round is not None else None
                self._touch(existing)
            return
        if event_type == "checkpoint":
            checkpoint = dict(event.get("checkpoint") or {})
            annotation = self._checkpoint_annotation(checkpoint)
            target = self._find_checkpoint_target(annotation)
            if target is None:
                self._pending_checkpoints.append(annotation)
            else:
                self._add_checkpoint_to_card(target, annotation)
            return
        if event_type == "compaction_start":
            card = self.append_card(
                "warning",
                "Context Compaction",
                str(event.get("content") or "Compacting history..."),
                status="running",
            )
            self._compaction_card_id = card.card_id
            return
        if event_type == "compaction_result":
            compaction = dict(event.get("compaction") or {})
            existing = self.find_card(self._compaction_card_id) if self._compaction_card_id else None
            if not bool(compaction.get("was_compacted", False)):
                if existing is not None:
                    self._remove_card(existing.card_id)
                self._compaction_card_id = None
                return
            body = str(event.get("content") or "History compaction finished.")
            if existing is None:
                self.append_card("warning", "Context Compaction", body, status="done")
            else:
                existing.body = body
                existing.status = "done"
                self._touch(existing)
            self._compaction_card_id = None
            return
        if event_type == "final":
            content = str(event.get("content") or "").strip()
            if not content:
                return
            round_card = self._current_round_card()
            round_number = None
            metrics: dict[str, Any] = {}
            if round_card is not None:
                round_number = round_card.metadata.get("round")
                metrics = dict(self._round_metrics_for_card(round_card))
            card = self._ensure_content_card()
            card.body = content
            card.status = None
            self._touch(card)
            thinking_card = None
            if self._current_round and self._current_round.thinking_card_id:
                thinking_card = self.find_card(self._current_round.thinking_card_id)
            if thinking_card is not None:
                thinking_card.status = None
                self._touch(thinking_card)
            self._finalize_current_round(outcome="completed")
            if round_number is not None:
                self._append_final_summary_cards(round_number=int(round_number), metrics=metrics, content=content)
            return
        if event_type == "interruption":
            self._finalize_current_round(outcome="pending")
            payload = dict(event.get("payload") or {})
            metadata = dict(payload.get("metadata") or {})
            interaction_type = str(metadata.get("interaction_type") or "")
            title = "Pending Confirmation"
            if interaction_type == "ask_user_question":
                title = "Ask User Question"
            elif interaction_type == "enter_plan_mode":
                title = "Enter Plan Mode Request"
            elif interaction_type == "exit_plan_mode":
                title = "Exit Plan Mode Request"
            body = self._format_interruption_body(event, payload, metadata)
            self.append_card(
                "warning",
                title,
                body,
                status="pending",
            )
            return
        if event_type == "interaction_resolved":
            self.append_card(
                "system",
                "Interaction Resolved",
                str(event.get("content") or "Resolved."),
            )
            return
        if event_type == "system_notice":
            self.append_card(
                "system",
                str(event.get("title") or "System"),
                str(event.get("content") or ""),
            )
            return
        if event_type == "error":
            self._finalize_current_round(outcome="error")
            self.append_card("error", "Error", str(event.get("error") or "Unknown error"))
            return
        if event_type == "cancelled":
            self._finalize_current_round(outcome="interrupted")
            self.append_card(
                "warning",
                "Interrupted",
                str(event.get("content") or "Agent execution interrupted."),
            )

    def has_live_round(self) -> bool:
        return self._current_round is not None

    @staticmethod
    def _checkpoint_annotation(checkpoint: dict[str, Any]) -> dict[str, Any]:
        return {
            "checkpoint_id": str(checkpoint.get("checkpoint_id") or "").strip(),
            "label": str(checkpoint.get("label") or "").strip(),
            "reason": str(checkpoint.get("reason") or "").strip(),
            "history_messages": checkpoint.get("history_messages", 0),
            "created_at": str(checkpoint.get("created_at") or "").strip(),
        }

    @staticmethod
    def _can_annotate_checkpoint(card: TranscriptCard) -> bool:
        return card.kind not in {"separator", "round", "runtime"}

    def _attach_pending_checkpoints(self, card: TranscriptCard) -> None:
        if not self._pending_checkpoints or not self._can_annotate_checkpoint(card):
            return
        pending = list(self._pending_checkpoints)
        self._pending_checkpoints.clear()
        for checkpoint in pending:
            self._add_checkpoint_to_card(card, checkpoint)

    def _add_checkpoint_to_card(self, card: TranscriptCard, checkpoint: dict[str, Any]) -> None:
        if not self._can_annotate_checkpoint(card):
            self._pending_checkpoints.append(checkpoint)
            return
        checkpoints = card.metadata.setdefault("checkpoints", [])
        if not isinstance(checkpoints, list):
            checkpoints = []
            card.metadata["checkpoints"] = checkpoints
        checkpoint_id = str(checkpoint.get("checkpoint_id") or "")
        if checkpoint_id and any(
            isinstance(item, dict) and item.get("checkpoint_id") == checkpoint_id
            for item in checkpoints
        ):
            return
        checkpoints.append(dict(checkpoint))
        self._touch(card)

    def _find_checkpoint_target(self, checkpoint: dict[str, Any]) -> Optional[TranscriptCard]:
        reason = str(checkpoint.get("reason") or "")
        preferred_kinds: tuple[str, ...]
        if reason == "before_prompt":
            preferred_kinds = ("user",)
        elif reason == "interruption":
            preferred_kinds = ("warning", "assistant", "user")
        elif reason == "after_prompt":
            preferred_kinds = ("assistant", "warning", "error", "user")
        else:
            preferred_kinds = ("assistant", "warning", "system", "user", "error", "tool")
        for card in reversed(self.cards):
            if card.kind in preferred_kinds and self._can_annotate_checkpoint(card):
                return card
        for card in reversed(self.cards):
            if self._can_annotate_checkpoint(card):
                return card
        return None

    def refresh_round_timers(self) -> bool:
        round_state = self._current_round
        if round_state is None:
            return False
        card = self.find_card(round_state.round_card_id)
        if card is None:
            return False
        body = self._format_active_round_body(
            round_state.started_at,
            now=self._clock(),
            metrics=self._round_metrics_for_card(card),
        )
        if body == card.body:
            return False
        card.body = body
        self._touch(card)
        return True

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

    def _format_tool_result_body(self, event: dict[str, Any]) -> str:
        structured_data = event.get("structured_data")
        if isinstance(structured_data, dict):
            task_id = str(structured_data.get("task_id") or "").strip()
            status = str(structured_data.get("status") or "").strip().lower()
            if task_id and status in {"running", "queued", "waiting"}:
                lines = [f"Started background task `{task_id}`."]
                description = str(structured_data.get("description") or "").strip()
                command = str(structured_data.get("command") or "").replace("\n", " ").strip()
                if description:
                    lines.append(f"Purpose: {self._summarize_scalar(description, max_chars=140)}")
                elif command:
                    lines.append(f"Command: {self._summarize_scalar(command, max_chars=140)}")
                lines.append(f"Use `/task output {task_id}` to stream logs.")
                lines.append(f"Use `/task stop {task_id}` to stop it.")
                return "\n".join(lines)

        content = event.get("content")
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

    def _extract_tool_result_metadata(self, event: dict[str, Any]) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        structured_data = event.get("structured_data")
        diff_payload = self._extract_tool_diff(structured_data)
        if diff_payload is not None:
            metadata["diff"] = diff_payload
        result_metadata = event.get("result_metadata")
        if isinstance(result_metadata, dict) and result_metadata:
            metadata["result_metadata"] = dict(result_metadata)
        if isinstance(structured_data, dict):
            task_id = str(structured_data.get("task_id") or "").strip()
            if task_id:
                metadata["background_task"] = {
                    "task_id": task_id,
                    "status": str(structured_data.get("status") or "").strip(),
                    "command": str(structured_data.get("command") or "").strip(),
                }
        error_type = str(event.get("error_type") or "").strip()
        if error_type:
            metadata["error_type"] = error_type
        result_status = str(event.get("status") or "").strip()
        if result_status:
            metadata["result_status"] = result_status
        return metadata

    def _extract_tool_diff(self, structured_data: Any) -> Optional[dict[str, Any]]:
        if not isinstance(structured_data, dict):
            return None
        diff_payload = structured_data.get("diff")
        if not isinstance(diff_payload, dict):
            return None
        unified = str(diff_payload.get("unified") or "").strip()
        if not unified:
            return None
        return {
            "unified": unified,
            "file_path": str(diff_payload.get("file_path") or structured_data.get("file_path") or "").strip(),
            "relative_path": str(diff_payload.get("relative_path") or "").strip(),
            "created": bool(diff_payload.get("created")),
            "source": str(diff_payload.get("source") or "").strip(),
        }

    def _format_runtime_snapshot(self, snapshot: Any) -> str:
        if not isinstance(snapshot, dict):
            return "Runtime snapshot unavailable."
        session = dict(snapshot.get("session") or {})
        worktree = dict(snapshot.get("worktree") or {})
        active_worktree = worktree.get("active") or {}
        agents = list(snapshot.get("agents") or [])
        tasks = list(snapshot.get("tasks") or [])
        background_tasks = list(snapshot.get("background_tasks") or [])
        context = dict(snapshot.get("context") or {})
        lines = [
            f"Updated: {snapshot.get('generated_at') or '-'}",
            f"Session: {session.get('session_id') or '-'} | checkpoints={session.get('checkpoints', 0)}",
            "",
            "Worktree:",
        ]
        if active_worktree:
            lines.append(f"- {active_worktree.get('branch') or '-'} @ {active_worktree.get('path') or '-'}")
        else:
            lines.append("- none")
        lines.extend(["", "Agents:"])
        if agents:
            for item in agents[:6]:
                lines.append(
                    f"- {item.get('agent_id') or '-'} | {item.get('status') or '-'} | "
                    f"{item.get('name') or '-'}"
                )
        else:
            lines.append("- none")
        lines.extend(["", "Tasks:"])
        if tasks or background_tasks:
            for item in tasks[:6]:
                lines.append(f"- {item.get('task_id') or '-'} | {item.get('status') or '-'} | {item.get('title') or '-'}")
            for item in background_tasks[:6]:
                command = str(item.get("command") or "").replace("\n", " ").strip()
                if len(command) > 100:
                    command = command[:97].rstrip() + "..."
                duration = item.get("duration_seconds")
                duration_text = f" | {float(duration):.1f}s" if isinstance(duration, (int, float)) else ""
                lines.append(
                    f"- {item.get('task_id') or '-'} | {item.get('status') or '-'} | "
                    f"rc={item.get('return_code')}{duration_text} | {command or item.get('cwd') or '-'}"
                )
                stdout_tail = str(item.get("stdout_tail") or "").strip()
                stderr_tail = str(item.get("stderr_tail") or "").strip()
                if stdout_tail:
                    lines.append(f"  stdout: {self._summarize_scalar(stdout_tail, max_chars=160)}")
                if stderr_tail:
                    lines.append(f"  stderr: {self._summarize_scalar(stderr_tail, max_chars=160)}")
        else:
            lines.append("- none")
        if context:
            lines.extend(
                [
                    "",
                    "Context: "
                    + self._context_summary_text(
                        used_tokens=context.get("used_tokens"),
                        max_tokens=context.get("max_tokens"),
                        remaining_tokens=context.get("remaining_tokens"),
                        ratio=None,
                    ),
                ]
            )
        return "\n".join(lines)

    def _resolve_tool_card_status(self, event: dict[str, Any]) -> str:
        status = str(event.get("status") or "").strip()
        if status == "error":
            return "error"
        if status == "needs_confirmation":
            return "pending"
        return "done"

    def _format_interruption_body(
        self,
        event: dict[str, Any],
        payload: dict[str, Any],
        metadata: dict[str, Any],
    ) -> str:
        interaction_type = str(metadata.get("interaction_type") or "")
        if interaction_type == "ask_user_question":
            lines = [
                "The agent needs your answer before it can continue.",
                "",
            ]
            questions = list(metadata.get("questions") or [])
            if questions:
                lines.append("Questions:")
                for index, item in enumerate(questions, start=1):
                    header = str(item.get("header") or f"Question {index}").strip()
                    question = str(item.get("question") or "").strip()
                    lines.append(f"{index}. {header}")
                    if question:
                        lines.append(f"   {question}")
                    options = list(item.get("options") or [])
                    for option in options:
                        label = str(option.get("label") or "").strip()
                        description = str(option.get("description") or "").strip()
                        option_text = f"   - {label}" if label else "   - option"
                        if description:
                            option_text += f": {description}"
                        lines.append(option_text)
                lines.append("")
            source = str(metadata.get("source") or "").strip()
            if source:
                lines.append(f"Source: {source}")
            lines.append("Next step:")
            lines.append("- Use `/answer <text>` to continue.")
            lines.append("- Use `/deny [reason]` to decline.")
            return "\n".join(lines).strip()
        if interaction_type == "enter_plan_mode":
            lines = ["The agent wants to switch into planning mode before making changes."]
            reason = str(metadata.get("reason") or "").strip()
            if reason:
                lines.append(f"Why this helps: {reason}")
            allowed_actions = list(metadata.get("allowedActions") or [])
            if allowed_actions:
                lines.append("What it wants to do:")
                lines.extend(f"- {self._summarize_scalar(item, max_chars=120)}" for item in allowed_actions)
            lines.append("Next step:")
            lines.append("- Use `/confirm` to enter plan mode.")
            lines.append("- Use `/deny [reason]` to refuse.")
            return "\n".join(lines)
        if interaction_type == "exit_plan_mode":
            lines = ["The agent is ready to leave planning mode and continue execution."]
            allowed_prompts = list(metadata.get("allowedPrompts") or [])
            if allowed_prompts:
                lines.append("Requested permission categories:")
                for item in allowed_prompts:
                    tool = str(item.get("tool") or "tool").strip()
                    prompt = str(item.get("prompt") or "").strip()
                    if prompt:
                        lines.append(f"- {tool}: {prompt}")
                    else:
                        lines.append(f"- {tool}")
            lines.append("Next step:")
            lines.append("- Use `/confirm` to leave plan mode.")
            lines.append("- Use `/deny [reason]` to stay in plan mode.")
            return "\n".join(lines)
        lines = ["The agent is waiting for your approval before it continues."]
        summary = str(event.get("content") or event.get("message") or "").strip()
        if summary:
            lines.extend(["", summary])
        tool_name = str(payload.get("tool_name") or event.get("tool_name") or "").strip()
        if tool_name:
            lines.append(f"Tool: {tool_name}")
        reason = str(metadata.get("reason") or "").strip()
        if reason:
            lines.append(f"Why this needs approval: {reason}")
        risk_line = self._pending_risk_summary(tool_name, payload.get("tool_args") or {})
        if risk_line:
            lines.append(risk_line)
        tool_args = payload.get("tool_args") or event.get("tool_args") or {}
        if isinstance(tool_args, dict) and tool_args:
            lines.append("Requested arguments:")
            lines.append(self._format_tool_call_body(tool_args))
        lines.append("Next step:")
        lines.append("- Use `/confirm [note]` to continue.")
        lines.append("- Use `/confirm remember` to allow a matching action for this session.")
        lines.append("- Use `/deny [reason]` to cancel.")
        return "\n".join(line for line in lines if line).strip()

    @staticmethod
    def _pending_risk_summary(tool_name: str, tool_args: Any) -> str:
        if not isinstance(tool_args, dict):
            tool_args = {}
        command = str(tool_args.get("command") or "").strip().lower()
        if tool_name == "Bash" and "git push" in command:
            return "Risk: high | reversible=False | shared_state=True | overwrites_local_changes=False"
        if tool_name == "ExitWorktree" and bool(tool_args.get("discard_changes")):
            return "Risk: high | reversible=False | shared_state=False | overwrites_local_changes=True"
        if tool_name in {"TaskStop", "AgentStop"} or "rewind" in command:
            return "Risk: medium | reversible=False | shared_state=False | overwrites_local_changes=False"
        if tool_name and ("edit" in tool_name.lower() or "write" in tool_name.lower()):
            return "Risk: medium | reversible=True | shared_state=False | overwrites_local_changes=False"
        if tool_name:
            return "Risk: low | reversible=True | shared_state=False | overwrites_local_changes=False"
        return ""

    @staticmethod
    def _format_duration(seconds: float) -> str:
        seconds = max(float(seconds), 0.0)
        if seconds < 60:
            return f"{seconds:.1f}s"
        minutes, remainder = divmod(seconds, 60.0)
        if minutes < 60:
            return f"{int(minutes)}m {remainder:04.1f}s"
        hours, minutes = divmod(int(minutes), 60)
        return f"{hours}h {minutes:02d}m {remainder:04.1f}s"

    def _format_round_metrics_line(self, metrics: dict[str, Any], *, outcome: str) -> str:
        items: list[str] = []
        tool_calls = int(metrics.get("tool_calls") or 0)
        running_tools = int(metrics.get("running_tools") or 0)
        tool_errors = int(metrics.get("tool_errors") or 0)
        if tool_calls:
            label = f"Tools {tool_calls}"
            if outcome == "running" and running_tools:
                label += f" ({running_tools} running)"
            items.append(label)
        llm_duration_seconds = float(metrics.get("llm_duration_ms") or 0.0) / 1000.0
        if llm_duration_seconds > 0:
            items.append(f"Model {self._format_duration(llm_duration_seconds)}")
        tool_duration_seconds = max(
            float(metrics.get("tool_duration_ms") or 0.0) / 1000.0,
            float(metrics.get("local_tool_seconds") or 0.0),
        )
        if tool_duration_seconds > 0:
            items.append(f"Tool {self._format_duration(tool_duration_seconds)}")
        files_changed = list(metrics.get("files_changed") or [])
        if files_changed:
            items.append(f"Files {len(files_changed)}")
        if tool_errors > 0:
            items.append(f"Errors {tool_errors}")
        if outcome == "pending":
            items.append("Waiting")
        elif outcome == "error":
            items.append("Errored")
        elif outcome == "interrupted":
            items.append("Interrupted")
        return " | ".join(items)

    def _format_active_round_body(self, started_at: float, *, now: float, metrics: Optional[dict[str, Any]] = None) -> str:
        lines = [f"Elapsed: {self._format_duration(now - started_at)}"]
        metrics_payload = metrics or {}
        metrics_line = self._format_round_metrics_line(metrics_payload, outcome="running")
        if metrics_line:
            lines.append(metrics_line)
        lines.extend(self._format_round_details(metrics_payload))
        return "\n".join(lines)

    def _format_completed_round_body(
        self,
        started_at: float,
        finished_at: float,
        *,
        metrics: Optional[dict[str, Any]] = None,
        outcome: str = "completed",
    ) -> str:
        label = {
            "completed": "Completed in",
            "pending": "Paused after",
            "error": "Errored after",
            "interrupted": "Interrupted in",
        }.get(outcome, "Completed in")
        lines = [f"{label} {self._format_duration(finished_at - started_at)}"]
        metrics_payload = metrics or {}
        metrics_line = self._format_round_metrics_line(metrics_payload, outcome=outcome)
        if metrics_line:
            lines.append(metrics_line)
        lines.extend(self._format_round_details(metrics_payload))
        return "\n".join(lines)

    def _format_round_details(self, metrics: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        tools_used = [str(item).strip() for item in list(metrics.get("tools_used") or []) if str(item).strip()]
        if tools_used:
            lines.append("Used: " + ", ".join(tools_used[:6]))
        files_changed = [str(item).strip() for item in list(metrics.get("files_changed") or []) if str(item).strip()]
        if files_changed:
            lines.append("Changed: " + ", ".join(files_changed[:5]))
        return lines

    @staticmethod
    def _format_metric_int(value: Any) -> str:
        try:
            return f"{int(value):,}"
        except Exception:
            return "?"

    def _format_message_metrics_footer(self, metrics: dict[str, Any]) -> str:
        items: list[str] = []
        context_used = metrics.get("context_used_tokens")
        context_max = metrics.get("context_max_tokens")
        if context_used is not None or context_max is not None:
            items.append(
                "Ctx "
                f"{self._format_metric_int(context_used) if context_used is not None else '?'}"
                "/"
                f"{self._format_metric_int(context_max) if context_max is not None else '?'}"
            )

        input_tokens = int(metrics.get("input_tokens") or 0)
        output_tokens = int(metrics.get("output_tokens") or 0)
        total_tokens = int(metrics.get("total_tokens") or 0)
        if input_tokens > 0:
            items.append(f"In {self._format_metric_int(input_tokens)}")
        if output_tokens > 0:
            items.append(f"Out {self._format_metric_int(output_tokens)}")
        if total_tokens > 0:
            items.append(f"Total {self._format_metric_int(total_tokens)}")

        prompt_total = int(metrics.get("prompt_tokens_total") or 0)
        prompt_cached = int(metrics.get("prompt_tokens_cached") or 0)
        cached_input = int(metrics.get("cached_input_tokens") or 0)
        cache_tokens = max(prompt_cached, cached_input)
        if cache_tokens > 0:
            if prompt_total > 0:
                items.append(
                    f"Cache {self._format_metric_int(cache_tokens)}/{self._format_metric_int(prompt_total)}"
                )
            else:
                items.append(f"Cache {self._format_metric_int(cache_tokens)}")

        estimated_cost = metrics.get("estimated_cost_usd")
        if estimated_cost is not None:
            try:
                items.append(f"Cost ${float(estimated_cost):.4f}")
            except Exception:
                pass
        return "  ·  ".join(items)

    @staticmethod
    def _context_summary_text(
        *,
        used_tokens: Any,
        max_tokens: Any,
        remaining_tokens: Any,
        ratio: Any,
        percent_text: Optional[str] = None,
    ) -> str:
        if percent_text:
            percent = percent_text
        elif isinstance(ratio, (int, float)):
            percent = f"{float(ratio) * 100:.0f}%"
        else:
            percent = "-"
        return (
            f"{percent} "
            f"({used_tokens if used_tokens is not None else '?'} / {max_tokens if max_tokens is not None else '?'} used, "
            f"{remaining_tokens if remaining_tokens is not None else '?'} remaining)"
        )

    def _append_final_summary_cards(self, *, round_number: int, metrics: dict[str, Any], content: str) -> None:
        tools_used = [str(item).strip() for item in list(metrics.get("tools_used") or []) if str(item).strip()]
        files_changed = [str(item).strip() for item in list(metrics.get("files_changed") or []) if str(item).strip()]
        outcome_lines = [
            f"Round {round_number} finished.",
            f"Tools used: {', '.join(tools_used) if tools_used else 'none'}",
            f"Files changed: {', '.join(files_changed) if files_changed else 'none'}",
        ]
        self.append_card(
            "system",
            "Round Outcome",
            "\n".join(outcome_lines),
            metadata={"round": round_number, "outcome_summary": True},
        )
        if files_changed:
            self.append_card(
                "system",
                "Changed Files",
                "\n".join(f"- {item}" for item in files_changed),
                metadata={"round": round_number, "changed_files": files_changed},
            )
        verification = self._build_verification_summary(round_number)
        if verification:
            self.append_card(
                "system",
                "Verification",
                verification,
                metadata={"round": round_number, "verification": True},
            )

    def _build_verification_summary(self, round_number: int) -> str:
        commands: list[str] = []
        background_tasks: list[str] = []
        for card in self.cards:
            if card.kind != "tool":
                continue
            if int(card.metadata.get("round") or 0) != round_number:
                continue
            if str(card.metadata.get("tool_name") or "") != "Bash":
                continue
            tool_args = dict(card.metadata.get("tool_args") or {})
            command = str(tool_args.get("command") or "").strip()
            normalized = command.lower()
            if any(token in normalized for token in ("pytest", " test", "cargo test", "npm test", "pnpm test", "go test", "uv run")):
                commands.append(command or "test command")
            background_task = card.metadata.get("background_task")
            if isinstance(background_task, dict):
                background_tasks.append(str(background_task.get("task_id") or ""))
        if not commands and not background_tasks:
            return ""
        lines = []
        if commands:
            lines.append("Ran:")
            lines.extend(f"- {command}" for command in commands[:4])
        if background_tasks:
            lines.append("Background work still running:")
            lines.extend(f"- {task_id}" for task_id in background_tasks[:4] if task_id)
        return "\n".join(lines)

    def _finalize_current_round(self, *, outcome: str = "completed") -> None:
        round_state = self._current_round
        if round_state is None:
            return
        finished_at = self._clock()
        card = self.find_card(round_state.round_card_id)
        if card is not None:
            metrics = self._round_metrics_for_card(card)
            card.body = self._format_completed_round_body(
                round_state.started_at,
                finished_at,
                metrics=metrics,
                outcome=outcome,
            )
            card.metadata.update(
                {
                    "finished_at": finished_at,
                    "duration_seconds": max(finished_at - round_state.started_at, 0.0),
                    "outcome": outcome,
                }
            )
            self._touch(card)
        for card_id in (round_state.thinking_card_id, round_state.content_card_id):
            if not card_id:
                continue
            related = self.find_card(card_id)
            if related is None:
                continue
            if related.status is not None:
                related.status = None
                self._touch(related)
        self._current_round = None

    def _summarize_scalar(self, value: Any, *, max_chars: int) -> str:
        text = str(value).replace("\n", " ").strip()
        text = " ".join(text.split())
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."
