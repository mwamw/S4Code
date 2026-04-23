"""EasyAgent integration layer for S4Code."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ._easyagent_bootstrap import ensure_easyagent_environment

ensure_easyagent_environment()

from agent import BasicAgent
from codeintel import CodeIntelManager, LSPCodeIntelProvider
from context import ContextManager, LLMHistoryCompactor, RuleBasedHistoryCompactor
from core.Config import Config
from core.guardrails import build_default_hook_manager
from core.llm import EasyLLM
from core.permissions import PermissionContext, PermissionMode, PermissionRule
from db import SessionStore
from mcp import MCPHub
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
    register_search_tool,
    register_shell_tools,
    register_todo_write_tool,
    register_web_fetch_tool,
)
from Tool.builtin.mcp_tool import MCPToolManager
from skill import MetaSkill, SkillManager, SkillRegistry
from .config import S4Settings
from .paths import S4Paths, get_project_skills_paths, get_s4_repo_skills_path
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
    skill_registry: SkillRegistry
    codeintel_manager: Optional[CodeIntelManager] = None
    context_manager: Optional[ContextManager] = None
    runtime_notice_hook: Optional[S4RuntimeNoticeHook] = None
    startup_issues: list[str] = field(default_factory=list)
    restore_report: Optional[dict[str, Any]] = None
    skill_sources: tuple[str, ...] = ()


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
    rules_by_source: dict[str, list[PermissionRule]] = {}
    for item in list(settings.product.permission_rules or []):
        try:
            payload = item.model_dump(mode="python") if hasattr(item, "model_dump") else dict(item)
            rule = PermissionRule.model_validate(payload)
        except Exception:
            continue
        source = str(rule.source or "session").strip() or "session"
        rules_by_source.setdefault(source, []).append(rule)
    for source, rules in rules_by_source.items():
        context.set_source_rules(source, rules)
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
        _register_mcp_servers(
            registry,
            settings=settings,
            startup_issues=startup_issues,
        )


def _register_mcp_servers(
    registry: ToolRegistry,
    *,
    settings: S4Settings,
    startup_issues: list[str],
) -> None:
    enabled_servers = [server for server in settings.mcp_servers if bool(server.enabled)]
    if not enabled_servers:
        return
    hub = MCPHub()
    for server in enabled_servers:
        manager = MCPToolManager(
            server_source=server.server_source,
            server_args=server.server_args,
            transport_type=server.transport_type,
            env=server.env,
            tool_prefix=server.tool_prefix,
            auto_connect=False,
            auth_config=server.auth,
            policy_context=server.policy,
            max_retries=server.max_retries,
            persist_connection=server.persist_connection,
            include_resources=server.include_resources,
            **dict(server.transport_kwargs or {}),
        )
        try:
            manager.connect()
        except Exception as exc:
            startup_issues.append(f"MCP server '{server.name}' connection failed: {exc}")
            continue
        try:
            manager.register_to_registry(
                registry,
                hub=hub,
                server_name=server.name,
                legacy_resource_tools=False,
            )
        except Exception as exc:
            startup_issues.append(f"MCP server '{server.name}' registration failed: {exc}")
            try:
                manager.close()
            except Exception:
                pass


def _connect_registered_mcp_servers(
    registry: ToolRegistry,
    *,
    startup_issues: list[str],
) -> None:
    surfaces = registry.list_runtime_surfaces("mcp_manager")
    for name, manager in surfaces.items():
        try:
            client = getattr(manager, "client", None)
            is_connected = callable(getattr(client, "is_connected", None)) and bool(client.is_connected())
            if is_connected:
                continue
            connect = getattr(manager, "connect", None)
            if callable(connect):
                connect()
        except Exception as exc:
            startup_issues.append(f"MCP server '{name}' startup connect failed: {exc}")


def _discover_skill_registry(
    *,
    paths: S4Paths,
    project: ProjectContext,
    startup_issues: list[str],
) -> tuple[SkillRegistry, tuple[str, ...]]:
    registry = SkillRegistry()
    discovered_dirs: list[str] = []
    seen: set[str] = set()
    candidates = (
        get_s4_repo_skills_path(),
        paths.skills_dir,
        *get_project_skills_paths(project.project_root),
    )
    for candidate in candidates:
        resolved = Path(candidate).expanduser().resolve()
        marker = str(resolved)
        if marker in seen:
            continue
        seen.add(marker)
        if not resolved.exists() or not resolved.is_dir():
            continue
        discovered_dirs.append(marker)
        try:
            registry.discover_from_directory(marker)
        except Exception as exc:
            startup_issues.append(f"Skill discovery failed for '{marker}': {exc}")
    return registry, tuple(discovered_dirs)


def _load_restore_snapshot(
    session_store: SessionStore,
    restore_session_id: Optional[str],
) -> dict[str, Any]:
    if not restore_session_id:
        return {}
    try:
        record = session_store.get_session(restore_session_id)
    except Exception:
        return {}
    if not isinstance(record, dict):
        return {}
    snapshot = record.get("snapshot")
    if not isinstance(snapshot, dict):
        return {}
    return dict(snapshot)


def _preregister_restore_skills(
    *,
    manager: SkillManager,
    registry: SkillRegistry,
    snapshot: dict[str, Any],
    startup_issues: list[str],
) -> None:
    for name in list(snapshot.get("registered_skills") or []):
        skill_name = str(name or "").strip()
        if not skill_name or skill_name == "meta_skill" or manager.has_skill(skill_name):
            continue
        if not registry.has(skill_name):
            startup_issues.append(f"Saved session skill unavailable: {skill_name}")
            continue
        try:
            manager.register(registry.create(skill_name), auto_activate=False)
        except Exception as exc:
            startup_issues.append(f"Skill preregistration failed for '{skill_name}': {exc}")


def _attach_meta_skill(
    *,
    agent: BasicAgent,
    registry: SkillRegistry,
    startup_issues: list[str],
) -> None:
    if agent.skill_manager.has_skill("meta_skill"):
        return
    try:
        agent.with_skill(MetaSkill(registry, agent.skill_manager))
    except Exception as exc:
        startup_issues.append(f"Meta skill initialization failed: {exc}")


def _restore_active_skills(
    *,
    agent: BasicAgent,
    snapshot: dict[str, Any],
    startup_issues: list[str],
) -> None:
    for name in list(snapshot.get("active_skills") or []):
        skill_name = str(name or "").strip()
        if not skill_name or skill_name == "meta_skill":
            continue
        if not agent.skill_manager.has_skill(skill_name):
            startup_issues.append(f"Active session skill could not be restored: {skill_name}")
            continue
        if agent.skill_manager.is_active(skill_name):
            continue
        try:
            skill = agent.skill_manager.get_skill(skill_name)
            visibility = "runtime" if skill.get_exposure_mode() == "on_demand" else "resident"
            agent.skill_manager.activate(skill_name, tool_visibility=visibility)
        except Exception as exc:
            startup_issues.append(f"Skill activation failed for '{skill_name}': {exc}")


def _register_resident_skills(
    *,
    agent: BasicAgent,
    registry: SkillRegistry,
    startup_issues: list[str],
) -> None:
    for manifest in registry.list_manifests():
        if manifest.name == "meta_skill" or manifest.exposure_mode != "resident":
            continue
        if agent.skill_manager.has_skill(manifest.name):
            continue
        try:
            agent.with_skill(registry.create(manifest.name))
        except Exception as exc:
            startup_issues.append(f"Resident skill load failed for '{manifest.name}': {exc}")


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
    skill_registry, skill_sources = _discover_skill_registry(
        paths=paths,
        project=project,
        startup_issues=startup_issues,
    )
    skill_manager = SkillManager()
    skill_manager.bind_registry(skill_registry)
    restore_snapshot = _load_restore_snapshot(session_store, restore_session_id)
    if restore_snapshot:
        _preregister_restore_skills(
            manager=skill_manager,
            registry=skill_registry,
            snapshot=restore_snapshot,
            startup_issues=startup_issues,
        )

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
            skill_manager=skill_manager,
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
            skill_manager=skill_manager,
            execution_context=ExecutionContext(
                workspace_root=str(project.project_root),
                allowed_roots=project.allowed_roots,
                permission_mode=str(settings.product.permission_mode),
                execution_mode="execute",
            ),
            verbose_thinking=settings.ui.show_thinking,
            reasoning={
                key: value
                for key, value in {
                    "effort": settings.llm.reasoning_effort,
                    "summary": settings.llm.reasoning_summary,
                }.items()
                if value is not None
            },
        )

    agent.skill_manager.bind_registry(skill_registry)
    _attach_meta_skill(
        agent=agent,
        registry=skill_registry,
        startup_issues=startup_issues,
    )
    if restore_snapshot:
        _restore_active_skills(
            agent=agent,
            snapshot=restore_snapshot,
            startup_issues=startup_issues,
        )
    else:
        _register_resident_skills(
            agent=agent,
            registry=skill_registry,
            startup_issues=startup_issues,
        )
    if agent.agent_runtime is None:
        agent.enable_multi_agent_system(
            workspace_root=str(project.project_root),
            storage_dir=str(paths.agent_storage_dir),
            max_background_tasks=settings.product.max_background_tasks,
        )
    _connect_registered_mcp_servers(
        registry,
        startup_issues=startup_issues,
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
        skill_registry=skill_registry,
        codeintel_manager=codeintel_manager,
        context_manager=context_manager,
        runtime_notice_hook=runtime_notice_hook,
        startup_issues=startup_issues,
        restore_report=restore_report,
        skill_sources=skill_sources,
    )
