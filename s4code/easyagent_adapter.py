"""EasyAgent integration layer for S4Code."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from re import S
from typing import Any, Optional

from ._easyagent_bootstrap import ensure_easyagent_environment

ensure_easyagent_environment()

from agent import BasicAgent
from codeintel import CodeIntelManager, LSPCodeIntelProvider
from context import ContextManager, LLMHistoryCompactor, RuleBasedHistoryCompactor
from core.Config import Config
from core.guardrails import build_default_hook_manager
from core.llm import EasyLLM
from core.permissions import PermissionContext, PermissionMode
from db import SessionStore
from runtime import ExecutionContext
from task import SQLiteTaskStore, TaskService
from Tool import ToolRegistry
from Tool.builtin import (
    register_ask_user_question_tool,
    register_config_tool,
    register_codeintel_tools,
    register_enter_plan_mode_tool,
    register_exit_plan_mode_tool,
    register_file_edit_tool,
    register_file_write_tool,
    register_filesystem_tools,
    register_notebook_edit_tool,
    register_mcp_tools,
    register_search_tool,
    register_shell_tools,
    register_todo_write_tool,
    register_web_fetch_tool,
)
from skill import SkillManager, SkillRegistry
from .config import S4Settings
from .paths import S4Paths, get_project_skills_path
from .project import ProjectContext
from .runtime_hooks import S4RuntimeNoticeHook


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
    context_manager: Optional[ContextManager] = None
    runtime_notice_hook: Optional[S4RuntimeNoticeHook] = None
    startup_issues: list[str] = field(default_factory=list)
    restore_report: Optional[dict[str, Any]] = None


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


def _build_context_manager(settings: S4Settings, llm: EasyLLM) -> Optional[ContextManager]:
    if not settings.context.enabled:
        return None
    manager = ContextManager(max_tokens=settings.context.max_tokens)
    if settings.context.history_compactor == "llm":
        manager.set_history_compactor(
            LLMHistoryCompactor(
                llm=llm,
                token_counter=manager.counter,
                recent_turns=settings.context.recent_turns,
            )
        )
    else:
        manager.set_history_compactor(
            RuleBasedHistoryCompactor(
                token_counter=manager.counter,
                recent_turns=settings.context.recent_turns,
            )
        )
    return manager


def _register_base_tools(
    registry: ToolRegistry,
    *,
    project: ProjectContext,
    settings: S4Settings,
    config: Config,
    task_service: TaskService,
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
    register_notebook_edit_tool(
        registry,
        workspace_root=workspace_root,
        allowed_roots=allowed_roots,
        cwd=workspace_root,
    )
    register_shell_tools(
        registry,
        workspace_root=workspace_root,
    )
    register_web_fetch_tool(registry)
    try:
        register_search_tool(registry)
    except Exception as exc:
        startup_issues.append(f"Search tool registration failed: {exc}")
    register_todo_write_tool(
        registry,
        service=task_service,
        scope_key=f"s4code:{project.project_name}",
        owner="S4Code",
    )
    register_config_tool(registry, config=config)
    register_ask_user_question_tool(registry)
    register_enter_plan_mode_tool(registry)
    register_exit_plan_mode_tool(registry)
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
    config = _build_agent_config(settings, project)
    hook_manager = build_default_hook_manager()
    runtime_notice_hook = S4RuntimeNoticeHook()
    hook_manager.add_hook(runtime_notice_hook)
    context_manager = _build_context_manager(settings, llm)
    codeintel_manager: Optional[CodeIntelManager] = None
    skill_register:SkillRegistry = SkillRegistry()
    skill_register.discover_from_directory(str(paths.skills_dir))

    local_skill_dir = get_project_skills_path(project.project_root)
    if local_skill_dir.exists() and local_skill_dir.is_dir():
        skill_register.discover_from_directory(str(local_skill_dir))

    if settings.product.enable_codeintel:
        try:
            codeintel_manager = CodeIntelManager(provider=LSPCodeIntelProvider())
        except Exception as exc:
            startup_issues.append(f"CodeIntel initialization failed: {exc}")

    _register_base_tools(
        registry,
        project=project,
        settings=settings,
        config=config,
        task_service=task_service,
        codeintel_manager=codeintel_manager,
        startup_issues=startup_issues,
    )

    if restore_session_id:
        agent = BasicAgent.load_session(
            restore_session_id,
            llm=llm,
            store=session_store,
            tool_registry=registry,
            context_manager=context_manager,
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
            context_manager=context_manager,
            history_via_context_manager=context_manager is not None,
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
    for skill in skill_register.list_available_names():
        agent.with_skill(skill_register.create(skill))
    if agent.agent_runtime is None:
        agent.enable_multi_agent_system(
            workspace_root=str(project.project_root),
            storage_dir=str(paths.agent_storage_dir),
            max_background_tasks=settings.product.max_background_tasks,
        )
    restore_report = None
    restore_report_getter = getattr(agent, "get_last_restore_report", None)
    if callable(restore_report_getter):
        restore_report = restore_report_getter()

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
        context_manager=context_manager,
        runtime_notice_hook=runtime_notice_hook,
        startup_issues=startup_issues,
        restore_report=restore_report,
    )
