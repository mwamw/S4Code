"""Central S4Code query engine."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from .command_registry import S4CommandRegistry
from .config import S4Settings, dump_settings_yaml, resolve_settings
from .easyagent_adapter import S4AgentBundle, build_agent_bundle
from .paths import S4Paths, get_s4_paths
from .project import ProjectContext
from .session import S4SessionManager


def _deep_merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


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
        self.sidebar_visible = bool(self.settings.ui.right_panel_open)
        if session_id is None and self.settings.product.session_auto_save:
            self.save_session(tolerate_failure=True)

    @property
    def agent(self):
        return self.bundle.agent

    @property
    def registry(self):
        return self.bundle.registry

    @property
    def was_restored(self) -> bool:
        return self._restored_session

    def _require_session_record(self, session_id: str) -> dict[str, Any]:
        record = self.session_manager.get_record(session_id)
        if record is None:
            raise ValueError(f"Session not found: {session_id}")
        return record

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
        self._restored_session = True
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
        self.sidebar_visible = bool(self.settings.ui.right_panel_open)
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

    def update_permission_mode(self, mode: str) -> str:
        self.agent.set_permission_mode(mode)
        self.settings.product.permission_mode = mode
        self.session_overrides.setdefault("product", {})["permission_mode"] = mode
        self.ensure_autosave()
        return f"Permission mode set to {mode}"

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

    def compact_history(self) -> str:
        changed = self.agent.compact_history()
        usage = self.agent.get_context_usage()
        compaction = dict(usage.get("compaction") or {})
        self.ensure_autosave()
        if changed:
            return (
                "Conversation compacted.\n"
                f"before={compaction.get('tokens_before', '?')} "
                f"after={compaction.get('tokens_after', '?')} "
                f"budget={compaction.get('max_tokens', '?')}"
            )
        return "Compaction not needed."

    def run_prompt(self, prompt: str, *, max_iter: int = 20) -> str:
        self._maybe_update_title(prompt)
        result = self.agent.invoke(prompt, max_iter=max_iter)
        self.ensure_autosave()
        return result

    async def stream_prompt(self, prompt: str, *, max_iter: int = 20) -> AsyncGenerator[dict[str, Any], None]:
        self._maybe_update_title(prompt)
        queue: asyncio.Queue[dict[str, Any] | object] = asyncio.Queue()
        sentinel = object()
        runtime_hook = self.bundle.runtime_notice_hook

        def _emit(event: dict[str, Any]) -> None:
            queue.put_nowait(dict(event))

        async def _produce() -> None:
            try:
                async for event in self.agent.astream_invoke_with_tool(prompt, max_iter=max_iter):
                    if runtime_hook is not None and runtime_hook.has_pending_compactions:
                        runtime_hook.flush_compaction_result(self.agent)
                    await queue.put(dict(event))
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
            await producer
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
        restore_report = self.get_restore_report()
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
            "agents": agent_count,
            "tasks": task_count,
            "toolCount": len(self.registry.get_tool_names()),
            "codeintelEnabled": self.settings.product.enable_codeintel,
            "mcpServers": list(self.registry.list_runtime_surfaces("mcp_manager").keys()),
            "context": self.agent.get_context_usage(),
            "startupIssues": list(self.bundle.startup_issues),
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

    def format_sidebar(self) -> str:
        permission_mode = getattr(getattr(self.agent, "permission_context", None), "mode", None).value
        agent_mode = self.agent.get_execution_mode().value
        handles = self.agent.agent_runtime.list_handles(limit=5) if self.agent.agent_runtime is not None else []
        tasks = self.bundle.task_service.list_tasks(limit=5)
        context_usage = self.agent.get_context_usage()
        restore_report = self.get_restore_report()
        restore_status = "-"
        restore_issue_count = 0
        if isinstance(restore_report, dict):
            restore_status = str(restore_report.get("status") or "-")
            restore_issue_count = len(list(restore_report.get("issues") or []))
        lines = [
            f"Project: {self.project.project_name}",
            f"Branch: {self.project.branch or '-'}",
            f"Profile: {self.settings.active_model_profile}",
            f"Model: {getattr(self.agent.llm, 'model', '-')}",
            f"Provider: {getattr(self.agent.llm, 'provider_name', '-')}",
            f"Mode: {agent_mode}",
            f"Permissions: {permission_mode}",
            f"Session: {self.session_id}",
            f"Tools: {len(self.registry.get_tool_names())}",
            f"Restore: {restore_status} ({restore_issue_count} issue(s))",
            "",
            "Context:",
            (
                f"- used={context_usage.get('used_tokens', '?')} "
                f"remaining={context_usage.get('remaining_tokens', '?')} "
                f"max={context_usage.get('max_tokens', '?')}"
            ),
            "",
            "Recent Tasks:",
        ]
        if tasks:
            for task in tasks[:5]:
                lines.append(f"- {task.task_id}: {task.title} [{task.status.value}]")
        else:
            lines.append("- none")
        lines.append("")
        lines.append("Agents:")
        if handles:
            for handle in handles[:5]:
                lines.append(f"- {handle.agent_id}: {handle.status}")
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
        lines.append("confirm with: /confirm [note]")
        lines.append("deny with: /deny [reason]")
        return "\n".join(lines)

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
        if not tasks:
            return "No tasks yet."
        return "\n".join(
            f"{task.task_id} | {task.status.value} | {task.title}"
            for task in tasks
        )

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

    def format_mcp(self) -> str:
        surfaces = self.registry.list_runtime_surfaces("mcp_manager")
        if not surfaces:
            return "No MCP servers configured."
        lines: list[str] = []
        for name, manager in surfaces.items():
            state = "unknown"
            connection_manager = getattr(manager, "connection_manager", None)
            if connection_manager is not None and hasattr(connection_manager, "describe_state"):
                state = connection_manager.describe_state()
            lines.append(f"{name} | {state}")
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
            "startupIssues": list(self.bundle.startup_issues),
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

    def get_startup_notices(self) -> list[dict[str, str]]:
        notices: list[dict[str, str]] = []
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
        return self.agent.close()
