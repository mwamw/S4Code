"""Central S4Code query engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from .command_registry import S4CommandRegistry
from .config import S4Settings, resolve_settings
from .easyagent_adapter import S4AgentBundle, build_agent_bundle
from .paths import S4Paths, get_s4_paths
from .project import ProjectContext
from .session import S4SessionManager


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
        self.session_overrides = dict(session_overrides or {})
        self.project = ProjectContext.detect(cwd)
        self.settings = resolve_settings(
            self.paths,
            project_root=self.project.project_root,
            session_overrides=self.session_overrides,
        )
        self.bundle: S4AgentBundle
        self.session_id = session_id or self.session_manager.new_session_id(self.project)
        self.title = f"{self.project.project_name} session"
        self.bundle = build_agent_bundle(
            settings=self.settings,
            project=self.project,
            paths=self.paths,
            session_store=self.session_manager.store,
            restore_session_id=session_id,
        )
        self.command_registry = S4CommandRegistry()
        self.sidebar_visible = False

    @property
    def agent(self):
        return self.bundle.agent

    @property
    def registry(self):
        return self.bundle.registry

    def ensure_autosave(self) -> None:
        if self.settings.product.session_auto_save:
            self.save_session()

    def save_session(self) -> None:
        metadata = self.session_manager.build_metadata(
            project=self.project,
            title=self.title,
            settings_payload=self.settings.model_dump(mode="python"),
            session_overrides=self.session_overrides,
        )
        self.agent.save_session(
            self.session_id,
            store=self.session_manager.store,
            metadata=metadata,
        )

    def resume_session(self, session_id: str) -> str:
        record = self.session_manager.get_record(session_id)
        if record is None:
            raise ValueError(f"Session not found: {session_id}")
        metadata = dict(record.get("metadata") or {})
        project_root = metadata.get("project_root") or str(self.project.project_root)
        self.project = ProjectContext.detect(project_root)
        self.session_overrides = dict(metadata.get("session_overrides") or {})
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
        self.title = str(metadata.get("title") or self.title)
        return f"Resumed session {session_id}"

    def update_model(self, model: str) -> str:
        self.agent.change_model(model=model)
        self.settings.llm.model = model
        self.session_overrides.setdefault("llm", {})["model"] = model
        self.ensure_autosave()
        return f"Model set to {model}"

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
        self.ensure_autosave()
        return "Conversation compacted." if changed else "Compaction not needed."

    def run_prompt(self, prompt: str, *, max_iter: int = 20) -> str:
        self._maybe_update_title(prompt)
        result = self.agent.invoke(prompt, max_iter=max_iter)
        self.ensure_autosave()
        return result

    async def stream_prompt(self, prompt: str, *, max_iter: int = 20) -> AsyncGenerator[dict[str, Any], None]:
        self._maybe_update_title(prompt)
        async for event in self.agent.astream_invoke_with_tool(prompt, max_iter=max_iter):
            yield dict(event)
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
        status = {
            "sessionId": self.session_id,
            "title": self.title,
            "projectRoot": str(self.project.project_root),
            "branch": self.project.branch,
            "model": getattr(self.agent.llm, "model", None),
            "provider": getattr(self.agent.llm, "provider_name", None),
            "executionMode": agent_mode,
            "permissionMode": getattr(getattr(self.agent, "permission_context", None), "mode", None).value,
            "agents": agent_count,
            "tasks": task_count,
            "codeintelEnabled": self.settings.product.enable_codeintel,
            "mcpServers": list(self.registry.list_runtime_surfaces("mcp_manager").keys()),
            "startupIssues": list(self.bundle.startup_issues),
        }
        return json.dumps(status, ensure_ascii=False, indent=2)

    def format_sidebar(self) -> str:
        permission_mode = getattr(getattr(self.agent, "permission_context", None), "mode", None).value
        agent_mode = self.agent.get_execution_mode().value
        handles = self.agent.agent_runtime.list_handles(limit=5) if self.agent.agent_runtime is not None else []
        tasks = self.bundle.task_service.list_tasks(limit=5)
        lines = [
            f"Project: {self.project.project_name}",
            f"Branch: {self.project.branch or '-'}",
            f"Model: {getattr(self.agent.llm, 'model', '-')}",
            f"Provider: {getattr(self.agent.llm, 'provider_name', '-')}",
            f"Mode: {agent_mode}",
            f"Permissions: {permission_mode}",
            f"Session: {self.session_id}",
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
            },
            ensure_ascii=False,
            indent=2,
        )

    def format_sessions(self, *, limit: int = 20) -> str:
        sessions = self.session_manager.list_sessions(limit=limit)
        if not sessions:
            return "No S4Code sessions found."
        lines = []
        for item in sessions:
            lines.append(
                f"{item.session_id} | {item.title} | {item.model or '-'} | "
                f"{item.permission_mode or '-'} | {item.project_root or '-'}"
            )
        return "\n".join(lines)

    def format_config(self) -> str:
        return json.dumps(self.settings.model_dump(mode="python"), ensure_ascii=False, indent=2)

    def format_cost(self) -> str:
        payload = {
            "observability": self.agent.get_observability_summary(),
            "traceSummary": self.agent.get_trace_summary(limit_turns=5),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

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
