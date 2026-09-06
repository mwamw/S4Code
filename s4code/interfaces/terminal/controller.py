"""TerminalController: terminal interaction responsibilities."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime
import json
from pathlib import Path
import time
from typing import Any, AsyncGenerator, Optional

from s4code.interfaces.terminal.commands.registry import S4CommandRegistry
from s4code.interfaces.terminal.settings import S4Settings, resolve_settings
from s4code.core.application import S4CodeRuntime
from s4code.core.sessions.session import CoreSession


from .formatting import _safe_provider_endpoint


class TerminalController:
    def __init__(
        self,
        *,
        cwd: str | Path | None = None,
        session_id: Optional[str] = None,
        session_overrides: Optional[dict[str, Any]] = None,
        ignore_saved_model_overrides: bool = False,
        settings: S4Settings | None = None,
        core: CoreSession | None = None,
        application: S4CodeRuntime | None = None,
    ) -> None:
        if core is not None and application is None:
            raise ValueError("An injected Core session requires its owning runtime")
        self.application = application or S4CodeRuntime(cwd=cwd, settings=settings)
        self.paths = self.application.paths
        self.session_manager = self.application.catalog
        self.project = self.application.project
        self.command_registry = S4CommandRegistry()
        self.session_overrides = dict(session_overrides or {})
        self._restored_session = session_id is not None
        self._pending_turn_skills: list[str] = []
        self._closed = False
        self._last_close_report: Optional[dict[str, Any]] = None
        self._session_dirty = False
        self._runtime_cache: dict[str, tuple[float, Any]] = {}
        self._last_background_notice_states: dict[str, str] = {}
        self._last_command_usage: list[str] = []
        self._last_manual_compaction: dict[str, Any] = {}

        self.settings = settings or resolve_settings(
            self.paths,
            project_root=self.project.project_root,
            session_overrides=self.session_overrides,
        )
        self.core = (
            self.application.attach_session(core)
            if core is not None
            else self.application.open_session(
                session_id,
                overrides=self.session_overrides,
                ignore_saved_model=ignore_saved_model_overrides,
            )
        )
        self._sync_from_core()
        saved_ui = self.session_overrides.get("ui")
        if saved_ui:
            self.settings.ui = type(self.settings.ui).model_validate(saved_ui)
        from .status import StatusPresenter
        from .usage import UsagePresenter
        from .session_view import SessionPresenter
        from .workspace_view import WorkspacePresenter
        from .runtime import RuntimePresenter
        from .mcp import MCPPresenter
        from .permissions import PermissionCommands
        from .theme_commands import ThemeCommands
        from .skills import SkillCommands
        from .checkpoints import CheckpointManager

        self.status = StatusPresenter(self)
        self.usage = UsagePresenter(self)
        self.session_view = SessionPresenter(self)
        self.workspace_view = WorkspacePresenter(self)
        self.runtime = RuntimePresenter(self)
        self.mcp = MCPPresenter(self)
        self.permissions = PermissionCommands(self)
        self.theme = ThemeCommands(self)
        self.skills = SkillCommands(self)
        self.checkpoints = CheckpointManager(self)
        self.checkpoints._restore_checkpoints_from_overrides()
        self.sidebar_visible = bool(self.settings.ui.right_panel_open)

    def _sync_from_core(self) -> None:
        config, info = self.core.configuration(), self.core.info()
        self.settings = S4Settings.model_validate(
            {
                **config.model_dump(),
                "ui": self.settings.ui.model_dump(),
            }
        )
        self.session_id = info.session_id
        self.title = info.title
        self.session_overrides = self.core.session_overrides()
        self.forked_from_session_id = info.forked_from_session_id

    def _get_cached_runtime_value(
        self,
        key: str,
        *,
        max_age: float,
        force: bool = False,
        producer,
    ) -> Any:
        if not force:
            cached = self._runtime_cache.get(key)
            if cached is not None:
                cached_at, value = cached
                if (time.monotonic() - cached_at) <= max(float(max_age), 0.0):
                    return value
        value = producer()
        self._runtime_cache[key] = (time.monotonic(), value)
        return value

    def _invalidate_runtime_cache(self, *prefixes: str) -> None:
        if not prefixes:
            self._runtime_cache.clear()
            return
        stale = [
            key
            for key in self._runtime_cache
            if any(key == prefix or key.startswith(f"{prefix}:") for prefix in prefixes)
        ]
        for key in stale:
            self._runtime_cache.pop(key, None)

    def record_command_usage(self, command_name: str) -> None:
        normalized = str(command_name or "").strip().lower()
        if not normalized:
            return
        self._last_command_usage = [
            item for item in self._last_command_usage if item != normalized
        ]
        self._last_command_usage.insert(0, normalized)
        del self._last_command_usage[12:]

    def get_recent_command_usage(self) -> list[str]:
        return list(self._last_command_usage)

    def request_stop(self, reason: str = "") -> bool:
        return self.core.runs.cancel(reason or "User interrupted the S4Code TUI")

    @staticmethod
    def _parse_iso_timestamp(value: Any) -> Optional[float]:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None

    def _close_session(
        self, *, mark_closed: bool, record_report: bool
    ) -> dict[str, Any]:
        if self._closed and self._last_close_report is not None:
            return self._last_close_report
        if self._session_dirty:
            self.save_session(tolerate_failure=True)
        self.core.close()
        report = self.core.close_report()
        if record_report:
            self._last_close_report = report
        if mark_closed:
            self._closed = True
        return report

    def ensure_autosave(self) -> None:
        if self.settings.product.session_auto_save:
            self.save_session(tolerate_failure=True)

    def _mark_session_dirty(self) -> None:
        self._session_dirty = True

    def save_session(self, *, tolerate_failure: bool = False) -> None:
        self.core.update_metadata(
            title=self.title,
            overrides=self.session_overrides,
            autosave=self.settings.product.session_auto_save,
        )
        if tolerate_failure:
            self._session_dirty = self.core.autosave()["dirty"]
        else:
            self.core.save()
            self._session_dirty = False

    def resume_session(self, session_id: str) -> str:
        self.save_session(tolerate_failure=True)
        self.core = self.application.replace_session(self.core, session_id)
        self._sync_from_core()
        saved_ui = self.session_overrides.get("ui")
        if saved_ui:
            self.settings.ui = type(self.settings.ui).model_validate(saved_ui)
        self.sidebar_visible = bool(self.settings.ui.right_panel_open)
        self._pending_turn_skills.clear()
        self._runtime_cache.clear()
        self.checkpoints._restore_checkpoints_from_overrides()
        self._restored_session = True
        self._closed = False
        self._session_dirty = False
        self._last_close_report = None
        return f"Resumed session {session_id}"

    def rename_session(self, title: str) -> str:
        self.core.save(title)
        self.title = self.core.info().title
        return f"Session renamed to {self.title}"

    def fork_session(self, title: Optional[str] = None) -> str:
        self.save_session()
        source = self.session_id
        branch = self.core.fork(title)
        self.resume_session(branch.session_id)
        return f"Forked session {source} -> {self.session_id}"

    def update_model(self, target: str) -> str:
        if not target.strip():
            return self.status.format_models()
        result = self.core.select_model(target)
        self._sync_from_core()
        return f"Active model profile set to {result['profile']} ({result['provider']} / {result['model']})."

    def clear_history(self) -> str:
        self.core.clear_history()
        self.ensure_autosave()
        return "Conversation history cleared."

    def compact_history(self, max_tokens: Optional[int] = None) -> str:
        result = self.core.compact(max_tokens)
        self._last_manual_compaction = result
        return (
            "Conversation compacted."
            if result["was_compacted"]
            else "Compaction not needed."
        ) + (
            f"\nbefore={result['tokens_before']} after={result['tokens_after']} budget={result['max_tokens']}"
        )

    def run_prompt(self, prompt: str, *, max_iter: int = 50) -> str:
        self._maybe_update_title(prompt)
        self.checkpoints.create_checkpoint("before prompt", reason="before_prompt")
        selected_turn_skills = self.skills._consume_pending_turn_skills()
        if selected_turn_skills:
            self.skills._activate_turn_skills(selected_turn_skills)
        result = self.core.run(prompt, {"max_iter": max_iter})
        self.checkpoints.create_checkpoint("after prompt", reason="after_prompt")
        self.ensure_autosave()
        return result.text

    def _translate_core_stream_event(self, raw_event: Any) -> dict[str, Any]:
        payload = (
            raw_event.to_dict() if hasattr(raw_event, "to_dict") else dict(raw_event)
        )
        event_type = str(payload.get("type") or "")
        content = payload.get("content")
        data = dict(payload.get("data") or {})
        base = {
            "invocation_id": payload.get("run_id") or payload.get("invocationId"),
            "sequence": payload.get("sequence"),
        }
        if event_type == "reasoning_delta":
            return {"type": "thinking_delta", "delta": str(content or ""), **base}
        if event_type == "text_delta":
            return {"type": "text_delta", "delta": str(content or ""), **base}
        if event_type == "tool_call":
            return {
                "type": "tool_call",
                "tool_name": data.get("tool_name"),
                "tool_id": data.get("tool_call_id"),
                "tool_args": dict(data.get("arguments") or {}),
                **base,
            }
        if event_type == "tool_result":
            result = dict(data.get("result") or {})
            return {
                "type": "tool_result",
                "tool_name": data.get("tool_name"),
                "tool_id": data.get("tool_call_id"),
                "tool_args": dict(data.get("arguments") or {}),
                "status": data.get("status") or result.get("status"),
                "content": content
                or result.get("display_text")
                or result.get("content"),
                "structured_data": result.get("structured_data"),
                "result_metadata": dict(result.get("metadata") or {}),
                "error_type": result.get("error_type"),
                **base,
            }
        if event_type == "final":
            return {"type": "final", "content": str(content or ""), **base}
        if event_type == "run_finished":
            status = data.get("status")
            if status == "interaction_required":
                return {
                    "type": "interruption",
                    "content": "Approval or answer required.",
                    "payload": self.permissions.get_pending_interaction(),
                    **base,
                }
            if status == "cancelled":
                return {"type": "cancelled", "content": "Run cancelled", **base}
            return {"type": "run_finished", "status": status, **base}
        if event_type == "error" and bool(data.get("interrupted")):
            return {
                "type": "interruption",
                "content": str(content or "Agent execution interrupted."),
                "payload": self.permissions.get_pending_interaction(),
                **base,
            }
        if event_type in {"compaction_start", "compaction_result"}:
            from .runtime_notices import CompactionPresenter

            return {**CompactionPresenter.present(event_type, data), **base}
        if event_type == "round_start":
            return {"type": event_type, "round": data["round"], **base}
        if event_type != "error":
            return {"type": event_type, "data": data, **base}
        return {
            "type": "error",
            "error": str(content or "Agent execution failed."),
            "error_type": data.get("error_type"),
            "status_code": data.get("status_code"),
            "error_code": data.get("error_code"),
            "request_id": data.get("request_id"),
            "edge_trace_id": data.get("edge_trace_id"),
            "provider": self.core.info().provider,
            "model": self.core.info().model,
            "endpoint": _safe_provider_endpoint(self.settings.llm.base_url),
            **base,
        }

    def _should_emit_stream_event(self, event_type: str) -> bool:
        if event_type == "thinking_delta":
            return bool(self.settings.ui.show_thinking)
        return True

    async def stream_prompt(
        self, prompt: str, *, max_iter: int = 50
    ) -> AsyncGenerator[dict[str, Any], None]:
        self._maybe_update_title(prompt)
        queue: asyncio.Queue[dict[str, Any] | object] = asyncio.Queue()
        sentinel = object()
        selected_turn_skills = self.skills._consume_pending_turn_skills()
        activated_skills: list[dict[str, Any]] = []
        turn_started_at = time.time()
        active_round = 0
        emitted_round_metrics: dict[int, str] = {}
        bash_diff_before_by_tool_id: dict[str, str] = {}

        async def _produce() -> None:
            nonlocal active_round
            emitted_failure = False
            completed_event_type = None
            try:
                before_checkpoint = self.checkpoints.create_checkpoint(
                    "before turn", reason="before_prompt"
                )
                await queue.put(
                    {
                        "type": "checkpoint",
                        "checkpoint": before_checkpoint,
                        "content": f"Checkpoint created: {before_checkpoint.get('checkpoint_id')}",
                    }
                )
                if selected_turn_skills:
                    activated_skills[:] = self.skills._activate_turn_skills(
                        selected_turn_skills
                    )
                    successful = [
                        str(item.get("skill") or "")
                        for item in activated_skills
                        if item.get("success")
                    ]
                    failed = [
                        f"{item.get('skill')}: {item.get('error')}"
                        for item in activated_skills
                        if not item.get("success")
                    ]
                    notice_parts: list[str] = []
                    if successful:
                        notice_parts.append(
                            "Turn skills enabled: " + ", ".join(successful)
                        )
                    if failed:
                        notice_parts.append(
                            "Skill activation failed: " + "; ".join(failed)
                        )
                    await queue.put(
                        {
                            "type": "system_notice",
                            "content": "\n".join(notice_parts),
                        }
                    )
                async for raw_event in self.core.stream(prompt, {"max_iter": max_iter}):
                    event = self._translate_core_stream_event(raw_event)
                    event_type = str(event.get("type") or "")
                    if event_type == "round_start":
                        active_round = int(event["round"])
                    if not self._should_emit_stream_event(event_type):
                        continue
                    emitted_failure = emitted_failure or event_type in {
                        "error",
                        "interruption",
                    }
                    tool_name = str(event.get("tool_name") or "")
                    tool_id = str(event.get("tool_id") or "")
                    if event_type == "tool_call" and tool_name == "Bash" and tool_id:
                        bash_diff_before_by_tool_id[tool_id] = (
                            self.workspace_view._capture_working_tree_diff()
                        )
                    if event_type == "tool_result" and tool_name == "Bash" and tool_id:
                        event = self.workspace_view._maybe_attach_bash_diff(
                            event,
                            before_diff=bash_diff_before_by_tool_id.pop(tool_id, ""),
                        )
                    if (
                        event_type
                        in {"tool_result", "final", "interruption", "error", "usage"}
                        and active_round > 0
                    ):
                        metrics = self.usage._build_round_metrics(
                            round_number=active_round,
                            turn_started_at=turn_started_at,
                        )
                        if metrics:
                            fingerprint = json.dumps(
                                metrics, ensure_ascii=False, sort_keys=True
                            )
                            if emitted_round_metrics.get(active_round) != fingerprint:
                                emitted_round_metrics[active_round] = fingerprint
                                await queue.put(
                                    {
                                        "type": "round_metrics",
                                        "round": active_round,
                                        "metrics": metrics,
                                    }
                                )
                    await queue.put(event)
                    if event_type == "tool_result" and tool_name == "Bash":
                        background_notice = (
                            self.status._background_task_notice_from_event(event)
                        )
                        if background_notice is not None:
                            await queue.put(background_notice)
                    if event_type in {"final", "interruption"}:
                        completed_event_type = event_type
                # The generator must finish and release the Core operation
                # before checkpointing or persisting conversation state.
                if completed_event_type is not None:
                    after_checkpoint = self.checkpoints.create_checkpoint(
                        "after turn"
                        if completed_event_type == "final"
                        else "paused turn",
                        reason="after_prompt"
                        if completed_event_type == "final"
                        else "interruption",
                    )
                    await queue.put(
                        {
                            "type": "checkpoint",
                            "checkpoint": after_checkpoint,
                            "content": f"Checkpoint created: {after_checkpoint.get('checkpoint_id')}",
                        }
                    )
            except Exception as exc:
                if not emitted_failure:
                    await queue.put(
                        {"type": "error", "error": f"{type(exc).__name__}: {exc}"}
                    )
            finally:
                await queue.put(sentinel)

        producer = asyncio.create_task(_produce())
        try:
            while True:
                event = await queue.get()
                if event is sentinel:
                    break
                yield dict(event)
        finally:
            if not producer.done():
                producer.cancel()
                with suppress(asyncio.CancelledError):
                    await producer
            else:
                await producer
            self.ensure_autosave()

    def _maybe_update_title(self, prompt: str) -> None:
        if self.title.endswith(" session"):
            compact = " ".join(prompt.strip().split())
            if compact:
                self.title = compact[:72]

    def build_review_prompt(self, target: Optional[str] = None) -> str:
        from s4code.core.workflows import ReviewWorkflow

        return ReviewWorkflow().prompt(target)

    def build_commit_prompt(self) -> str:
        from s4code.core.workflows import CommitWorkflow

        return CommitWorkflow().prompt()

    def close(self) -> dict[str, Any]:
        report = self._close_session(mark_closed=True, record_report=True)
        self.application.close()
        return report
