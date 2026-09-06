"""S4Code's product Agent. No terminal or transport dependencies."""

from __future__ import annotations

from contextlib import aclosing, contextmanager
from pathlib import Path
from threading import Lock
from uuid import uuid4
from typing import Any
from easyagent import (
    BasicAgent,
    Config,
    EasyLLM,
    ContextManager,
    SkillManager,
    ToolRegistry,
    MultiAgentRuntime,
    ObservabilityManager,
    SQLiteObservabilityStore,
    PlanModeManager,
    PlanModeConfig,
    PermissionContext,
    PermissionMode,
    PermissionRule,
    MCPHub,
    MCPToolManager,
)
from easyagent.context import LLMHistoryCompactor, RuleBasedHistoryCompactor
from easyagent.codeintel import CodeIntelManager, LSPCodeIntelProvider
from easyagent.runtime import RuntimeEventType
from easyagent.tasks import TaskService, SQLiteTaskStore
from easyagent.tools import (
    register_filesystem_tools,
    register_file_write_tool,
    register_file_edit_tool,
    register_notebook_edit_tool,
    register_shell_tools,
    register_web_fetch_tool,
    register_search_tool,
    register_config_tool,
    register_ask_user_question_tool,
)
from .settings import S4AgentSettings, LLMSettings
from .paths import (
    S4Paths,
    get_s4_paths,
    get_project_skills_paths,
    get_s4_repo_skills_path,
)
from .project import ProjectContext
from .prompting import S4PromptComposer, build_s4_system_prompt
from .sessions.manager import S4SessionManager
from .interactions import S4Interactions
from .runtime import S4RuntimeOperations
from .permissions import S4Permissions
from ..version import __version__


class S4CodeAgent(BasicAgent):
    """Product defaults and lifecycle on BasicAgent's execution loop.

    Use ``create`` for product construction. The underlying constructor keeps
    the BasicAgent signature so framework subclass loading remains compatible.
    """

    def __init__(
        self,
        name: str,
        llm: EasyLLM,
        system_prompt: str | None = None,
        description: str | None = None,
        config: Config | None = None,
    ):
        super().__init__(name, llm, system_prompt, description, config)
        self._operation_lock = Lock()
        self.startup_issues: list[str] = []
        self.skill_sources: tuple[str, ...] = ()
        self._owns_llm = True
        self.session: S4SessionManager | None = None
        self.interactions = S4Interactions(self)
        self.runtime = S4RuntimeOperations(self)
        self.permissions = S4Permissions(self)
        self.last_manual_compaction: dict[str, Any] = {}

    @classmethod
    def create(
        cls,
        *,
        workspace: str | Path,
        settings: S4AgentSettings,
        paths: S4Paths | None = None,
        llm: EasyLLM | None = None,
        session_store=None,
    ) -> S4CodeAgent:
        settings = S4AgentSettings.model_validate(settings.model_dump()).model_copy(
            deep=True
        )
        if not settings.model_profiles:
            settings.model_profiles[settings.active_model_profile] = (
                settings.llm.model_copy(deep=True)
            )
        project = ProjectContext.detect(
            workspace, git_binary=settings.product.git_binary
        )
        paths = (paths or get_s4_paths()).ensure()
        model = llm if llm is not None else cls._new_llm(settings.llm)
        config = Config(
            default_model=settings.llm.model,
            default_provider=settings.llm.provider,
            workspace_root=str(project.project_root),
            allowed_roots=project.allowed_roots,
            shell=settings.product.shell,
            command_timeout_ms=settings.product.command_timeout_ms,
            max_background_tasks=settings.product.max_background_tasks,
            git_binary=settings.product.git_binary,
            enable_worktree=settings.product.enable_worktree,
            **{
                k: v
                for k, v in {
                    "temperature": settings.llm.temperature,
                    "max_tokens": settings.llm.max_tokens,
                }.items()
                if v is not None
            },
        )
        agent = cls(
            "S4Code",
            model,
            build_s4_system_prompt(paths=paths, project=project),
            "Local software engineering agent.",
            config,
        )
        agent._owns_llm = llm is None
        agent.settings, agent.project, agent.paths = settings, project, paths
        try:
            agent._install_product()
            agent.session = S4SessionManager(agent, paths, store=session_store)
        except BaseException:
            agent.close()
            raise
        return agent

    @classmethod
    def from_session(
        cls,
        session_id: str,
        *,
        workspace,
        settings: S4AgentSettings,
        paths: S4Paths | None = None,
        llm=None,
        session_store=None,
    ):
        agent = cls.create(
            workspace=workspace,
            settings=settings,
            paths=paths,
            llm=llm,
            session_store=session_store,
        )
        try:
            agent.session.restore(session_id)
        except BaseException:
            agent.close()
            raise
        return agent

    @staticmethod
    def _new_llm(profile: LLMSettings) -> EasyLLM:
        return EasyLLM(
            provider=profile.provider,
            model=profile.model,
            base_url=profile.base_url,
            api_key=profile.api_key,
            temperature=profile.temperature,
            max_tokens=profile.max_tokens,
            timeout=profile.timeout,
            default_headers={
                "User-Agent": profile.user_agent or f"S4Code/{__version__}"
            },
        )

    def _install_product(self) -> None:
        settings = self.settings
        self.with_prompt(S4PromptComposer(paths=self.paths, project=self.project))
        self.with_tool(ToolRegistry())
        common = dict(
            workspace_root=str(self.project.project_root),
            allowed_roots=self.project.allowed_roots,
            cwd=str(self.project.project_root),
        )
        for register in (
            register_filesystem_tools,
            register_file_write_tool,
            register_file_edit_tool,
            register_notebook_edit_tool,
        ):
            register(self.tool_registry, **common)
        register_shell_tools(
            self.tool_registry, workspace_root=str(self.project.project_root)
        )
        register_web_fetch_tool(self.tool_registry)
        self._optional("Search", lambda: register_search_tool(self.tool_registry))
        register_config_tool(self.tool_registry, config=self.config)
        register_ask_user_question_tool(self.tool_registry)
        permissions = PermissionContext()
        permissions.set_mode(PermissionMode(settings.product.permission_mode))
        grouped: dict[str, list[PermissionRule]] = {}
        for value in settings.product.permission_rules:
            rule = PermissionRule.model_validate(value.model_dump())
            grouped.setdefault(rule.source or "session", []).append(rule)
        for source, rules in grouped.items():
            permissions.set_source_rules(source, rules)
        self.with_permissions(context=permissions)
        if settings.context.enabled:
            context = ContextManager(max_tokens=settings.context.max_tokens)
            compactor = (
                LLMHistoryCompactor
                if settings.context.history_compactor == "llm"
                else RuleBasedHistoryCompactor
            )
            options = {"llm": self.llm, "language": "en"} if compactor is LLMHistoryCompactor else {}
            context.set_history_compactor(
                compactor(
                    token_counter=context.counter,
                    recent_turns=settings.context.recent_turns,
                    **options,
                )
            )
            self.with_context(context)
        self.with_task_service(
            TaskService(SQLiteTaskStore(str(self.paths.task_db_path)))
        )
        self._install_skills()
        self.with_plan(PlanModeManager(PlanModeConfig(register_tools=True)))
        if settings.product.enable_worktree and self.project.is_git_repo:
            self._optional("Worktree", self.with_worktree)
        if settings.product.enable_codeintel:
            self._optional(
                "CodeIntel",
                lambda: self.with_codeintel(
                    CodeIntelManager(
                        provider=LSPCodeIntelProvider(),
                        workspace_root=str(self.project.project_root),
                        allowed_roots=self.project.allowed_roots,
                    )
                ),
            )
        self.with_multi_agent(
            MultiAgentRuntime(
                workspace_root=str(self.project.project_root),
                storage_dir=str(self.paths.agent_storage_dir),
                max_background_tasks=settings.product.max_background_tasks,
            )
        )
        self.with_observability(
            ObservabilityManager(
                SQLiteObservabilityStore(
                    str(self.paths.data_dir / "observability.sqlite3")
                )
            )
        )
        self._apply_reasoning()
        if settings.product.enable_mcp:
            self._install_mcp()

    def _optional(self, name, install):
        try:
            return install()
        except Exception as exc:
            self.startup_issues.append(f"{name} initialization failed: {exc}")
            return None

    def _install_skills(self) -> None:
        manager = SkillManager()
        sources = []
        for directory in (
            get_s4_repo_skills_path(),
            self.paths.skills_dir,
            *get_project_skills_paths(self.project.project_root),
        ):
            if directory is None:
                continue
            path = Path(directory).expanduser().resolve()
            if not path.is_dir() or str(path) in sources:
                continue
            try:
                manager.add_directories([path])
                sources.append(str(path))
            except Exception as exc:
                self.startup_issues.append(f"Skill discovery failed for {path}: {exc}")
        if manager.skill_names:
            self.with_skill(manager=manager)
        self.skill_sources = tuple(sources)

    def _install_mcp(self) -> None:
        hub = MCPHub()
        for server in self.settings.mcp_servers:
            if not server.enabled:
                continue
            manager = None
            try:
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
                    **server.transport_kwargs,
                )
                manager.connect()
                self.with_mcp(
                    manager,
                    hub=hub,
                    server_name=server.name,
                    legacy_resource_tools=False,
                )
            except Exception as exc:
                self.startup_issues.append(
                    f"MCP server '{server.name}' initialization failed: {exc}"
                )
                if manager is not None:
                    self._optional("MCP cleanup", manager.close)

    def _apply_reasoning(self):
        self.reasoning = {
            k: v
            for k, v in {
                "effort": self.settings.llm.reasoning_effort,
                "summary": self.settings.llm.reasoning_summary,
            }.items()
            if v is not None
        }

    @property
    def busy(self) -> bool:
        return self._operation_lock.locked()

    def __enter__(self) -> S4CodeAgent:
        if self._closed:
            raise RuntimeError("Agent is closed")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @contextmanager
    def operation(self):
        if self._closed:
            raise RuntimeError("Agent is closed")
        if not self._operation_lock.acquire(blocking=False):
            raise RuntimeError("Agent is busy; stop the active operation first")
        try:
            if self._closed:
                raise RuntimeError("Agent is closed")
            yield
        finally:
            self._operation_lock.release()

    def _after_run(self):
        self.clear_stop_request()
        if self.session is not None:
            self.session.dirty = True
            self.session._autosave()

    def invoke(self, query, max_iter=50, temperature=None, **kwargs):
        with self.operation():
            try:
                return super().invoke(query, max_iter, temperature, **kwargs)
            finally:
                self._after_run()

    async def ainvoke(self, query, max_iter=50, temperature=None, **kwargs):
        with self.operation():
            try:
                return await super().ainvoke(query, max_iter, temperature, **kwargs)
            finally:
                self._after_run()

    def stream(self, query, max_iter=50, temperature=None, **kwargs):
        with self.operation():
            try:
                yield from super().stream(query, max_iter, temperature, **kwargs)
            finally:
                self._after_run()

    async def astream(self, query, max_iter=50, temperature=None, **kwargs):
        with self.operation():
            try:
                async with aclosing(
                    super().astream(query, max_iter, temperature, **kwargs)
                ) as events:
                    async for event in events:
                        yield event
            finally:
                self._after_run()

    def select_model(self, target: str) -> dict[str, str]:
        with self.operation():
            target = target.strip()
            if not target:
                raise ValueError("Model profile or model name is required")
            configured = target in self.settings.model_profiles
            profile = (
                self.settings.model_profiles[target]
                if configured
                else self.settings.llm.model_copy(update={"model": target})
            ).model_copy(deep=True)
            replacement = self._new_llm(profile)
            previous, owned = self.llm, self._owns_llm
            try:
                self.change_model(replacement)
            except BaseException:
                self.change_model(previous)
                replacement.close()
                raise
            self._owns_llm = True
            self.settings.llm = profile
            self.config.default_model = profile.model
            self.config.default_provider = profile.provider
            self.config.temperature = (
                profile.temperature
                if profile.temperature is not None
                else Config().temperature
            )
            self.config.max_tokens = profile.max_tokens
            if configured:
                self.settings.active_model_profile = target
            if self.context_manager is not None:
                compactor = self.context_manager.history_compactor
                if isinstance(compactor, LLMHistoryCompactor):
                    compactor.llm = replacement
            self._apply_reasoning()
            if self.session is not None:
                self.session.overrides["active_model_profile"] = (
                    self.settings.active_model_profile
                )
                self.session.overrides["llm"] = profile.model_dump()
                self.session.dirty = True
                self.session._autosave()
            if owned:
                self._optional("Previous model cleanup", previous.close)
            return {
                "profile": self.settings.active_model_profile,
                "model": profile.model,
                "provider": profile.provider,
            }

    def compact_history(self, max_tokens=None) -> dict[str, Any]:
        with self.operation():
            manager = self.context_manager
            if manager is None:
                raise ValueError("Context management is disabled")
            budget = (
                manager.budget.max_tokens if max_tokens is None else int(max_tokens)
            )
            if budget <= 0:
                raise ValueError("max_tokens must be positive")
            invocation_id = f"compact_{uuid4().hex}"
            hook = self.hook_manager.before_compaction(
                {
                    "canonical_history": self.get_canonical_history(),
                    "replay_history": self.replay_history,
                    "max_tokens": budget,
                    "invocation_id": invocation_id,
                    "source": "s4code.manual",
                }
            )
            if hook.blocked:
                raise ValueError("History compaction was blocked by a hook")
            result = manager.compact_persistent_history(
                hook.payload.get("canonical_history", self.get_canonical_history()),
                hook.payload.get("replay_history", self.replay_history),
                provider_name=self.llm.provider_name,
                token_counter=manager.counter,
                system_prompt=self.get_enhanced_prompt(),
                tools=self.get_provider_tools(),
                reasoning=self.reasoning,
                max_tokens=int(hook.payload.get("max_tokens") or budget),
                force=True,
                metadata={"source": "s4code.manual", "hook_audit": hook.audit},
            )
            if result.was_compacted:
                self.history = result.canonical_history
            payload = dict(
                was_compacted=result.was_compacted,
                compaction_possible=result.compaction_possible,
                tokens_before=result.tokens_before,
                tokens_after=result.tokens_after,
                max_tokens=result.budget,
                metadata=dict(result.metadata),
            )
            self.last_manual_compaction = payload
            self.event_bus.publish(
                RuntimeEventType.HISTORY_COMPACTED,
                agent_id=self.name,
                invocation_id=invocation_id,
                data=payload,
            )
            if self.session is not None:
                self.session.dirty = True
                self.session._autosave()
            return payload

    def export_conversation(self) -> dict[str, Any]:
        """Copy conversation data; checkpoint policy belongs to the caller."""
        with self.operation():
            return {
                "history": self.history_store.export_state(),
                "interruptions": self.interrupt_controller.export_state(),
            }

    def clear_history(self) -> None:
        with self.operation():
            super().clear_history()
            self.interrupt_controller.restore_state(None)
            self.metamessage_manager.reconcile_history()
            if self.session is not None:
                self.session.dirty = True
                self.session._autosave()

    def restore_conversation(self, state: dict[str, Any]) -> None:
        with self.operation():
            if not isinstance(state, dict) or not isinstance(
                state.get("history"), dict
            ):
                raise ValueError("Conversation state must contain a history object")
            if state.get("interruptions") is not None and not isinstance(
                state["interruptions"], dict
            ):
                raise ValueError("Conversation interruptions must be an object")
            previous_history = self.history_store.export_state()
            previous_interruptions = self.interrupt_controller.export_state()
            try:
                self.history_store.restore_state(state["history"])
                self.interrupt_controller.restore_state(state.get("interruptions"))
            except Exception:
                self.history_store.restore_state(previous_history)
                self.interrupt_controller.restore_state(previous_interruptions)
                raise
            self.metamessage_manager.reconcile_history()
            if self.session is not None:
                self.session.dirty = True
                self.session._autosave()

    def close(
        self, *, worktree_action="keep", discard_worktree_changes=False, close_llm=True
    ):
        if self._closed:
            return self.get_last_close_report()
        with self.operation():
            if self.session is not None:
                self.session._autosave()
            return super().close(
                worktree_action=worktree_action,
                discard_worktree_changes=discard_worktree_changes,
                close_llm=close_llm and self._owns_llm,
            )
