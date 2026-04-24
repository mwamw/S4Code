"""Central S4Code query engine."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import copy
from datetime import datetime
import json
from pathlib import Path
import time
from typing import Any, AsyncGenerator, Optional
from urllib.parse import urlparse

from .command_registry import S4CommandRegistry
from .config import PermissionRuleSettings, S4Settings, dump_settings_yaml, resolve_settings
from .easyagent_adapter import S4AgentBundle, build_agent_bundle
from .paths import S4Paths, get_s4_paths
from .project import ProjectContext
from .session import S4SessionManager
from .theme import list_bundled_themes

from core.history import canonical_text_content, coerce_canonical_message
from core.permissions import PermissionBehavior, PermissionRule


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
        compaction_raw = usage.get("compaction") or {}
    compaction = dict(compaction_raw or {})
    if "max_tokens" not in compaction and compaction.get("budget") is not None:
        compaction["max_tokens"] = compaction.get("budget")
    return compaction


class S4QueryEngine:
    def __init__(
        self,
        *,
        cwd: str | Path | None = None,
        session_id: Optional[str] = None,
        session_overrides: Optional[dict[str, Any]] = None,
    ) -> None:
        self.paths = get_s4_paths().ensure()
        self.session_manager = S4SessionManager(self.paths)
        self.command_registry = S4CommandRegistry()
        self._base_session_overrides = dict(session_overrides or {})
        self.session_overrides = dict(self._base_session_overrides)
        self.project = ProjectContext.detect(cwd)
        self.bundle: S4AgentBundle
        self.session_id = session_id or self.session_manager.new_session_id(self.project)
        self.title = f"{self.project.project_name} session"
        self.forked_from_session_id: Optional[str] = None
        self._restored_session = session_id is not None
        self._pending_turn_skills: list[str] = []
        self._closed = False
        self._last_close_report: Optional[dict[str, Any]] = None
        self._checkpoints: list[dict[str, Any]] = []
        self._session_dirty = False
        self._runtime_cache: dict[str, tuple[float, Any]] = {}

        if session_id is not None:
            self._apply_session_record(self._require_session_record(session_id))

        self.settings = resolve_settings(
            self.paths,
            project_root=self.project.project_root,
            session_overrides=self.session_overrides,
        )
        self.bundle = build_agent_bundle(
            settings=self.settings,
            project=self.project,
            paths=self.paths,
            session_store=self.session_manager.store,
            restore_session_id=session_id,
        )
        self._restore_checkpoints_from_overrides()
        self.sidebar_visible = bool(self.settings.ui.right_panel_open)

    @property
    def agent(self):
        return self.bundle.agent

    @property
    def registry(self):
        return self.bundle.registry

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

    @property
    def was_restored(self) -> bool:
        return self._restored_session

    def request_stop(self, reason: str = "") -> bool:
        stopper = getattr(self.agent, "request_stop", None)
        if not callable(stopper):
            return False
        stopper(str(reason or "").strip() or "User interrupted the agent from the S4Code TUI.")
        return True

    def clear_stop_request(self) -> None:
        clearer = getattr(self.agent, "clear_stop_request", None)
        if callable(clearer):
            clearer()

    @staticmethod
    def _parse_iso_timestamp(value: Any) -> Optional[float]:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None

    def _get_skill_registry(self):
        return getattr(self.bundle, "skill_registry", None)

    def _get_process_manager(self):
        for tool_name in ("TaskOutput", "TaskStop", "Bash"):
            tool = self.registry.get_tool(tool_name)
            manager = getattr(tool, "process_manager", None) if tool is not None else None
            if manager is not None:
                return manager
        return None

    def _get_worktree_manager(self):
        for tool_name in ("EnterWorktree", "ExitWorktree", "Agent"):
            tool = self.registry.get_tool(tool_name)
            manager = getattr(tool, "worktree_manager", None) if tool is not None else None
            if manager is not None:
                return manager
        return None

    def _execute_registry_tool(
        self,
        tool_name: str,
        parameters: Optional[dict[str, Any]] = None,
        *,
        confirmed: bool = True,
    ):
        executor = (
            self.registry.execute_confirmed_tool_result
            if confirmed
            else self.registry.execute_tool_result
        )
        return executor(
            tool_name,
            dict(parameters or {}),
            permission_context=self.agent.permission_context,
            permission_engine=self.agent.permission_engine,
        )

    def _consume_pending_turn_skills(self) -> list[str]:
        skills = list(self._pending_turn_skills)
        self._pending_turn_skills.clear()
        return skills

    def _activate_turn_skills(
        self,
        skill_names: list[str],
    ) -> tuple[list[dict[str, Any]], str]:
        activated: list[dict[str, Any]] = []
        prompt_blocks: list[str] = []
        registry = self._get_skill_registry()
        if registry is None:
            return activated, ""
        manager = self.agent.skill_manager

        for raw_name in skill_names:
            name = str(raw_name or "").strip()
            if not name or not registry.has(name):
                continue
            existed_before = manager.has_skill(name)
            if existed_before:
                skill = manager.get_skill(name)
            else:
                skill = registry.create(name)
                manager.register(skill, auto_activate=False)
            was_active = manager.is_active(name)
            visibility = "runtime" if skill.get_exposure_mode() == "on_demand" else "resident"
            if not was_active:
                manager.activate(name, tool_visibility=visibility)
            activated.append(
                {
                    "name": name,
                    "created": not existed_before,
                    "was_active": was_active,
                }
            )
            if skill.get_exposure_mode() == "on_demand":
                body = skill.get_body_prompt().strip()
                heading = f"### {name}"
                if body:
                    prompt_blocks.append(f"{heading}\n{body}")
                else:
                    prompt_blocks.append(f"{heading}\n(No additional body prompt was provided.)")

        prompt_prefix = ""
        if prompt_blocks:
            prompt_prefix = (
                "The user explicitly enabled the following skills for this turn only. "
                "Treat them as active guidance for this request.\n\n"
                "## Turn Skills\n"
                f"{chr(10).join(prompt_blocks)}\n\n"
            )
        return activated, prompt_prefix

    def _cleanup_turn_skills(self, activated: list[dict[str, Any]]) -> None:
        manager = self.agent.skill_manager
        for payload in reversed(activated):
            name = str(payload.get("name") or "").strip()
            if not name:
                continue
            created = bool(payload.get("created"))
            was_active = bool(payload.get("was_active"))
            try:
                if created and manager.has_skill(name):
                    manager.unregister(name)
                elif not was_active and manager.is_active(name):
                    manager.deactivate(name)
            except Exception:
                continue

    def _build_round_metrics(
        self,
        *,
        round_number: int,
        turn_started_at: float,
    ) -> dict[str, Any]:
        llm_items: list[dict[str, Any]] = []
        tool_items: list[dict[str, Any]] = []
        estimated_cost = 0.0
        saw_cost = False

        for item in self.agent.get_recent_observability_events(limit=500):
            if not isinstance(item, dict):
                continue
            event_time = self._parse_iso_timestamp(item.get("endedAt") or item.get("startedAt"))
            if event_time is not None and event_time < turn_started_at:
                continue
            event_type = str(item.get("eventType") or "")
            if event_type == "llm":
                metadata = dict(item.get("metadata") or {})
                if int(metadata.get("round") or 0) != round_number:
                    continue
                llm_items.append(item)
                if item.get("costUsd") is not None:
                    try:
                        estimated_cost += float(item["costUsd"])
                        saw_cost = True
                    except Exception:
                        pass
            elif event_type == "tool":
                if int(item.get("round") or 0) != round_number:
                    continue
                tool_items.append(item)

        if not llm_items and not tool_items:
            return {}

        return {
            "round": round_number,
            "llm_requests": len(llm_items),
            "tool_calls": len(tool_items),
            "llm_duration_ms": sum(float(item.get("durationMs") or 0.0) for item in llm_items),
            "tool_duration_ms": sum(float(item.get("durationMs") or 0.0) for item in tool_items),
            "input_tokens": sum(int(item.get("inputTokens") or 0) for item in llm_items),
            "output_tokens": sum(int(item.get("outputTokens") or 0) for item in llm_items),
            "total_tokens": sum(int(item.get("totalTokens") or 0) for item in llm_items),
            "estimated_cost_usd": estimated_cost if saw_cost else None,
            "tools_used": sorted(
                {
                    str(item.get("toolName") or "").strip()
                    for item in tool_items
                    if str(item.get("toolName") or "").strip()
                }
            ),
        }

    def _get_background_task_snapshots(self, *, limit: int = 20, force: bool = False) -> list[dict[str, Any]]:
        def _produce() -> list[dict[str, Any]]:
            manager = self._get_process_manager()
            if manager is None:
                return []
            try:
                snapshots = manager.list_tasks()
            except Exception:
                return []
            result: list[dict[str, Any]] = []
            for snapshot in snapshots[: max(int(limit), 0)]:
                stdout = str(getattr(snapshot, "stdout", "") or "")
                stderr = str(getattr(snapshot, "stderr", "") or "")
                started_at = getattr(snapshot, "started_at", None)
                finished_at = getattr(snapshot, "finished_at", None)
                duration_seconds = None
                if isinstance(started_at, (int, float)):
                    end_time = finished_at if isinstance(finished_at, (int, float)) else time.time()
                    duration_seconds = max(float(end_time) - float(started_at), 0.0)
                result.append(
                    {
                        "task_id": getattr(snapshot, "task_id", ""),
                        "status": getattr(snapshot, "status", ""),
                        "cwd": getattr(snapshot, "cwd", ""),
                        "command": getattr(snapshot, "command", ""),
                        "return_code": getattr(snapshot, "return_code", None),
                        "started_at": started_at,
                        "finished_at": finished_at,
                        "duration_seconds": duration_seconds,
                        "stdout_tail": self._tail_text(stdout, max_chars=1200),
                        "stderr_tail": self._tail_text(stderr, max_chars=1200),
                        "stdout_bytes": len(stdout.encode("utf-8", errors="ignore")),
                        "stderr_bytes": len(stderr.encode("utf-8", errors="ignore")),
                    }
                )
            return result

        return self._get_cached_runtime_value(
            f"background:{int(limit)}",
            max_age=0.35,
            force=force,
            producer=_produce,
        )

    @staticmethod
    def _tail_text(value: str, *, max_chars: int = 1200) -> str:
        text = str(value or "")
        if len(text) <= max_chars:
            return text
        return text[-max_chars:]

    def _json_safe_copy(self, value: Any) -> Any:
        json_safe = getattr(self.agent, "_make_json_safe", None)
        try:
            payload = json_safe(value) if callable(json_safe) else value
            return json.loads(json.dumps(payload, ensure_ascii=False, default=str))
        except Exception:
            return copy.deepcopy(value)

    def _get_agent_history_snapshot(self) -> list[Any]:
        getter = getattr(self.agent, "get_canonical_history", None)
        if callable(getter):
            history = getter()
        else:
            history = getattr(self.agent, "history", [])
        if not isinstance(history, list):
            history = list(history or [])
        return self._json_safe_copy(history)

    def _restore_agent_history_snapshot(self, history: list[Any]) -> None:
        setter = getattr(self.agent, "_set_history_entries", None)
        if callable(setter):
            setter(self._json_safe_copy(history), rebuild_replay=True)
            return
        setattr(self.agent, "history", self._json_safe_copy(history))

    def _checkpoint_store(self) -> dict[str, Any]:
        return self.session_overrides.setdefault("_s4code", {})

    def _restore_checkpoints_from_overrides(self) -> None:
        store = self.session_overrides.get("_s4code")
        if not isinstance(store, dict):
            self._checkpoints = []
            return
        raw = store.get("checkpoints")
        if not isinstance(raw, list):
            self._checkpoints = []
            return
        checkpoints = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            checkpoint = dict(item)
            if checkpoint.get("checkpoint_id") and isinstance(checkpoint.get("history"), list):
                checkpoints.append(checkpoint)
        self._checkpoints = checkpoints[-30:]

    def _persist_checkpoints_to_overrides(self) -> None:
        self._checkpoint_store()["checkpoints"] = self._json_safe_copy(self._checkpoints[-30:])

    def _public_checkpoint_payload(self, checkpoint: dict[str, Any]) -> dict[str, Any]:
        payload = dict(checkpoint)
        payload.pop("history", None)
        return payload

    def create_checkpoint(self, label: Optional[str] = None, *, reason: str = "manual") -> dict[str, Any]:
        history = self._get_agent_history_snapshot()
        checkpoint_number = len(self._checkpoints) + 1
        checkpoint = {
            "checkpoint_id": f"cp-{checkpoint_number:03d}",
            "label": str(label or "").strip() or f"checkpoint {checkpoint_number}",
            "reason": str(reason or "manual"),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "session_id": self.session_id,
            "title": self.title,
            "history": history,
            "history_messages": len(history),
        }
        try:
            checkpoint["context"] = self.agent.get_context_usage()
        except Exception:
            checkpoint["context"] = {}
        self._checkpoints.append(self._json_safe_copy(checkpoint))
        self._checkpoints = self._checkpoints[-30:]
        self._persist_checkpoints_to_overrides()
        self._mark_session_dirty()
        self.ensure_autosave()
        return self._public_checkpoint_payload(checkpoint)

    def get_checkpoint_choices(self) -> list[dict[str, Any]]:
        return [self._public_checkpoint_payload(item) for item in self._checkpoints]

    def get_transcript_history_cards(self, *, limit: int = 200) -> list[dict[str, Any]]:
        history = self._get_agent_history_snapshot()
        if limit > 0:
            history = history[-limit:]
        cards: list[dict[str, Any]] = []
        for message in history:
            item = self._history_message_to_transcript_card(message)
            if item is not None:
                cards.append(item)
        return cards

    def _history_message_to_transcript_card(self, message: Any) -> Optional[dict[str, Any]]:
        role, text = self._history_message_role_and_text(message)
        text = str(text or "").strip()
        if not text:
            return None
        if role == "user":
            return {"kind": "user", "title": "You", "body": text}
        if role == "assistant":
            return {"kind": "assistant", "title": "Model Response", "body": text}
        if role == "tool":
            return {"kind": "tool", "title": "Tool History", "body": text, "status": "done"}
        if role == "system":
            return {"kind": "system", "title": "System", "body": text}
        return {"kind": "system", "title": f"History · {role or 'message'}", "body": text}

    def _history_message_role_and_text(self, message: Any) -> tuple[str, str]:
        canonical = coerce_canonical_message(message)
        if canonical is not None:
            return str(canonical.role), canonical.text_content()
        if isinstance(message, dict):
            role = str(message.get("role") or message.get("type") or "assistant")
            if message.get("record_type", message.get("schema")) == "canonical_message":
                return role, canonical_text_content(message)
            content = message.get("content")
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text") or item.get("thinking") or item.get("content")
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
            if checkpoint.get("checkpoint_id") == normalized or checkpoint.get("label") == normalized:
                return checkpoint
        raise ValueError(f"Checkpoint not found: {normalized}")

    def rewind_to_checkpoint(self, target: Optional[str] = None) -> str:
        checkpoint = self._resolve_checkpoint(target)
        history = checkpoint.get("history")
        if not isinstance(history, list):
            raise ValueError(f"Checkpoint has no restorable history: {checkpoint.get('checkpoint_id')}")
        self._restore_agent_history_snapshot(history)
        self.ensure_autosave()
        return (
            f"Rewound to {checkpoint.get('checkpoint_id')} | "
            f"{checkpoint.get('label')} | messages={checkpoint.get('history_messages', len(history))}"
        )

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
            f"Session: {self.session_id}",
            f"Title: {self.title}",
            f"Forked from: {self.forked_from_session_id or '-'}",
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
        try:
            trace = self.agent.get_trace_summary(limit_turns=5)
        except Exception:
            trace = []
        if trace:
            lines.extend(["", "Recent Turns:"])
            for item in trace:
                label = str(item.get("query") or item.get("turnId") or item.get("turn_id") or "-")
                status = str(item.get("status") or item.get("success") or "-")
                duration = item.get("durationMs") or item.get("duration_ms")
                suffix = f" | {duration}ms" if duration is not None else ""
                lines.append(f"- {label[:96]} | {status}{suffix}")
        return "\n".join(lines)

    def format_session_tree(self) -> str:
        sessions = self.get_session_choices(limit=100)
        if not sessions:
            return "No S4Code sessions found."
        by_parent: dict[str, list[dict[str, Any]]] = {}
        roots: list[dict[str, Any]] = []
        known_ids = {str(item.get("session_id") or "") for item in sessions}
        for item in sessions:
            parent = str(item.get("forked_from_session_id") or "")
            if parent and parent in known_ids:
                by_parent.setdefault(parent, []).append(item)
            else:
                roots.append(item)

        def _render(item: dict[str, Any], prefix: str = "") -> list[str]:
            marker = "*" if item.get("current") else "-"
            line = f"{prefix}{marker} {item.get('session_id')} | {item.get('title') or '-'}"
            children = sorted(by_parent.get(str(item.get("session_id")), []), key=lambda child: str(child.get("updated_at") or ""), reverse=True)
            lines = [line]
            for child in children:
                lines.extend(_render(child, prefix + "  "))
            return lines

        ordered_roots = sorted(roots, key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        lines: list[str] = []
        for item in ordered_roots:
            lines.extend(_render(item))
        return "\n".join(lines)

    def _capture_working_tree_diff(self) -> str:
        try:
            diff = self.project.get_diff(max_lines=1200)
        except Exception:
            return ""
        normalized = str(diff or "").strip()
        if normalized in {"", "No diff.", "Not a git repository."}:
            return ""
        return normalized

    def _maybe_attach_bash_diff(
        self,
        event: dict[str, Any],
        *,
        before_diff: str,
    ) -> dict[str, Any]:
        after_diff = self._capture_working_tree_diff()
        if not after_diff or after_diff == before_diff:
            return event
        updated = dict(event)
        structured_data = dict(updated.get("structured_data") or {})
        existing_diff = structured_data.get("diff")
        if not isinstance(existing_diff, dict) or not str(existing_diff.get("unified") or "").strip():
            structured_data["diff"] = {
                "unified": after_diff,
                "file_path": str(self.project.project_root),
                "relative_path": "Working tree diff after Bash",
                "created": False,
                "source": "bash",
            }
            updated["structured_data"] = structured_data
        return updated

    def get_runtime_snapshot_payload(self) -> dict[str, Any]:
        structured_tasks = []
        try:
            tasks = self.bundle.task_service.list_tasks(limit=20)
        except Exception:
            tasks = []
        for task in tasks:
            structured_tasks.append(
                {
                    "task_id": getattr(task, "task_id", ""),
                    "status": getattr(getattr(task, "status", None), "value", getattr(task, "status", "")),
                    "title": getattr(task, "title", ""),
                    "parent_task_id": getattr(task, "parent_task_id", None),
                }
            )
        try:
            context = self.agent.get_context_usage()
        except Exception:
            context = {}
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "session": {
                "session_id": self.session_id,
                "title": self.title,
                "checkpoints": len(self._checkpoints),
            },
            "worktree": self.get_worktree_status_payload(),
            "agents": self.get_agent_choices(limit=20),
            "tasks": structured_tasks,
            "background_tasks": self._get_background_task_snapshots(limit=20),
            "context": context,
        }

    def _require_session_record(self, session_id: str) -> dict[str, Any]:
        record = self.session_manager.get_record(session_id)
        if record is None:
            raise ValueError(f"Session not found: {session_id}")
        return record

    def _close_bundle(
        self,
        *,
        mark_closed: bool,
        record_report: bool,
    ) -> dict[str, Any]:
        if record_report and self._closed and self._last_close_report is not None:
            return dict(self._last_close_report)

        agent = getattr(getattr(self, "bundle", None), "agent", None)
        if agent is None:
            report = {
                "status": "closed",
                "metadata": {
                    "sessionId": self.session_id,
                    "title": self.title,
                    "hadAgent": False,
                },
                "components": {},
                "issues": [],
            }
            if record_report:
                self._last_close_report = report
            if mark_closed:
                self._closed = True
            return report

        if self._session_dirty and self.settings.product.session_auto_save:
            self.save_session(tolerate_failure=True)
        close_fn = getattr(agent, "close", None)
        if not callable(close_fn):
            report = {
                "status": "closed",
                "metadata": {
                    "sessionId": self.session_id,
                    "title": self.title,
                    "hadAgent": True,
                    "closeCallable": False,
                },
                "components": {},
                "issues": [],
            }
        else:
            report = dict(close_fn())
            report.setdefault("metadata", {})
            report["metadata"].update(
                {
                    "sessionId": self.session_id,
                    "title": self.title,
                }
            )
        if record_report:
            self._last_close_report = report
        if mark_closed:
            self._closed = True
        return report

    def _apply_session_record(self, record: dict[str, Any]) -> None:
        metadata = dict(record.get("metadata") or {})
        project_root = metadata.get("project_root") or str(self.project.project_root)
        self.project = ProjectContext.detect(project_root)
        stored_overrides = dict(metadata.get("session_overrides") or {})
        self.session_overrides = _deep_merge_dicts(stored_overrides, self._base_session_overrides)
        restored_title = str(metadata.get("title") or "").strip()
        if restored_title:
            self.title = restored_title
        self.forked_from_session_id = metadata.get("forked_from_session_id")

    def ensure_autosave(self) -> None:
        if self.settings.product.session_auto_save:
            self.save_session(tolerate_failure=True)

    def _mark_session_dirty(self) -> None:
        self._session_dirty = True

    def _note_session_persistence_failure(self, exc: Exception) -> None:
        message = f"Session persistence unavailable: {type(exc).__name__}: {exc}"
        if message not in self.bundle.startup_issues:
            self.bundle.startup_issues.append(message)

    def save_session(self, *, tolerate_failure: bool = False) -> None:
        metadata = self._build_session_metadata()
        try:
            self.agent.save_session(
                self.session_id,
                store=self.session_manager.store,
                metadata=metadata,
            )
            self._session_dirty = False
        except Exception as exc:
            if not tolerate_failure:
                raise
            self.settings.product.session_auto_save = False
            self._note_session_persistence_failure(exc)

    def _build_session_metadata(self) -> dict[str, Any]:
        return self.session_manager.build_metadata(
            project=self.project,
            title=self.title,
            settings_payload=self.settings.model_dump(mode="python"),
            session_overrides=self.session_overrides,
            forked_from_session_id=self.forked_from_session_id,
        )

    def resume_session(self, session_id: str) -> str:
        if getattr(self, "bundle", None) is not None:
            self._close_bundle(mark_closed=False, record_report=False)
        self._restored_session = True
        self._pending_turn_skills.clear()
        self._apply_session_record(self._require_session_record(session_id))
        self.settings = resolve_settings(
            self.paths,
            project_root=self.project.project_root,
            session_overrides=self.session_overrides,
        )
        self.bundle = build_agent_bundle(
            settings=self.settings,
            project=self.project,
            paths=self.paths,
            session_store=self.session_manager.store,
            restore_session_id=session_id,
        )
        self.session_id = session_id
        self._restore_checkpoints_from_overrides()
        self.sidebar_visible = bool(self.settings.ui.right_panel_open)
        self._closed = False
        self._last_close_report = None
        self._session_dirty = False
        summary = self.summarize_restore_report()
        if summary:
            return f"Resumed session {session_id}\n{summary}"
        return f"Resumed session {session_id}"

    def rename_session(self, title: str) -> str:
        new_title = str(title or "").strip()
        if not new_title:
            raise ValueError("Session title must be non-empty.")
        self.title = new_title
        self.save_session()
        return f"Session renamed to {new_title}"

    def fork_session(self, title: Optional[str] = None) -> str:
        self.save_session()
        previous_session_id = self.session_id
        previous_title = self.title
        self.session_id = self.session_manager.new_session_id(self.project)
        self.title = str(title or "").strip() or f"{previous_title} (fork)"
        self.forked_from_session_id = previous_session_id
        self.save_session()
        return f"Forked session {previous_session_id} -> {self.session_id}"

    def _refresh_context_compactor_llm(self) -> None:
        manager = self.bundle.context_manager
        if manager is None:
            return
        compactor = getattr(manager, "history_compactor", None)
        if compactor is not None and hasattr(compactor, "llm"):
            compactor.llm = self.agent.llm

    def update_model(self, target: str) -> str:
        raw_target = str(target or "").strip()
        if not raw_target:
            return self.format_models()
        if raw_target in self.settings.model_profiles:
            profile = self.settings.model_profiles[raw_target]
            self.agent.change_model(
                model=profile.model,
                provider=profile.provider,
                base_url=profile.base_url,
                api_key=profile.api_key,
                temperature=profile.temperature,
                max_tokens=profile.max_tokens,
                timeout=profile.timeout,
            )
            self.settings.active_model_profile = raw_target
            self.settings.llm = profile.model_copy(deep=True)
            self.session_overrides["active_model_profile"] = raw_target
            self.session_overrides.pop("llm", None)
            self._refresh_context_compactor_llm()
            self.ensure_autosave()
            return (
                f"Active model profile set to {raw_target} "
                f"({profile.provider} / {profile.model})."
            )

        self.agent.change_model(model=raw_target)
        self.settings.llm.model = raw_target
        self.session_overrides.setdefault("llm", {})["model"] = raw_target
        self._refresh_context_compactor_llm()
        self.ensure_autosave()
        return f"Model override set to {raw_target} on profile {self.settings.active_model_profile}."

    def get_theme_choices(self) -> list[dict[str, Any]]:
        current = str(self.settings.ui.theme or "s4")
        choices = [
            {
                "name": name,
                "active": name == current,
                "kind": "bundled",
            }
            for name in list_bundled_themes()
        ]
        if current and current not in {item["name"] for item in choices}:
            choices.append(
                {
                    "name": current,
                    "active": True,
                    "kind": "custom",
                }
            )
        return choices

    def format_themes(self) -> str:
        lines = [
            f"Current theme: {self.settings.ui.theme or 's4'}",
            "",
            "Themes:",
        ]
        for item in self.get_theme_choices():
            marker = "*" if item.get("active") else "-"
            lines.append(f"{marker} {item.get('name')} ({item.get('kind')})")
        lines.append("")
        lines.append("Usage: /theme <theme-name|theme-json-path>")
        return "\n".join(lines)

    def update_theme(self, target: str) -> str:
        raw_target = str(target or "").strip()
        if not raw_target:
            return self.format_themes()
        bundled = set(list_bundled_themes())
        if raw_target in bundled:
            normalized = raw_target
        else:
            candidate = Path(raw_target).expanduser()
            if not candidate.is_absolute():
                project_candidate = (self.project.project_root / candidate).resolve()
                candidate = project_candidate if project_candidate.exists() else candidate.resolve()
            if not candidate.exists() or not candidate.is_file():
                return (
                    f"Unknown theme: {raw_target}\n"
                    + self.format_themes()
                )
            normalized = str(candidate.resolve())
        self.settings.ui.theme = normalized
        self.session_overrides.setdefault("ui", {})["theme"] = normalized
        self._mark_session_dirty()
        self.ensure_autosave()
        return f"Theme set to {normalized}"

    def update_permission_mode(self, mode: str) -> str:
        normalized_mode = str(mode or "").strip()
        if not normalized_mode:
            return self.format_permissions()
        self.agent.set_permission_mode(normalized_mode)
        self.settings.product.permission_mode = normalized_mode
        self.session_overrides.setdefault("product", {})["permission_mode"] = normalized_mode
        self._record_permission_history(
            "mode",
            {
                "mode": normalized_mode,
            },
        )
        self._persist_permission_state()
        self.ensure_autosave()
        return f"Permission mode set to {normalized_mode}"

    def _permission_rules(self) -> list[PermissionRule]:
        context = getattr(self.agent, "permission_context", None)
        if context is None:
            return []
        iter_rules = getattr(context, "iter_rules", None)
        if callable(iter_rules):
            return list(iter_rules())
        return list(getattr(context, "rules", []) or [])

    def _permission_rules_payload(self) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for rule in self._permission_rules():
            try:
                item = rule.model_dump(mode="python")
            except Exception:
                item = dict(rule)
            payload.append(item)
        return payload

    def _permission_history(self) -> list[dict[str, Any]]:
        raw = self.session_overrides.get("product", {}).get("permission_history")
        if isinstance(raw, list):
            return [dict(item) for item in raw if isinstance(item, dict)]
        return list(self.settings.product.permission_history or [])

    def _record_permission_history(self, action: str, payload: dict[str, Any]) -> None:
        history = self._permission_history()
        event = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "action": str(action or "").strip(),
            **dict(payload or {}),
        }
        history.append(event)
        history = history[-100:]
        self.settings.product.permission_history = history
        self.session_overrides.setdefault("product", {})["permission_history"] = history

    def _persist_permission_state(self) -> None:
        rules_payload = self._permission_rules_payload()
        self.settings.product.permission_rules = [
            PermissionRuleSettings.model_validate(item)
            for item in rules_payload
        ]
        product_overrides = self.session_overrides.setdefault("product", {})
        product_overrides["permission_rules"] = rules_payload
        product_overrides["permission_history"] = self._permission_history()

    @staticmethod
    def _split_csv_values(value: str) -> list[str]:
        result = []
        for item in str(value or "").split(","):
            stripped = item.strip()
            if stripped:
                result.append(stripped)
        return result

    def _build_permission_matcher_from_options(self, options: dict[str, str]) -> dict[str, Any]:
        matcher: dict[str, Any] = {}
        if options.get("path"):
            matcher["path_prefixes"] = self._split_csv_values(options["path"])
        if options.get("paths"):
            matcher["path_prefixes"] = self._split_csv_values(options["paths"])
        if options.get("command"):
            matcher["command_prefixes"] = self._split_csv_values(options["command"])
        if options.get("cmd"):
            matcher["command_prefixes"] = self._split_csv_values(options["cmd"])
        if options.get("host"):
            matcher["hosts"] = self._split_csv_values(options["host"])
        if options.get("hosts"):
            matcher["hosts"] = self._split_csv_values(options["hosts"])
        if options.get("mcp"):
            matcher["mcp_servers"] = self._split_csv_values(options["mcp"])
        if options.get("server"):
            matcher["mcp_servers"] = self._split_csv_values(options["server"])
        if options.get("risk"):
            matcher["risk_categories"] = self._split_csv_values(options["risk"])
        if options.get("risks"):
            matcher["risk_categories"] = self._split_csv_values(options["risks"])

        param_equals: dict[str, str] = {}
        param_contains: dict[str, str] = {}
        for key, value in options.items():
            if key.startswith("equals:"):
                param_key = key.split(":", 1)[1].strip()
                if param_key:
                    param_equals[param_key] = value
            elif key.startswith("contains:"):
                param_key = key.split(":", 1)[1].strip()
                if param_key:
                    param_contains[param_key] = value
        if param_equals:
            matcher["param_equals"] = param_equals
        if param_contains:
            matcher["param_contains"] = param_contains
        return matcher

    def add_permission_rule_from_tokens(
        self,
        *,
        behavior: str,
        tool_name: str,
        tokens: list[str],
    ) -> str:
        normalized_tool = str(tool_name or "").strip()
        if not normalized_tool:
            return "Usage: /permissions [allow|deny|ask] <tool|*> [path=...] [host=...] [command=...] [mcp=...] [risk=...] [source=session] [desc=...]"
        normalized_behavior = PermissionBehavior(str(behavior or "").strip())
        options: dict[str, str] = {}
        free_parts: list[str] = []
        for token in list(tokens or []):
            if "=" in token:
                key, value = token.split("=", 1)
                options[key.strip().lower()] = value.strip()
            elif token:
                free_parts.append(str(token))
        source = options.pop("source", "session").strip() or "session"
        description = (
            options.pop("desc", None)
            or options.pop("description", None)
            or " ".join(free_parts).strip()
            or None
        )
        matcher = self._build_permission_matcher_from_options(options)
        rule = PermissionRule(
            tool_name=normalized_tool,
            behavior=normalized_behavior,
            matcher=matcher,
            source=source,
            description=description,
        )
        self.agent.add_permission_rule(rule, source=source)
        self._record_permission_history(
            "rule_added",
            {
                "behavior": normalized_behavior.value,
                "tool": normalized_tool,
                "source": source,
                "matcher": matcher,
                "description": description,
            },
        )
        self._persist_permission_state()
        self.ensure_autosave()
        scope = json.dumps(matcher, ensure_ascii=False, sort_keys=True) if matcher else "all matching calls"
        return f"Permission rule added: {normalized_behavior.value} {normalized_tool} ({scope})"

    def clear_permission_rules(self, *, source: Optional[str] = "session") -> str:
        normalized_source = str(source or "").strip()
        if normalized_source in {"", "session"}:
            self.agent.clear_permission_rules(source="session")
            target = "session"
        elif normalized_source in {"all", "*"}:
            self.agent.clear_permission_rules(source=None)
            target = "all"
        else:
            self.agent.clear_permission_rules(source=normalized_source)
            target = normalized_source
        self._record_permission_history(
            "rules_cleared",
            {
                "source": target,
            },
        )
        self._persist_permission_state()
        self.ensure_autosave()
        return f"Permission rules cleared: {target}"

    def get_permission_status_payload(self) -> dict[str, Any]:
        context = getattr(self.agent, "permission_context", None)
        mode = getattr(getattr(context, "mode", None), "value", getattr(context, "mode", None))
        rules = self._permission_rules_payload()
        source_counts: dict[str, int] = {}
        behavior_counts: dict[str, int] = {}
        for rule in rules:
            source = str(rule.get("source") or "session")
            behavior = str(rule.get("behavior") or "")
            source_counts[source] = source_counts.get(source, 0) + 1
            behavior_counts[behavior] = behavior_counts.get(behavior, 0) + 1
        return {
            "mode": mode,
            "ruleCount": len(rules),
            "sourceCounts": source_counts,
            "behaviorCounts": behavior_counts,
            "rules": rules,
            "history": self._permission_history()[-20:],
        }

    def format_permissions(self) -> str:
        payload = self.get_permission_status_payload()
        lines = [
            f"Permission mode: {payload.get('mode') or '-'}",
            f"Rules: {payload.get('ruleCount', 0)}",
        ]
        source_counts = dict(payload.get("sourceCounts") or {})
        if source_counts:
            lines.append("Sources: " + ", ".join(f"{source}={count}" for source, count in sorted(source_counts.items())))
        rules = list(payload.get("rules") or [])
        if rules:
            lines.append("")
            lines.append("Rules:")
            for index, rule in enumerate(rules, start=1):
                matcher = rule.get("matcher") or {}
                matcher_text = json.dumps(matcher, ensure_ascii=False, sort_keys=True) if matcher else "{}"
                description = str(rule.get("description") or "").strip()
                suffix = f" | {description}" if description else ""
                lines.append(
                    f"{index}. {rule.get('behavior')} {rule.get('tool_name')} "
                    f"source={rule.get('source') or '-'} matcher={matcher_text}{suffix}"
                )
        else:
            lines.append("No permission rules.")
        lines.append("")
        lines.append("Usage:")
        lines.append("/permissions mode <default|accept_edits|dont_ask|bypass|plan>")
        lines.append("/permissions allow <tool|*> [path=prefix] [host=domain] [command=prefix] [mcp=server] [risk=category]")
        lines.append("/permissions deny <tool|*> [path=prefix] [host=domain] [command=prefix] [mcp=server] [risk=category]")
        lines.append("/permissions ask <tool|*> [path=prefix] [host=domain] [command=prefix] [mcp=server] [risk=category]")
        lines.append("/permissions clear [session|source|all]")
        return "\n".join(lines)

    def format_permission_history(self) -> str:
        history = self._permission_history()
        if not history:
            return "No permission history."
        lines = []
        for item in history[-20:]:
            action = str(item.get("action") or "-")
            ts = str(item.get("ts") or "-")
            details = {
                key: value
                for key, value in item.items()
                if key not in {"action", "ts"}
            }
            lines.append(f"{ts} | {action} | {json.dumps(details, ensure_ascii=False, sort_keys=True)}")
        return "\n".join(lines)

    def enter_plan_mode(self) -> str:
        self.agent.enter_plan_mode()
        return "Entered plan mode."

    def exit_plan_mode(self) -> str:
        target_mode = self.settings.product.permission_mode
        self.agent.exit_plan_mode(permission_mode=target_mode)
        return f"Exited plan mode. Permission mode restored to {target_mode}."

    def clear_history(self) -> str:
        self.agent.clear_history()
        self.ensure_autosave()
        return "Conversation history cleared."

    def compact_history(self, max_tokens: Optional[int] = None) -> str:
        changed = self.agent.compact_history(max_tokens=max_tokens)
        usage = self.agent.get_context_usage()
        compaction = _extract_last_compaction_state(dict(usage or {}))
        self.ensure_autosave()
        if compaction.get("hook_blocked"):
            return f"Compaction blocked.\nmessage={compaction.get('hook_message') or 'blocked by hook'}"
        if changed:
            return (
                "Conversation compacted.\n"
                f"before={compaction.get('tokens_before', '?')} "
                f"after={compaction.get('tokens_after', '?')} "
                f"budget={compaction.get('max_tokens', '?')}"
            )
        if compaction.get("compaction_possible") is False:
            return (
                "Compaction not needed.\n"
                f"before={compaction.get('tokens_before', '?')} "
                f"after={compaction.get('tokens_after', '?')} "
                f"budget={compaction.get('max_tokens', '?')}"
            )
        return "Compaction not needed."

    def run_prompt(self, prompt: str, *, max_iter: int = 20) -> str:
        self._maybe_update_title(prompt)
        self.create_checkpoint("before prompt", reason="before_prompt")
        selected_turn_skills = self._consume_pending_turn_skills()
        activated_skills: list[dict[str, Any]] = []
        effective_prompt = prompt
        try:
            if selected_turn_skills:
                activated_skills, prompt_prefix = self._activate_turn_skills(selected_turn_skills)
                effective_prompt = f"{prompt_prefix}{prompt}" if prompt_prefix else prompt
            result = self.agent.invoke(effective_prompt, max_iter=max_iter)
            self.create_checkpoint("after prompt", reason="after_prompt")
            self.ensure_autosave()
            return result
        finally:
            self._cleanup_turn_skills(activated_skills)

    async def stream_prompt(self, prompt: str, *, max_iter: int = 20) -> AsyncGenerator[dict[str, Any], None]:
        self._maybe_update_title(prompt)
        queue: asyncio.Queue[dict[str, Any] | object] = asyncio.Queue()
        sentinel = object()
        runtime_hook = self.bundle.runtime_notice_hook
        selected_turn_skills = self._consume_pending_turn_skills()
        activated_skills: list[dict[str, Any]] = []
        prompt_prefix = ""
        effective_prompt = prompt
        turn_started_at = time.time()
        active_round = 0
        emitted_round_metrics: dict[int, str] = {}
        bash_diff_before_by_tool_id: dict[str, str] = {}

        def _emit(event: dict[str, Any]) -> None:
            queue.put_nowait(dict(event))

        async def _produce() -> None:
            nonlocal active_round, effective_prompt, prompt_prefix
            try:
                before_checkpoint = self.create_checkpoint("before turn", reason="before_prompt")
                await queue.put(
                    {
                        "type": "checkpoint",
                        "checkpoint": before_checkpoint,
                        "content": f"Checkpoint created: {before_checkpoint.get('checkpoint_id')}",
                    }
                )
                if selected_turn_skills:
                    activated_skills[:], prompt_prefix_value = self._activate_turn_skills(selected_turn_skills)
                    prompt_prefix = prompt_prefix_value
                    effective_prompt = f"{prompt_prefix}{prompt}" if prompt_prefix else prompt
                    await queue.put(
                        {
                            "type": "system_notice",
                            "content": (
                                "Turn skills enabled: "
                                + ", ".join(str(item["name"]) for item in activated_skills)
                            ),
                        }
                    )
                async for event in self.agent.astream_invoke_with_tool(effective_prompt, max_iter=max_iter):
                    event = dict(event)
                    event_type = str(event.get("type") or "")
                    if event_type == "round_start":
                        active_round = int(event.get("round") or 0)
                    tool_name = str(event.get("tool_name") or "")
                    tool_id = str(event.get("tool_id") or "")
                    if event_type == "tool_call" and tool_name == "Bash" and tool_id:
                        bash_diff_before_by_tool_id[tool_id] = self._capture_working_tree_diff()
                    if event_type == "tool_result" and tool_name == "Bash" and tool_id:
                        event = self._maybe_attach_bash_diff(
                            event,
                            before_diff=bash_diff_before_by_tool_id.pop(tool_id, ""),
                        )
                    if runtime_hook is not None and runtime_hook.has_pending_compactions:
                        runtime_hook.flush_compaction_result(self.agent)
                    await queue.put(event)
                    if event_type in {"tool_result", "final", "interruption", "error"} and active_round > 0:
                        metrics = self._build_round_metrics(
                            round_number=active_round,
                            turn_started_at=turn_started_at,
                        )
                        if metrics:
                            fingerprint = json.dumps(metrics, ensure_ascii=False, sort_keys=True)
                            if emitted_round_metrics.get(active_round) != fingerprint:
                                emitted_round_metrics[active_round] = fingerprint
                                await queue.put(
                                    {
                                        "type": "round_metrics",
                                        "round": active_round,
                                        "metrics": metrics,
                                    }
                                )
                    if event_type in {"final", "interruption"}:
                        after_checkpoint = self.create_checkpoint(
                            "after turn" if event_type == "final" else "paused turn",
                            reason="after_prompt" if event_type == "final" else "interruption",
                        )
                        await queue.put(
                            {
                                "type": "checkpoint",
                                "checkpoint": after_checkpoint,
                                "content": f"Checkpoint created: {after_checkpoint.get('checkpoint_id')}",
                            }
                        )
                if runtime_hook is not None and runtime_hook.has_pending_compactions:
                    runtime_hook.flush_compaction_result(self.agent)
            except Exception as exc:
                await queue.put({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
            finally:
                await queue.put(sentinel)

        if runtime_hook is not None:
            runtime_hook.bind_emitter(_emit)
        producer = asyncio.create_task(_produce())
        try:
            while True:
                event = await queue.get()
                if event is sentinel:
                    break
                yield dict(event)
        finally:
            if runtime_hook is not None:
                runtime_hook.bind_emitter(None)
            if not producer.done():
                producer.cancel()
                with suppress(asyncio.CancelledError):
                    await producer
            else:
                await producer
            self._cleanup_turn_skills(activated_skills)
            self.clear_stop_request()
            self.ensure_autosave()

    def _maybe_update_title(self, prompt: str) -> None:
        if self.title.endswith(" session"):
            compact = " ".join(prompt.strip().split())
            if compact:
                self.title = compact[:72]

    def format_help(self) -> str:
        lines = ["Available commands:"]
        for command in self.command_registry.list_commands():
            usage = f" {command.usage}" if command.usage else ""
            aliases = f" ({', '.join('/' + alias for alias in command.aliases)})" if command.aliases else ""
            lines.append(f"/{command.name}{usage}{aliases}: {command.description}")
        return "\n".join(lines)

    def format_status(self) -> str:
        agent_mode = self.agent.get_execution_mode().value
        agent_count = len(self.agent.agent_runtime.list_handles(limit=1000)) if self.agent.agent_runtime is not None else 0
        task_count = len(self.bundle.task_service.list_tasks(limit=1000))
        background_task_count = len(self._get_background_task_snapshots(limit=1000))
        restore_report = self.get_restore_report()
        worktree = self.get_worktree_status_payload()
        skills = self.get_skill_choices()
        permissions = self.get_permission_status_payload()
        status = {
            "sessionId": self.session_id,
            "title": self.title,
            "projectRoot": str(self.project.project_root),
            "branch": self.project.branch,
            "activeModelProfile": self.settings.active_model_profile,
            "model": getattr(self.agent.llm, "model", None),
            "provider": getattr(self.agent.llm, "provider_name", None),
            "executionMode": agent_mode,
            "permissionMode": getattr(getattr(self.agent, "permission_context", None), "mode", None).value,
            "permissions": {
                "mode": permissions.get("mode"),
                "ruleCount": permissions.get("ruleCount"),
                "sourceCounts": permissions.get("sourceCounts"),
                "behaviorCounts": permissions.get("behaviorCounts"),
            },
            "agents": agent_count,
            "tasks": task_count,
            "backgroundTasks": background_task_count,
            "checkpoints": len(self._checkpoints),
            "toolCount": len(self.registry.get_tool_names()),
            "codeintelEnabled": self.settings.product.enable_codeintel,
            "mcpServers": list(self.registry.list_runtime_surfaces("mcp_manager").keys()),
            "skills": {
                "available": len(skills),
                "registered": sum(1 for item in skills if item["registered"]),
                "active": sum(1 for item in skills if item["active"]),
                "pendingTurn": list(self._pending_turn_skills),
                "sources": list(getattr(self.bundle, "skill_sources", ()) or ()),
            },
            "worktree": worktree,
            "context": self.agent.get_context_usage(),
            "startupIssues": list(self.bundle.startup_issues),
            "closed": self._closed,
            "lastCloseStatus": (
                str(self._last_close_report.get("status") or "")
                if isinstance(self._last_close_report, dict)
                else None
            ),
            "restore": (
                {
                    "status": restore_report.get("status"),
                    "issueCount": len(list(restore_report.get("issues") or [])),
                    "missingTools": list(restore_report.get("missingTools") or []),
                    "missingSkills": list(restore_report.get("missingSkills") or []),
                }
                if isinstance(restore_report, dict)
                else None
            ),
        }
        return json.dumps(status, ensure_ascii=False, indent=2)

    def format_sidebar(self, *, force: bool = False) -> str:
        permission_mode = getattr(getattr(self.agent, "permission_context", None), "mode", None).value
        permission_status = self.get_permission_status_payload()
        agent_mode = self.agent.get_execution_mode().value
        handles = self.get_agent_choices(limit=5, force=force)
        tasks = self.get_task_choices(limit=5, force=force)
        background_tasks = self._get_background_task_snapshots(limit=5, force=force)
        worktree = self.get_worktree_status_payload()
        skills = self.get_skill_choices()
        active_skills = [item["name"] for item in skills if item["active"]]
        context_usage = self.agent.get_context_usage()
        restore_report = self.get_restore_report()
        mcp_summary = self.get_mcp_summary_payload()
        restore_status = "-"
        restore_issue_count = 0
        if isinstance(restore_report, dict):
            restore_status = str(restore_report.get("status") or "-")
            restore_issue_count = len(list(restore_report.get("issues") or []))
        mcp_line = "disabled"
        if mcp_summary.get("enabled"):
            configured = int(mcp_summary.get("configured") or 0)
            if configured <= 0:
                mcp_line = "none"
            else:
                parts = [
                    f"{configured} configured",
                    f"{int(mcp_summary.get('connected') or 0)} connected",
                ]
                disabled = int(mcp_summary.get("disabled") or 0)
                unavailable = int(mcp_summary.get("unavailable") or 0)
                if disabled:
                    parts.append(f"{disabled} disabled")
                if unavailable:
                    parts.append(f"{unavailable} unavailable")
                mcp_line = " | ".join(parts)
        lines = [
            f"Project: {self.project.project_name}",
            f"Branch: {self.project.branch or '-'}",
            f"Profile: {self.settings.active_model_profile}",
            f"Model: {getattr(self.agent.llm, 'model', '-')}",
            f"Provider: {getattr(self.agent.llm, 'provider_name', '-')}",
            f"Mode: {agent_mode}",
            f"Permissions: {permission_mode} ({permission_status.get('ruleCount', 0)} rules)",
            f"Session: {self.session_id}",
            f"Checkpoints: {len(self._checkpoints)}",
            f"Tools: {len(self.registry.get_tool_names())}",
            f"MCP: {mcp_line}",
            f"Restore: {restore_status} ({restore_issue_count} issue(s))",
            (
                "Worktree: "
                + (
                    f"{worktree['active']['branch'] or '-'} @ {worktree['active']['path']}"
                    if worktree.get("active")
                    else "none"
                )
            ),
            f"Skills: {len(skills)} available / {len(active_skills)} active",
            "",
            "Context:",
            (
                f"- used={context_usage.get('used_tokens', '?')} "
                f"remaining={context_usage.get('remaining_tokens', '?')} "
                f"max={context_usage.get('max_tokens', '?')}"
            ),
            "",
            "Next Turn Skills:",
        ]
        if self._pending_turn_skills:
            lines.extend(f"- {name}" for name in self._pending_turn_skills[:5])
        else:
            lines.append("- none")
        lines.extend(
            [
                "",
                "Active Skills:",
            ]
        )
        if active_skills:
            lines.extend(f"- {name}" for name in active_skills[:5])
        else:
            lines.append("- none")
        lines.extend(
            [
                "",
                "Background Tasks:",
            ]
        )
        if background_tasks:
            for item in background_tasks:
                lines.append(f"- {item['task_id']}: {item['status']}")
        else:
            lines.append("- none")
        lines.extend(
            [
                "",
                "Recent Tasks:",
            ]
        )
        if tasks:
            for task in tasks[:5]:
                lines.append(f"- {task['task_id']}: {task['title']} [{task['status']}]")
        else:
            lines.append("- none")
        lines.append("")
        lines.append("Agents:")
        if handles:
            for handle in handles[:5]:
                lines.append(f"- {handle['agent_id']}: {handle['status']}")
        else:
            lines.append("- none")
        return "\n".join(lines)

    def toggle_sidebar(self, visible: Optional[bool] = None) -> str:
        if visible is None:
            self.sidebar_visible = not self.sidebar_visible
        else:
            self.sidebar_visible = bool(visible)
        return "Sidebar shown." if self.sidebar_visible else "Sidebar hidden."

    def format_current_session(self) -> str:
        return json.dumps(
            {
                "sessionId": self.session_id,
                "title": self.title,
                "projectRoot": str(self.project.project_root),
                "forkedFromSessionId": self.forked_from_session_id,
                "checkpoints": self.get_checkpoint_choices(),
            },
            ensure_ascii=False,
            indent=2,
        )

    def get_model_choices(self) -> list[dict[str, Any]]:
        choices: list[dict[str, Any]] = []
        for name, profile in self.settings.model_profiles.items():
            choices.append(
                {
                    "name": name,
                    "provider": profile.provider,
                    "model": profile.model,
                    "active": name == self.settings.active_model_profile,
                }
            )
        return choices

    def get_session_choices(self, *, limit: int = 20) -> list[dict[str, Any]]:
        choices: list[dict[str, Any]] = []
        for item in self.session_manager.list_sessions(limit=limit):
            choices.append(
                {
                    "session_id": item.session_id,
                    "title": item.title,
                    "model": item.model,
                    "provider": item.provider,
                    "project_root": item.project_root,
                    "permission_mode": item.permission_mode,
                    "branch": item.branch,
                    "forked_from_session_id": item.forked_from_session_id,
                    "updated_at": item.updated_at.isoformat() if item.updated_at is not None else None,
                    "current": item.session_id == self.session_id,
                }
            )
        return choices

    def get_skill_choices(self) -> list[dict[str, Any]]:
        registry = self._get_skill_registry()
        if registry is None:
            return []
        manifests = []
        for manifest in registry.list_manifests():
            if manifest.name == "meta_skill":
                continue
            manifests.append(
                {
                    "name": manifest.name,
                    "description": manifest.description,
                    "listing_description": manifest.listing_description,
                    "when_to_use": manifest.when_to_use,
                    "priority": manifest.priority,
                    "exposure_mode": manifest.exposure_mode,
                    "execution_mode": manifest.execution_mode,
                    "source_type": manifest.source_type,
                    "source_path": manifest.source_path,
                    "tool_names": list(manifest.tool_names),
                    "registered": self.agent.skill_manager.has_skill(manifest.name),
                    "active": self.agent.skill_manager.is_active(manifest.name),
                    "pending": manifest.name in self._pending_turn_skills,
                }
            )
        return manifests

    def queue_turn_skill(self, skill_name: str) -> str:
        normalized = str(skill_name or "").strip()
        if not normalized:
            return self.format_skills()
        registry = self._get_skill_registry()
        if registry is None or normalized == "meta_skill" or not registry.has(normalized):
            raise ValueError(f"Unknown skill: {normalized}")
        if normalized not in self._pending_turn_skills:
            self._pending_turn_skills.append(normalized)
        return f"Skill queued for the next turn: {normalized}"

    def clear_turn_skills(self) -> str:
        if not self._pending_turn_skills:
            return "No queued turn skills."
        cleared = ", ".join(self._pending_turn_skills)
        self._pending_turn_skills.clear()
        return f"Cleared queued turn skills: {cleared}"

    def format_skills(self) -> str:
        skills = self.get_skill_choices()
        if not skills:
            return "No skills discovered."
        lines: list[str] = []
        for item in skills:
            markers: list[str] = []
            if item["active"]:
                markers.append("active")
            if item["pending"]:
                markers.append("next-turn")
            if item["registered"] and not item["active"]:
                markers.append("registered")
            status = f" [{', '.join(markers)}]" if markers else ""
            lines.append(
                f"{item['name']}{status} | {item['exposure_mode']}/{item['execution_mode']} | "
                f"{item['listing_description'] or item['description'] or '-'} | "
                f"{item['source_path'] or item['source_type']}"
            )
        return "\n".join(lines)

    def get_worktree_status_payload(self) -> dict[str, Any]:
        manager = self._get_worktree_manager()
        if manager is None:
            return {"enabled": False, "available": False}
        active_session = None
        managed_worktrees: list[Any] = []
        try:
            active_session = manager.get_active_session()
        except Exception:
            active_session = None
        try:
            managed_worktrees = list(manager.list_managed_worktrees())
        except Exception:
            managed_worktrees = []
        active_payload = None
        if active_session is not None:
            active_payload = {
                "path": getattr(getattr(active_session, "worktree", None), "path", None),
                "branch": getattr(getattr(active_session, "worktree", None), "branch", None),
                "original_cwd": getattr(active_session, "original_cwd", None),
                "created_at": getattr(active_session, "created_at", None),
            }
        return {
            "enabled": True,
            "available": True,
            "active": active_payload,
            "managed": [
                {
                    "path": getattr(item, "path", None),
                    "branch": getattr(item, "branch", None),
                    "head": getattr(item, "head", None),
                }
                for item in managed_worktrees
            ],
        }

    def format_worktree_status(self) -> str:
        payload = self.get_worktree_status_payload()
        if not payload.get("available"):
            return "Worktree runtime is not available."
        active = payload.get("active")
        lines = [f"Managed worktrees: {len(list(payload.get('managed') or []))}"]
        if active:
            lines.append(f"Active path: {active.get('path') or '-'}")
            lines.append(f"Active branch: {active.get('branch') or '-'}")
            lines.append(f"Original cwd: {active.get('original_cwd') or '-'}")
        else:
            lines.append("Active worktree: none")
        return "\n".join(lines)

    def enter_worktree(self, name: Optional[str] = None) -> str:
        parameters = {"name": str(name).strip()} if str(name or "").strip() else {}
        result = self._execute_registry_tool("EnterWorktree", parameters)
        self.ensure_autosave()
        return result.to_display_string()

    def exit_worktree(self, *, action: str = "keep", discard_changes: bool = False) -> str:
        result = self._execute_registry_tool(
            "ExitWorktree",
            {
                "action": action,
                "discard_changes": discard_changes,
            },
        )
        self.ensure_autosave()
        return result.to_display_string()

    def get_agent_choices(self, *, limit: int = 20, force: bool = False) -> list[dict[str, Any]]:
        def _produce() -> list[dict[str, Any]]:
            runtime = self.agent.agent_runtime
            if runtime is None:
                return []
            handles = runtime.list_handles(limit=limit)
            return [
                {
                    "agent_id": handle.agent_id,
                    "status": handle.status,
                    "name": handle.name,
                    "task_id": getattr(getattr(handle, "execution_context", None), "current_task_id", None),
                    "output_file": handle.output_file,
                }
                for handle in handles
            ]

        return self._get_cached_runtime_value(
            f"agents:{int(limit)}",
            max_age=0.35,
            force=force,
            producer=_produce,
        )

    def get_task_choices(self, *, limit: int = 20, force: bool = False) -> list[dict[str, Any]]:
        def _produce() -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            for task in self.bundle.task_service.list_tasks(limit=limit):
                seen_ids.add(task.task_id)
                result.append(
                    {
                        "task_id": task.task_id,
                        "status": task.status.value,
                        "title": task.title,
                        "kind": "structured",
                    }
                )
            for snapshot in self._get_background_task_snapshots(limit=limit, force=force):
                task_id = str(snapshot.get("task_id") or "")
                if not task_id or task_id in seen_ids:
                    continue
                result.append(
                    {
                        "task_id": task_id,
                        "status": str(snapshot.get("status") or ""),
                        "title": str(snapshot.get("command") or snapshot.get("cwd") or task_id),
                        "kind": "background",
                    }
                )
            return result

        return self._get_cached_runtime_value(
            f"tasks:{int(limit)}",
            max_age=0.35,
            force=force,
            producer=_produce,
        )

    def has_live_runtime_activity(self, *, force: bool = False) -> bool:
        live_task_statuses = {"open", "in_progress", "blocked", "running"}
        live_agent_statuses = {"running", "queued", "waiting", "busy"}
        if any(
            str(item.get("status") or "").lower() in live_agent_statuses
            for item in self.get_agent_choices(limit=100, force=force)
        ):
            return True
        if any(
            str(item.get("status") or "").lower() in live_task_statuses
            for item in self.get_task_choices(limit=100, force=force)
        ):
            return True
        return False

    def format_agent_detail(self, agent_id: str) -> str:
        result = self._execute_registry_tool("AgentGet", {"agent_id": agent_id})
        return result.to_display_string()

    def wait_for_agent(self, agent_id: str, *, timeout_ms: Optional[int] = None) -> str:
        result = self._execute_registry_tool(
            "AgentWait",
            {
                "agent_id": agent_id,
                "timeout_ms": timeout_ms,
            },
        )
        return result.to_display_string()

    def stop_agent(self, agent_id: str, *, reason: str = "", wait: bool = False, timeout_ms: Optional[int] = None) -> str:
        result = self._execute_registry_tool(
            "AgentStop",
            {
                "agent_id": agent_id,
                "reason": reason,
                "wait": wait,
                "timeout_ms": timeout_ms,
            },
        )
        self.ensure_autosave()
        return result.to_display_string()

    def format_task_detail(self, task_id: str) -> str:
        try:
            task = self.bundle.task_service.get_task(task_id)
            return json.dumps(task.model_dump(mode="json"), ensure_ascii=False, indent=2)
        except Exception:
            pass
        manager = self._get_process_manager()
        if manager is None:
            raise ValueError(f"Task not found: {task_id}")
        try:
            snapshot = manager.get_task(task_id)
        except Exception as exc:
            raise ValueError(f"Task not found: {task_id}") from exc
        return json.dumps(
            {
                "taskId": getattr(snapshot, "task_id", ""),
                "status": getattr(snapshot, "status", ""),
                "cwd": getattr(snapshot, "cwd", ""),
                "command": getattr(snapshot, "command", ""),
                "returnCode": getattr(snapshot, "return_code", None),
                "startedAt": getattr(snapshot, "started_at", None),
                "finishedAt": getattr(snapshot, "finished_at", None),
                "stdoutTail": self._tail_text(str(getattr(snapshot, "stdout", "") or ""), max_chars=4000),
                "stderrTail": self._tail_text(str(getattr(snapshot, "stderr", "") or ""), max_chars=4000),
            },
            ensure_ascii=False,
            indent=2,
        )

    def format_task_output(self, task_id: str, *, block: bool = False, timeout_ms: Optional[int] = None) -> str:
        result = self._execute_registry_tool(
            "TaskOutput",
            {
                "task_id": task_id,
                "block": block,
                "timeout": timeout_ms,
            },
        )
        return result.to_display_string()

    def stop_task(self, task_id: str) -> str:
        result = self._execute_registry_tool(
            "TaskStop",
            {
                "task_id": task_id,
            },
        )
        return result.to_display_string()

    def format_sessions(self, *, limit: int = 20) -> str:
        sessions = self.session_manager.list_sessions(limit=limit)
        if not sessions:
            return "No S4Code sessions found."
        lines = []
        for item in sessions:
            marker = "*" if item.session_id == self.session_id else "-"
            updated = item.updated_at.isoformat(timespec="seconds") if item.updated_at is not None else "-"
            lines.append(
                f"{marker} {item.session_id} | {item.title} | {item.model or '-'} | "
                f"{item.permission_mode or '-'} | {updated} | {item.project_root or '-'}"
            )
        return "\n".join(lines)

    def format_config(self) -> str:
        return dump_settings_yaml(self.settings)

    def format_tools(self) -> str:
        specs = sorted(self.registry.list_tool_specs(), key=lambda item: item.name.lower())
        if not specs:
            return "No tools registered."
        lines: list[str] = []
        for spec in specs:
            flags: list[str] = []
            if spec.read_only:
                flags.append("read-only")
            if spec.requires_confirmation:
                flags.append("confirm")
            if spec.destructive:
                flags.append("destructive")
            if spec.visibility_scope != "resident":
                flags.append(spec.visibility_scope)
            if spec.side_effect_level != "none":
                flags.append(f"side={spec.side_effect_level}")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"{spec.name}{suffix}: {spec.description}")
        return "\n".join(lines)

    def format_models(self) -> str:
        lines = [
            f"Active profile: {self.settings.active_model_profile}",
            f"Current provider: {self.settings.llm.provider}",
            f"Current model: {self.settings.llm.model}",
            "",
            "Profiles:",
        ]
        for name, profile in self.settings.model_profiles.items():
            marker = "*" if name == self.settings.active_model_profile else "-"
            lines.append(f"{marker} {name}: {profile.provider} / {profile.model}")
        lines.append("")
        lines.append("Usage: /model <profile-name|literal-model>")
        return "\n".join(lines)

    def format_context(self) -> str:
        return json.dumps(self.agent.get_context_usage(), ensure_ascii=False, indent=2)

    def get_restore_report(self) -> Optional[dict[str, Any]]:
        report = self.bundle.restore_report
        if report is None:
            getter = getattr(self.agent, "get_last_restore_report", None)
            if callable(getter):
                report = getter()
                self.bundle.restore_report = report
        if report is None:
            return None
        if hasattr(report, "to_dict"):
            return dict(report.to_dict())
        return dict(report)

    def summarize_restore_report(self, *, detailed: bool = False) -> str:
        report = self.get_restore_report()
        if report is None:
            return ""
        lines = [
            f"Restore status: {report.get('status') or 'restored'}",
            f"Execution context restored: {bool(report.get('executionContextRestored'))}",
        ]
        missing_tools = list(report.get("missingTools") or [])
        missing_skills = list(report.get("missingSkills") or [])
        issues = list(report.get("issues") or [])
        if missing_tools:
            lines.append(f"Missing tools: {', '.join(str(item) for item in missing_tools)}")
        if missing_skills:
            lines.append(f"Missing skills: {', '.join(str(item) for item in missing_skills)}")
        if issues:
            lines.append(f"Issues: {len(issues)}")
        components = dict(report.get("components") or {})
        degraded_components = [
            f"{name}={payload.get('status') or 'unknown'}"
            for name, payload in components.items()
            if str(payload.get("status") or "restored") != "restored"
        ]
        if degraded_components:
            lines.append(f"Components: {', '.join(degraded_components)}")
        if detailed and issues:
            for issue in issues[:5]:
                severity = str(issue.get("severity") or "warning").upper()
                component = str(issue.get("component") or "restore")
                message = str(issue.get("message") or "").strip()
                lines.append(f"- {severity} {component}: {message}")
            hidden = len(issues) - 5
            if hidden > 0:
                lines.append(f"... {hidden} more restore issue(s)")
        return "\n".join(lines)

    def format_restore_report(self) -> str:
        report = self.get_restore_report()
        if report is None:
            return "No restore report for the current session."
        return json.dumps(report, ensure_ascii=False, indent=2)

    def get_pending_interaction(self) -> Optional[dict[str, Any]]:
        payload = self.agent.get_last_tool_interrupt()
        if payload is None:
            return None
        return dict(payload)

    def format_pending_interaction(self) -> str:
        payload = self.get_pending_interaction()
        if payload is None:
            return "No pending interaction."
        return self._format_pending_payload(payload)

    def _format_pending_payload(self, payload: dict[str, Any]) -> str:
        metadata = dict(payload.get("metadata") or {})
        interaction_type = str(metadata.get("interaction_type") or "confirmation")
        lines = [
            f"status: {payload.get('status')}",
            f"type: {interaction_type}",
        ]
        tool_name = str(payload.get("tool_name") or "").strip()
        if tool_name:
            lines.append(f"tool: {tool_name}")
        message = str(payload.get("message") or "").strip()
        if message:
            lines.append(f"message: {message}")

        if interaction_type == "ask_user_question":
            questions = list(metadata.get("questions") or [])
            if questions:
                lines.append("")
                lines.append("questions:")
                for index, item in enumerate(questions, start=1):
                    header = str(item.get("header") or f"Question {index}").strip()
                    question = str(item.get("question") or "").strip()
                    lines.append(f"  {index}. {header}")
                    if question:
                        lines.append(f"     {question}")
                    for option in list(item.get("options") or []):
                        label = str(option.get("label") or "").strip()
                        description = str(option.get("description") or "").strip()
                        bullet = f"     - {label}" if label else "     - option"
                        if description:
                            bullet += f": {description}"
                        lines.append(bullet)
            lines.append("")
            lines.append("reply with: /answer <text>")
            lines.append("or cancel with: /deny [reason]")
            return "\n".join(lines)

        if metadata.get("reason"):
            lines.append(f"reason: {metadata.get('reason')}")
        allowed_actions = list(metadata.get("allowedActions") or [])
        if allowed_actions:
            lines.append("allowed_actions:")
            lines.extend(f"  - {item}" for item in allowed_actions)
        allowed_prompts = list(metadata.get("allowedPrompts") or [])
        if allowed_prompts:
            lines.append("allowed_prompts:")
            for item in allowed_prompts:
                tool = str(item.get("tool") or "tool").strip()
                prompt = str(item.get("prompt") or "").strip()
                if prompt:
                    lines.append(f"  - {tool}: {prompt}")
                else:
                    lines.append(f"  - {tool}")
        tool_args = payload.get("tool_args") or {}
        if isinstance(tool_args, dict) and tool_args:
            lines.append("tool_args:")
            lines.append(json.dumps(tool_args, ensure_ascii=False, indent=2))
        lines.append("")
        lines.append("confirm with: /confirm [note] or /confirm remember")
        lines.append("deny with: /deny [reason] or /deny remember")
        return "\n".join(lines)

    @staticmethod
    def _answer_requests_permission_remember(answer: str) -> bool:
        normalized = str(answer or "").strip().lower()
        if not normalized:
            return False
        tokens = {token.strip(" ,.;:") for token in normalized.split()}
        return bool(tokens & {"remember", "remember-session", "allow-session", "deny-session"})

    def _matcher_from_pending_tool_args(self, tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
        matcher: dict[str, Any] = {}
        paths: list[str] = []
        for key in ("file_path", "path", "notebook_path", "directory", "cwd", "workspace_root"):
            value = str(tool_args.get(key) or "").strip()
            if value:
                paths.append(value)
        if paths:
            matcher["path_prefixes"] = sorted(set(paths))

        command = str(tool_args.get("command") or "").strip()
        if command:
            matcher["command_prefixes"] = [command]

        hosts: list[str] = []
        for key in ("url", "uri", "endpoint"):
            raw = str(tool_args.get(key) or "").strip()
            if not raw:
                continue
            host = urlparse(raw).netloc or raw.split("/", 1)[0]
            if host:
                hosts.append(host)
        if hosts:
            matcher["hosts"] = sorted(set(hosts))

        server = str(tool_args.get("server") or tool_args.get("mcp_server") or "").strip()
        if server:
            matcher["mcp_servers"] = [server]

        if tool_name == "Bash" and command:
            return {"command_prefixes": [command]}
        return matcher

    def remember_pending_permission_rule(self, payload: dict[str, Any], *, behavior: str) -> Optional[str]:
        tool_name = str(payload.get("tool_name") or "").strip()
        if not tool_name:
            return None
        tool_args = payload.get("tool_args") or {}
        if not isinstance(tool_args, dict):
            tool_args = {}
        matcher = self._matcher_from_pending_tool_args(tool_name, tool_args)
        rule = PermissionRule(
            tool_name=tool_name,
            behavior=PermissionBehavior(behavior),
            matcher=matcher,
            source="session",
            description="Remembered from pending interaction.",
        )
        self.agent.add_permission_rule(rule, source="session")
        self._record_permission_history(
            "pending_remembered",
            {
                "behavior": behavior,
                "tool": tool_name,
                "matcher": matcher,
            },
        )
        self._persist_permission_state()
        self.ensure_autosave()
        scope = json.dumps(matcher, ensure_ascii=False, sort_keys=True) if matcher else "all matching calls"
        return f"Remembered permission rule: {behavior} {tool_name} ({scope})"

    def _resolve_interaction_result_text(
        self,
        payload: dict[str, Any],
        *,
        action: str,
        answer: str = "",
    ) -> tuple[str, Any]:
        metadata = dict(payload.get("metadata") or {})
        interaction_type = str(metadata.get("interaction_type") or "")
        tool_name = str(payload.get("tool_name") or "")
        tool_args = dict(payload.get("tool_args") or {})
        if interaction_type == "ask_user_question":
            if action == "deny":
                return "The user declined to answer the structured question.", None
            answer_text = answer.strip()
            if not answer_text:
                raise ValueError("A pending AskUserQuestion interaction requires /answer <text>.")
            return (
                "User provided the following answer for the structured question:\n"
                f"{answer_text}",
                None,
            )
        if interaction_type == "enter_plan_mode":
            if action == "deny":
                return "The user declined the request to enter plan mode.", None
            allowed_actions = list(metadata.get("allowedActions") or [])
            self.agent.enter_plan_mode(allowed_actions=allowed_actions)
            return (
                f"S4Code entered plan mode. allowed_actions={allowed_actions or []}",
                None,
            )
        if interaction_type == "exit_plan_mode":
            if action == "deny":
                return "The user declined the request to exit plan mode.", None
            permission_mode = self.settings.product.permission_mode
            self.agent.exit_plan_mode(permission_mode=permission_mode)
            return (
                f"S4Code exited plan mode and restored permission mode to {permission_mode}.",
                None,
            )
        if action == "deny":
            denied_reason = answer.strip() or "No reason provided."
            return (
                f"The user denied execution of tool '{tool_name}'. Reason: {denied_reason}",
                None,
            )
        result = self.registry.execute_confirmed_tool_result(
            tool_name,
            tool_args,
            permission_context=self.agent.permission_context,
            permission_engine=self.agent.permission_engine,
        )
        return result.to_display_string(), getattr(result, "ephemeral_context", None)

    async def stream_resolve_pending_interaction(
        self,
        *,
        action: str,
        answer: str = "",
        max_iter: int = 20,
    ) -> AsyncGenerator[dict[str, Any], None]:
        payload = self.get_pending_interaction()
        if payload is None:
            yield {"type": "system_notice", "content": "No pending interaction."}
            return
        remember_notice = None
        if action in {"approve", "deny"} and self._answer_requests_permission_remember(answer):
            behavior = "allow" if action == "approve" else "deny"
            remember_notice = self.remember_pending_permission_rule(payload, behavior=behavior)
        content, ephemeral_context = self._resolve_interaction_result_text(
            payload,
            action=action,
            answer=answer,
        )
        self.agent.resolve_last_tool_interrupt(
            content=content,
            ephemeral_context=ephemeral_context,
            commit_pending_step=True,
        )
        notice = {
            "approve": "User confirmed the pending interaction. Resuming execution.",
            "deny": "User denied the pending interaction. Resuming execution with the denial result.",
            "answer": "User answered the pending interaction. Resuming execution.",
        }[action]
        if remember_notice:
            notice = f"{notice}\n{remember_notice}"
        yield {
            "type": "interaction_resolved",
            "content": notice,
            "payload": payload,
        }
        async for event in self.agent.astream_invoke_with_tool(
            "[resume pending interaction]",
            max_iter=max_iter,
            resume_from_history=True,
            trace_query="[resume_pending_tool_interrupt]",
        ):
            yield dict(event)
        self.ensure_autosave()

    def format_cost(self) -> str:
        payload = {
            "observability": self.agent.get_observability_summary(),
            "recentEvents": self.agent.get_recent_observability_events(limit=10),
            "traceSummary": self.agent.get_trace_summary(limit_turns=5),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def format_trace(self, *, limit_turns: int = 5) -> str:
        return json.dumps(
            self.agent.get_trace_summary(limit_turns=limit_turns),
            ensure_ascii=False,
            indent=2,
        )

    def format_recent_events(self, *, limit: int = 20, event_type: Optional[str] = None) -> str:
        return json.dumps(
            self.agent.get_recent_observability_events(limit=limit, event_type=event_type),
            ensure_ascii=False,
            indent=2,
        )

    def format_files(self, relative_path: str = ".", *, limit: int = 200) -> str:
        files = self.project.list_files(relative_path, limit=limit)
        if not files:
            return f"No files found under {relative_path!r}."
        return "\n".join(files)

    def format_diff(self, target: Optional[str] = None) -> str:
        return self.project.get_diff(target=target)

    def format_tasks(self, *, limit: int = 20) -> str:
        tasks = self.bundle.task_service.list_tasks(limit=limit)
        background_tasks = self._get_background_task_snapshots(limit=limit)
        if not tasks and not background_tasks:
            return "No tasks yet."
        lines: list[str] = []
        if tasks:
            lines.append("Structured Tasks:")
            lines.extend(
                f"- {task.task_id} | {task.status.value} | {task.title}"
                for task in tasks
            )
        if background_tasks:
            if lines:
                lines.append("")
            lines.append("Background Tasks:")
            for item in background_tasks:
                command = self._format_command_value(item.get("command")).replace("\n", " ").strip()
                if len(command) > 120:
                    command = command[:117].rstrip() + "..."
                duration = item.get("duration_seconds")
                duration_text = f" | {float(duration):.1f}s" if isinstance(duration, (int, float)) else ""
                lines.append(
                    f"- {item.get('task_id') or '-'} | {item.get('status') or '-'} | "
                    f"rc={item.get('return_code')}{duration_text} | {command or item.get('cwd') or '-'}"
                )
                stdout_tail = str(item.get("stdout_tail") or "").strip()
                stderr_tail = str(item.get("stderr_tail") or "").strip()
                if stdout_tail:
                    lines.append(f"  stdout: {self._tail_text(stdout_tail.replace(chr(10), ' '), max_chars=180)}")
                if stderr_tail:
                    lines.append(f"  stderr: {self._tail_text(stderr_tail.replace(chr(10), ' '), max_chars=180)}")
        return "\n".join(lines)

    def format_agents(self, *, limit: int = 20) -> str:
        runtime = self.agent.agent_runtime
        if runtime is None:
            return "Agent runtime is not enabled."
        handles = runtime.list_handles(limit=limit)
        if not handles:
            return "No agents running."
        return "\n".join(
            f"{handle.agent_id} | {handle.status} | {handle.name or '-'} | "
            f"task={handle.execution_context.current_task_id or '-'} | "
            f"output={handle.output_file or '-'}"
            for handle in handles
        )

    def format_runtime_panel(self) -> str:
        return self._format_runtime_snapshot(self.get_runtime_snapshot_payload())

    def _get_mcp_managers(self) -> dict[str, Any]:
        surfaces = self.registry.list_runtime_surfaces("mcp_manager")
        if not isinstance(surfaces, dict):
            return {}
        return dict(surfaces)

    def _get_configured_mcp_servers(self) -> dict[str, Any]:
        configured: dict[str, Any] = {}
        for server in list(self.settings.mcp_servers or []):
            name = str(getattr(server, "name", "") or "").strip()
            if name:
                configured[name] = server
        return configured

    def _get_mcp_known_server_names(self) -> list[str]:
        configured = self._get_configured_mcp_servers()
        ordered_names = list(configured.keys())
        for name in sorted(self._get_mcp_managers().keys()):
            if name not in configured:
                ordered_names.append(name)
        return ordered_names

    def _resolve_mcp_server_name(self, server_name: str) -> str:
        normalized = str(server_name or "").strip()
        if not normalized:
            raise ValueError("Usage: /mcp status <server-name>")
        configured = self._get_configured_mcp_servers()
        managers = self._get_mcp_managers()
        if normalized in managers or normalized in configured:
            return normalized
        lowered = normalized.lower()
        for name in self._get_mcp_known_server_names():
            if str(name).lower() == lowered:
                return name
        available = ", ".join(self._get_mcp_known_server_names())
        if available:
            raise ValueError(f"Unknown MCP server: {normalized}. Available: {available}")
        raise ValueError(f"Unknown MCP server: {normalized}")

    def _get_mcp_server_settings(self, server_name: str) -> Any:
        normalized = self._resolve_mcp_server_name(server_name)
        return self._get_configured_mcp_servers().get(normalized)

    def _get_mcp_manager(self, server_name: str, *, allow_missing: bool = False) -> Any:
        normalized = self._resolve_mcp_server_name(server_name)
        managers = self._get_mcp_managers()
        if normalized in managers:
            return managers[normalized]
        if allow_missing:
            return None
        server_settings = self._get_configured_mcp_servers().get(normalized)
        if server_settings is not None and not bool(server_settings.enabled):
            raise ValueError(f"MCP server '{normalized}' is configured but disabled.")
        raise ValueError(f"MCP server '{normalized}' is configured but not registered in the runtime.")

    @staticmethod
    def _mcp_snapshot_counts(snapshot: Any) -> tuple[int, int, int]:
        tools = list(getattr(snapshot, "tools", []) or [])
        resources = list(getattr(snapshot, "resources", []) or [])
        prompts = list(getattr(snapshot, "prompts", []) or [])
        return (len(tools), len(resources), len(prompts))

    @staticmethod
    def _mcp_connection_state(manager: Any) -> dict[str, Any]:
        getter = getattr(manager, "connection_state", None)
        if callable(getter):
            state = getter()
            if isinstance(state, dict):
                return dict(state)
        connection_manager = getattr(manager, "connection_manager", None)
        describe_state = getattr(connection_manager, "describe_state", None)
        if callable(describe_state):
            state = describe_state()
            if isinstance(state, dict):
                return dict(state)
        return {}

    @staticmethod
    def _mcp_transport_summary(state: dict[str, Any]) -> str:
        transport = state.get("transport")
        if isinstance(transport, dict):
            parts = []
            transport_type = str(transport.get("transport_type") or transport.get("transportType") or "").strip()
            if transport_type:
                parts.append(transport_type)
            command = str(transport.get("command") or "").strip()
            if command:
                parts.append(command)
            url = str(transport.get("url") or transport.get("endpoint") or "").strip()
            if url:
                parts.append(url)
            if parts:
                return " | ".join(parts)
        return "-"

    def get_mcp_status_payload(
        self,
        *,
        refresh: bool = False,
        include_capabilities: bool = True,
    ) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        managers = self._get_mcp_managers()
        configured = self._get_configured_mcp_servers()
        for name in self._get_mcp_known_server_names():
            manager = managers.get(name)
            server_settings = configured.get(name)
            snapshot = None
            snapshot_error = None
            snapshot_fn = getattr(manager, "snapshot", None) if manager is not None else None
            if include_capabilities and callable(snapshot_fn):
                try:
                    snapshot = snapshot_fn(refresh=refresh)
                except Exception as exc:
                    snapshot_error = f"{type(exc).__name__}: {exc}"
            state = self._mcp_connection_state(manager) if manager is not None else {}
            tools_count, resources_count, prompts_count = self._mcp_snapshot_counts(snapshot)
            status = str(state.get("status") or "").strip()
            if not status:
                if server_settings is not None and not bool(server_settings.enabled):
                    status = "disabled"
                elif manager is None:
                    status = "unregistered"
                else:
                    status = "unknown"
            payloads.append(
                {
                    "server_name": name,
                    "source_identifier": str(getattr(manager, "source_identifier", "") or ""),
                    "registry_server_name": str(getattr(manager, "registry_server_name", name) or name),
                    "status": status,
                    "retry_count": int(state.get("retryCount") or 0),
                    "last_operation": str(state.get("lastOperation") or "").strip(),
                    "last_error": str(state.get("lastError") or snapshot_error or "").strip(),
                    "last_error_type": str(state.get("lastErrorType") or "").strip(),
                    "last_connected_at": state.get("lastConnectedAt"),
                    "last_disconnected_at": state.get("lastDisconnectedAt"),
                    "transport": state.get("transport") if isinstance(state.get("transport"), dict) else {},
                    "transport_summary": self._mcp_transport_summary(state),
                    "enabled": bool(server_settings.enabled) if server_settings is not None else True,
                    "persist_connection": bool(
                        getattr(getattr(manager, "connection_manager", None), "persist_connection", False)
                        if manager is not None
                        else bool(getattr(server_settings, "persist_connection", False))
                    ),
                    "include_resources": bool(
                        getattr(manager, "include_resources", False)
                        if manager is not None
                        else bool(getattr(server_settings, "include_resources", False))
                    ),
                    "tool_count": tools_count,
                    "resource_count": resources_count,
                    "prompt_count": prompts_count,
                    "tool_names": [
                        str(item.get("name") or "").strip()
                        for item in list(getattr(snapshot, "tools", []) or [])
                        if str(item.get("name") or "").strip()
                    ],
                    "resource_names": [
                        str(item.get("uri") or item.get("name") or "").strip()
                        for item in list(getattr(snapshot, "resources", []) or [])
                        if str(item.get("uri") or item.get("name") or "").strip()
                    ],
                    "prompt_names": [
                        str(item.get("name") or "").strip()
                        for item in list(getattr(snapshot, "prompts", []) or [])
                        if str(item.get("name") or "").strip()
                    ],
                }
            )
        return payloads

    def get_mcp_summary_payload(self) -> dict[str, Any]:
        if not bool(self.settings.product.enable_mcp):
            return {
                "enabled": False,
                "configured": 0,
                "connected": 0,
                "disabled": 0,
                "unavailable": 0,
                "issues": [],
            }
        payload = self.get_mcp_status_payload(include_capabilities=False)
        connected = 0
        disabled = 0
        unavailable = 0
        issues: list[dict[str, str]] = []
        for item in payload:
            status = str(item.get("status") or "unknown").strip() or "unknown"
            if status == "connected":
                connected += 1
                continue
            if status == "disabled":
                disabled += 1
                continue
            unavailable += 1
            issues.append(
                {
                    "server_name": str(item.get("server_name") or "").strip(),
                    "status": status,
                    "last_error": str(item.get("last_error") or "").strip(),
                }
            )
        return {
            "enabled": True,
            "configured": len(payload),
            "connected": connected,
            "disabled": disabled,
            "unavailable": unavailable,
            "issues": issues,
        }

    def connect_mcp(self, server_name: Optional[str] = None) -> str:
        managers = self._get_mcp_managers()
        configured = self._get_configured_mcp_servers()
        target_names = (
            self._get_mcp_known_server_names()
            if not server_name or str(server_name).strip().lower() in {"all", "*"}
            else [self._resolve_mcp_server_name(str(server_name).strip())]
        )
        if not target_names:
            return "No MCP servers configured."
        lines: list[str] = []
        for name in target_names:
            manager = managers.get(name)
            server_settings = configured.get(name)
            if manager is None:
                if server_settings is not None and not bool(server_settings.enabled):
                    lines.append(f"{name} | disabled")
                else:
                    lines.append(f"{name} | unregistered")
                continue
            connect = getattr(manager, "connect", None)
            if not callable(connect):
                lines.append(f"{name} | connect unsupported")
                continue
            try:
                connect()
                lines.append(f"{name} | connected")
            except Exception as exc:
                lines.append(f"{name} | error | {type(exc).__name__}: {exc}")
        return "\n".join(lines)

    def disconnect_mcp(self, server_name: Optional[str] = None) -> str:
        managers = self._get_mcp_managers()
        configured = self._get_configured_mcp_servers()
        target_names = (
            self._get_mcp_known_server_names()
            if not server_name or str(server_name).strip().lower() in {"all", "*"}
            else [self._resolve_mcp_server_name(str(server_name).strip())]
        )
        if not target_names:
            return "No MCP servers configured."
        lines: list[str] = []
        for name in target_names:
            manager = managers.get(name)
            server_settings = configured.get(name)
            if manager is None:
                if server_settings is not None and not bool(server_settings.enabled):
                    lines.append(f"{name} | disabled")
                else:
                    lines.append(f"{name} | unregistered")
                continue
            close = getattr(manager, "close", None)
            if not callable(close):
                lines.append(f"{name} | disconnect unsupported")
                continue
            try:
                close()
                lines.append(f"{name} | disconnected")
            except Exception as exc:
                lines.append(f"{name} | error | {type(exc).__name__}: {exc}")
        return "\n".join(lines)

    def refresh_mcp(self, server_name: Optional[str] = None) -> str:
        managers = self._get_mcp_managers()
        configured = self._get_configured_mcp_servers()
        target_names = (
            self._get_mcp_known_server_names()
            if not server_name or str(server_name).strip().lower() in {"all", "*"}
            else [self._resolve_mcp_server_name(str(server_name).strip())]
        )
        if not target_names:
            return "No MCP servers configured."
        lines: list[str] = []
        for name in target_names:
            manager = managers.get(name)
            server_settings = configured.get(name)
            if manager is None:
                if server_settings is not None and not bool(server_settings.enabled):
                    lines.append(f"{name} | disabled")
                else:
                    lines.append(f"{name} | unregistered")
                continue
            try:
                connect = getattr(manager, "connect", None)
                if callable(connect):
                    connect()
                snapshot_fn = getattr(manager, "snapshot", None)
                snapshot = snapshot_fn(refresh=True) if callable(snapshot_fn) else None
                tool_count, resource_count, prompt_count = self._mcp_snapshot_counts(snapshot)
                lines.append(
                    f"{name} | refreshed | tools={tool_count} resources={resource_count} prompts={prompt_count}"
                )
            except Exception as exc:
                lines.append(f"{name} | error | {type(exc).__name__}: {exc}")
        return "\n".join(lines)

    def format_mcp_server_detail(self, server_name: str, *, refresh: bool = False) -> str:
        resolved_name = self._resolve_mcp_server_name(server_name)
        manager = self._get_mcp_manager(resolved_name, allow_missing=True)
        server_settings = self._get_mcp_server_settings(resolved_name)
        snapshot = None
        snapshot_error = ""
        snapshot_fn = getattr(manager, "snapshot", None)
        if callable(snapshot_fn):
            try:
                snapshot = snapshot_fn(refresh=refresh)
            except Exception as exc:
                snapshot_error = f"{type(exc).__name__}: {exc}"
        state = self._mcp_connection_state(manager)
        tool_count, resource_count, prompt_count = self._mcp_snapshot_counts(snapshot)
        status = str(state.get("status") or "").strip()
        if not status:
            if server_settings is not None and not bool(server_settings.enabled):
                status = "disabled"
            elif manager is None:
                status = "unregistered"
            else:
                status = "unknown"
        lines = [
            f"Server: {getattr(manager, 'registry_server_name', resolved_name) or resolved_name}",
            f"Source: {getattr(manager, 'source_identifier', getattr(server_settings, 'server_source', '-')) or '-'}",
            f"Enabled: {bool(getattr(server_settings, 'enabled', True))}",
            f"Status: {status}",
            (
                f"Persist Connection: {bool(getattr(server_settings, 'persist_connection', False))}"
                if manager is None
                else f"Persist Connection: {bool(getattr(getattr(manager, 'connection_manager', None), 'persist_connection', False))}"
            ),
            f"Transport: {self._mcp_transport_summary(state)}",
            f"Last Operation: {state.get('lastOperation') or '-'}",
            f"Last Connected: {self._format_epoch(state.get('lastConnectedAt'))}",
            f"Last Disconnected: {self._format_epoch(state.get('lastDisconnectedAt'))}",
            f"Capabilities: tools={tool_count} resources={resource_count} prompts={prompt_count}",
        ]
        if manager is None:
            if server_settings is not None and not bool(server_settings.enabled):
                lines.append("Runtime: configured but disabled")
            else:
                lines.append("Runtime: configured but not registered")
        if snapshot_error:
            lines.append(f"Snapshot Error: {snapshot_error}")
        last_error = str(state.get("lastError") or "").strip()
        if last_error:
            lines.append(f"Last Error: {last_error}")
        last_error_type = str(state.get("lastErrorType") or "").strip()
        if last_error_type:
            lines.append(f"Last Error Type: {last_error_type}")
        tool_names = [
            str(item.get("name") or "").strip()
            for item in list(getattr(snapshot, "tools", []) or [])
            if str(item.get("name") or "").strip()
        ]
        if tool_names:
            lines.append("")
            lines.append("Tools:")
            lines.extend(f"- {name}" for name in tool_names[:20])
            if len(tool_names) > 20:
                lines.append(f"... {len(tool_names) - 20} more tool(s)")
        resource_names = [
            str(item.get("uri") or item.get("name") or "").strip()
            for item in list(getattr(snapshot, "resources", []) or [])
            if str(item.get("uri") or item.get("name") or "").strip()
        ]
        if resource_names:
            lines.append("")
            lines.append("Resources:")
            lines.extend(f"- {name}" for name in resource_names[:20])
            if len(resource_names) > 20:
                lines.append(f"... {len(resource_names) - 20} more resource(s)")
        prompt_names = [
            str(item.get("name") or "").strip()
            for item in list(getattr(snapshot, "prompts", []) or [])
            if str(item.get("name") or "").strip()
        ]
        if prompt_names:
            lines.append("")
            lines.append("Prompts:")
            lines.extend(f"- {name}" for name in prompt_names[:20])
            if len(prompt_names) > 20:
                lines.append(f"... {len(prompt_names) - 20} more prompt(s)")
        return "\n".join(lines)

    def format_mcp_tools(self, server_name: str) -> str:
        resolved_name = self._resolve_mcp_server_name(server_name)
        manager = self._get_mcp_manager(resolved_name, allow_missing=True)
        if manager is None:
            server_settings = self._get_mcp_server_settings(resolved_name)
            if server_settings is not None and not bool(server_settings.enabled):
                return f"MCP server '{resolved_name}' is configured but disabled."
            return f"MCP server '{resolved_name}' is configured but not registered in the runtime."
        snapshot_fn = getattr(manager, "snapshot", None)
        snapshot = snapshot_fn(refresh=True) if callable(snapshot_fn) else None
        tool_names = [
            str(item.get("name") or "").strip()
            for item in list(getattr(snapshot, "tools", []) or [])
            if str(item.get("name") or "").strip()
        ]
        if not tool_names:
            return f"No MCP tools found for {resolved_name}."
        return "\n".join(tool_names)

    def format_mcp_resources(self, server_name: str) -> str:
        resolved_name = self._resolve_mcp_server_name(server_name)
        manager = self._get_mcp_manager(resolved_name, allow_missing=True)
        if manager is None:
            server_settings = self._get_mcp_server_settings(resolved_name)
            if server_settings is not None and not bool(server_settings.enabled):
                return f"MCP server '{resolved_name}' is configured but disabled."
            return f"MCP server '{resolved_name}' is configured but not registered in the runtime."
        snapshot_fn = getattr(manager, "snapshot", None)
        snapshot = snapshot_fn(refresh=True) if callable(snapshot_fn) else None
        resources = [
            str(item.get("uri") or item.get("name") or "").strip()
            for item in list(getattr(snapshot, "resources", []) or [])
            if str(item.get("uri") or item.get("name") or "").strip()
        ]
        if not resources:
            return f"No MCP resources found for {resolved_name}."
        return "\n".join(resources)

    @staticmethod
    def _format_command_value(value: Any) -> str:
        if isinstance(value, (list, tuple)):
            return " ".join(str(item) for item in value)
        return str(value or "")

    @staticmethod
    def _format_epoch(value: Any) -> str:
        if not isinstance(value, (int, float)):
            return "-"
        try:
            return datetime.fromtimestamp(float(value)).isoformat(timespec="seconds")
        except Exception:
            return "-"

    def _format_runtime_snapshot(self, payload: dict[str, Any]) -> str:
        worktree = dict(payload.get("worktree") or {})
        agents = list(payload.get("agents") or [])
        tasks = list(payload.get("tasks") or [])
        background_tasks = list(payload.get("background_tasks") or [])
        context = dict(payload.get("context") or {})
        active_worktree = worktree.get("active") or {}
        lines = [
            f"Runtime snapshot: {payload.get('generated_at') or '-'}",
            f"Session: {self.session_id} | checkpoints={len(self._checkpoints)}",
            "",
            "Worktree:",
        ]
        if active_worktree:
            lines.append(f"- active: {active_worktree.get('branch') or '-'} @ {active_worktree.get('path') or '-'}")
        else:
            lines.append("- active: none")
        lines.append(f"- managed: {len(list(worktree.get('managed') or []))}")
        lines.extend(["", "Agents:"])
        if agents:
            for agent in agents:
                lines.append(
                    f"- {agent.get('agent_id') or '-'} | {agent.get('status') or '-'} | "
                    f"{agent.get('name') or '-'} | task={agent.get('task_id') or '-'}"
                )
        else:
            lines.append("- none")
        lines.extend(["", "Structured Tasks:"])
        if tasks:
            for task in tasks:
                lines.append(f"- {task.get('task_id') or '-'} | {task.get('status') or '-'} | {task.get('title') or '-'}")
        else:
            lines.append("- none")
        lines.extend(["", "Background Tasks:"])
        if background_tasks:
            for task in background_tasks:
                command = self._format_command_value(task.get("command")).replace("\n", " ").strip()
                if len(command) > 120:
                    command = command[:117].rstrip() + "..."
                duration = task.get("duration_seconds")
                duration_text = f" | {float(duration):.1f}s" if isinstance(duration, (int, float)) else ""
                lines.append(
                    f"- {task.get('task_id') or '-'} | {task.get('status') or '-'} | "
                    f"rc={task.get('return_code')}{duration_text} | {command or task.get('cwd') or '-'}"
                )
                stdout_tail = str(task.get("stdout_tail") or "").strip()
                stderr_tail = str(task.get("stderr_tail") or "").strip()
                if stdout_tail:
                    lines.append(f"  stdout tail: {self._tail_text(stdout_tail.replace(chr(10), ' '), max_chars=240)}")
                if stderr_tail:
                    lines.append(f"  stderr tail: {self._tail_text(stderr_tail.replace(chr(10), ' '), max_chars=240)}")
        else:
            lines.append("- none")
        if context:
            lines.extend(
                [
                    "",
                    "Context:",
                    (
                        f"- used={context.get('used_tokens', '?')} "
                        f"remaining={context.get('remaining_tokens', '?')} "
                        f"max={context.get('max_tokens', '?')}"
                    ),
                ]
            )
        return "\n".join(lines)

    def format_mcp(self) -> str:
        payload = self.get_mcp_status_payload()
        if not payload:
            return "No MCP servers configured."
        lines: list[str] = []
        for item in payload:
            line = (
                f"{item.get('server_name')} | {item.get('status')} | "
                f"tools={item.get('tool_count', 0)} "
                f"resources={item.get('resource_count', 0)} "
                f"prompts={item.get('prompt_count', 0)} | "
                f"persist={item.get('persist_connection')} | "
                f"{item.get('transport_summary') or '-'}"
            )
            last_error = str(item.get("last_error") or "").strip()
            if last_error:
                line += f" | error={last_error}"
            lines.append(line)
        lines.append("")
        lines.append("Usage: /mcp [list|status <server>|tools <server>|resources <server>|refresh [server]|connect [server]|disconnect [server]]")
        return "\n".join(lines)

    def format_hooks(self) -> str:
        hooks = getattr(self.agent.hook_manager, "hooks", [])
        if not hooks:
            return "No hooks installed."
        return "\n".join(f"{hook.name}" for hook in hooks)

    def format_doctor(self) -> str:
        payload = {
            "project": self.project.to_status_dict(),
            "status": json.loads(self.format_status()),
            "restoreReport": self.get_restore_report(),
            "lastCloseReport": self.get_last_close_report(),
            "startupIssues": list(self.bundle.startup_issues),
            "mcp": self.get_mcp_status_payload(),
            "skills": self.get_skill_choices(),
            "backgroundTasks": self._get_background_task_snapshots(limit=20),
            "tools": [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "readOnly": spec.read_only,
                    "requiresConfirmation": spec.requires_confirmation,
                    "destructive": spec.destructive,
                    "visibility": spec.visibility_scope,
                    "sideEffectLevel": spec.side_effect_level,
                }
                for spec in self.registry.list_tool_specs()
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def get_last_close_report(self) -> Optional[dict[str, Any]]:
        if self._last_close_report is None:
            getter = getattr(self.agent, "get_last_close_report", None)
            if callable(getter):
                report = getter()
                if isinstance(report, dict):
                    self._last_close_report = dict(report)
        return dict(self._last_close_report) if isinstance(self._last_close_report, dict) else None

    def get_startup_notices(self) -> list[dict[str, str]]:
        notices: list[dict[str, str]] = []
        mcp_summary = self.get_mcp_summary_payload()
        if mcp_summary.get("enabled") and int(mcp_summary.get("configured") or 0) > 0:
            configured = int(mcp_summary.get("configured") or 0)
            connected = int(mcp_summary.get("connected") or 0)
            disabled = int(mcp_summary.get("disabled") or 0)
            unavailable = int(mcp_summary.get("unavailable") or 0)
            lines = [
                (
                    f"Configured {configured} MCP server(s): "
                    f"{connected} connected, {disabled} disabled, {unavailable} unavailable."
                )
            ]
            for item in list(mcp_summary.get("issues") or [])[:8]:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("server_name") or "").strip() or "-"
                status = str(item.get("status") or "unknown").strip() or "unknown"
                last_error = str(item.get("last_error") or "").strip()
                line = f"- {name}: {status}"
                if last_error:
                    line += f" | {last_error}"
                lines.append(line)
            lines.append("Use /mcp for details.")
            notices.append(
                {
                    "kind": "warning" if unavailable > 0 else "system",
                    "title": "MCP Startup",
                    "body": "\n".join(lines),
                }
            )
        if self.bundle.startup_issues:
            notices.append(
                {
                    "kind": "warning",
                    "title": "Startup Issues",
                    "body": "\n".join(f"- {issue}" for issue in self.bundle.startup_issues),
                }
            )
        restore_summary = self.summarize_restore_report(detailed=True)
        restore_report = self.get_restore_report()
        if restore_summary and (
            self.was_restored
            or (
                isinstance(restore_report, dict)
                and (
                    str(restore_report.get("status") or "restored") != "restored"
                    or bool(restore_report.get("issues"))
                )
            )
        ):
            kind = "warning"
            if isinstance(restore_report, dict) and str(restore_report.get("status") or "restored") == "restored":
                kind = "system"
            notices.append(
                {
                    "kind": kind,
                    "title": "Session Restored",
                    "body": restore_summary,
                }
            )
        return notices

    def build_review_prompt(self, target: Optional[str] = None) -> str:
        scope = target or "the current uncommitted diff"
        return (
            f"Review {scope} in this repository.\n"
            "Primary goal: identify bugs, behavioral regressions, risky assumptions, and missing tests.\n"
            "Output format:\n"
            "1. Findings first, ordered by severity.\n"
            "2. Use file paths and concrete reasoning.\n"
            "3. Keep summary short and secondary.\n"
            "Prefer git diff, code intelligence, and targeted file reads instead of broad speculation."
        )

    def build_commit_prompt(self) -> str:
        return (
            "Inspect the current git diff and produce one strong commit proposal.\n"
            "You must:\n"
            "- summarize the change set\n"
            "- suggest one conventional commit message\n"
            "- list any risks or follow-up items\n"
            "- do not execute git commit unless explicitly instructed later"
        )

    def close(self) -> dict[str, Any]:
        return self._close_bundle(mark_closed=True, record_report=True)
