"""EasyAgent integration layer for S4Code."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from easyagent import (
    BasicAgent,
    Config,
    EasyLLM,
    ExecutionContext,
    PermissionContext,
    PermissionMode,
    ToolRegistry,
    build_default_hook_manager,
)
from easyagent.codeintel import CodeIntelManager, LSPCodeIntelProvider
from easyagent.session import SessionStore
from easyagent.tasks import SQLiteTaskStore, TaskService
from easyagent.tools import (
    register_codeintel_tools,
    register_file_edit_tool,
    register_file_write_tool,
    register_filesystem_tools,
    register_mcp_tools,
    register_shell_tools,
)

from .config import S4Settings
from .paths import S4Paths
from .project import ProjectContext


S4_AGENT_SYSTEM_PROMPT = """You are S4Code, a serious code agent running inside a local CLI.

Operating rules:
- Treat the repository as the source of truth. Inspect before changing anything.
- Prefer file, search, code-intel, task, and runtime tools over unsupported assumptions.
- For non-trivial work, keep a structured task list and update it as work progresses.
- When the user asks for review, prioritize findings: bugs, regressions, risks, and missing tests.
- When editing code, keep changes scoped, coherent, and production-grade.
- Use subagents only for bounded parallel work with clear ownership.
- If tool results include IDs, output files, task IDs, or runtime handles, use those structured values instead of inventing your own labels.
- Respect the current permission mode. In plan mode, produce plans; in execute mode, do the work.
- When code intelligence is available, prefer symbol-aware inspection over blind file scanning.
- Be concise, but do not omit concrete technical details needed to complete the task.
"""


@dataclass(slots=True)
class S4AgentBundle:
    settings: S4Settings
    project: ProjectContext
    paths: S4Paths
    llm: EasyLLM
    agent: BasicAgent
    registry: ToolRegistry
    task_service: TaskService
    session_store: SessionStore
    codeintel_manager: Optional[CodeIntelManager] = None
    startup_issues: list[str] = field(default_factory=list)


def _build_llm(settings: S4Settings) -> EasyLLM:
    return EasyLLM(
        provider=settings.llm.provider,
        base_url=settings.llm.base_url,
        api_key=settings.llm.api_key,
        model=settings.llm.model,
        temperature=settings.llm.temperature,
        max_tokens=settings.llm.max_tokens,
        timeout=settings.llm.timeout,
    )


def _build_agent_config(settings: S4Settings, project: ProjectContext) -> Config:
    return Config(
        default_model=settings.llm.model,
        default_provider=settings.llm.provider,
        temperature=settings.llm.temperature,
        max_tokens=settings.llm.max_tokens,
        workspace_root=str(project.project_root),
        allowed_roots=[str(project.project_root)],
        shell=settings.product.shell,
        command_timeout_ms=settings.product.command_timeout_ms,
        max_background_tasks=settings.product.max_background_tasks,
        git_binary=settings.product.git_binary,
        enable_worktree=settings.product.enable_worktree,
    )


def _build_permission_context(settings: S4Settings) -> PermissionContext:
    context = PermissionContext()
    context.set_mode(PermissionMode(str(settings.product.permission_mode)))
    return context


def _register_base_tools(
    registry: ToolRegistry,
    *,
    project: ProjectContext,
    settings: S4Settings,
    codeintel_manager: Optional[CodeIntelManager],
    startup_issues: list[str],
) -> None:
    workspace_root = str(project.project_root)
    allowed_roots = project.allowed_roots
    register_filesystem_tools(
        registry,
        workspace_root=workspace_root,
        allowed_roots=allowed_roots,
        cwd=workspace_root,
    )
    register_file_write_tool(
        registry,
        workspace_root=workspace_root,
        allowed_roots=allowed_roots,
        cwd=workspace_root,
    )
    register_file_edit_tool(
        registry,
        workspace_root=workspace_root,
        allowed_roots=allowed_roots,
        cwd=workspace_root,
    )
    register_shell_tools(
        registry,
        workspace_root=workspace_root,
    )
    if codeintel_manager is not None:
        register_codeintel_tools(
            registry,
            manager=codeintel_manager,
            workspace_root=workspace_root,
            allowed_roots=allowed_roots,
        )
    if settings.product.enable_mcp:
        for server in settings.mcp_servers:
            try:
                register_mcp_tools(
                    registry,
                    server_source=server.server_source,
                    server_args=server.server_args,
                    transport_type=server.transport_type,
                    tool_prefix=server.tool_prefix,
                    auto_connect=server.auto_connect,
                    include_resources=server.include_resources,
                    env=server.env,
                    server_name=server.name,
                )
            except Exception as exc:
                startup_issues.append(f"MCP server '{server.name}' registration failed: {exc}")


def build_agent_bundle(
    *,
    settings: S4Settings,
    project: ProjectContext,
    paths: S4Paths,
    session_store: Optional[SessionStore] = None,
    restore_session_id: Optional[str] = None,
) -> S4AgentBundle:
    paths.ensure()
    startup_issues: list[str] = []
    llm = _build_llm(settings)
    registry = ToolRegistry()
    task_service = TaskService(SQLiteTaskStore(str(paths.task_db_path)))
    session_store = session_store or SessionStore(str(paths.session_db_path))
    permission_context = _build_permission_context(settings)
    hook_manager = build_default_hook_manager()
    codeintel_manager: Optional[CodeIntelManager] = None

    if settings.product.enable_codeintel:
        try:
            codeintel_manager = CodeIntelManager(provider=LSPCodeIntelProvider())
        except Exception as exc:
            startup_issues.append(f"CodeIntel initialization failed: {exc}")

    _register_base_tools(
        registry,
        project=project,
        settings=settings,
        codeintel_manager=codeintel_manager,
        startup_issues=startup_issues,
    )
    config = _build_agent_config(settings, project)

    if restore_session_id:
        agent = BasicAgent.load_session(
            restore_session_id,
            llm=llm,
            store=session_store,
            tool_registry=registry,
            hook_manager=hook_manager,
            permission_context=permission_context,
            task_service=task_service,
        )
    else:
        agent = BasicAgent(
            name="S4Code",
            llm=llm,
            system_prompt=S4_AGENT_SYSTEM_PROMPT,
            enable_tool=True,
            tool_registry=registry,
            config=config,
            permission_context=permission_context,
            hook_manager=hook_manager,
            task_service=task_service,
            execution_context=ExecutionContext(
                workspace_root=str(project.project_root),
                allowed_roots=project.allowed_roots,
                permission_mode=str(settings.product.permission_mode),
                execution_mode="execute",
            ),
            verbose_thinking=settings.ui.show_thinking,
            reasoning={
                "effort": settings.llm.reasoning_effort,
                "summary": settings.llm.reasoning_summary,
            },
        )

    if agent.agent_runtime is None:
        agent.enable_multi_agent_system(
            workspace_root=str(project.project_root),
            storage_dir=str(paths.agent_storage_dir),
            max_background_tasks=settings.product.max_background_tasks,
        )

    return S4AgentBundle(
        settings=settings,
        project=project,
        paths=paths,
        llm=llm,
        agent=agent,
        registry=registry,
        task_service=task_service,
        session_store=session_store,
        codeintel_manager=codeintel_manager,
        startup_issues=startup_issues,
    )

