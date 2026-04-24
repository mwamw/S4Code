from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import s4code.query_engine as query_engine
from s4code.config import LLMSettings, MCPServerSettings, S4Settings
from s4code.paths import S4Paths
from s4code.project import ProjectContext
from core.permissions import PermissionContext, PermissionMode


class _DummyAgent:
    def __init__(self) -> None:
        self.saved: list[dict[str, object]] = []
        self.llm = SimpleNamespace(model="dummy-model", provider_name="dummy-provider")

    def save_session(self, session_id: str, *, store=None, metadata=None) -> None:
        self.saved.append(
            {
                "session_id": session_id,
                "store": store,
                "metadata": metadata,
            }
        )


class _FakeSkill:
    def __init__(self, name: str, *, exposure_mode: str = "on_demand", body: str = "Use this skill.") -> None:
        self.name = name
        self._exposure_mode = exposure_mode
        self._body = body

    def get_exposure_mode(self) -> str:
        return self._exposure_mode

    def get_body_prompt(self) -> str:
        return self._body


class _FakeSkillManager:
    def __init__(self) -> None:
        self._skills: dict[str, _FakeSkill] = {}
        self._active: set[str] = set()
        self.activations: list[tuple[str, str]] = []

    def has_skill(self, name: str) -> bool:
        return name in self._skills

    def get_skill(self, name: str) -> _FakeSkill:
        return self._skills[name]

    def register(self, skill: _FakeSkill, *, auto_activate: bool = False) -> None:
        self._skills[skill.name] = skill
        if auto_activate:
            self.activate(skill.name)

    def unregister(self, name: str) -> None:
        self._active.discard(name)
        self._skills.pop(name, None)

    def is_active(self, name: str) -> bool:
        return name in self._active

    def activate(self, name: str, *, tool_visibility: str = "resident") -> None:
        self._active.add(name)
        self.activations.append((name, tool_visibility))

    def deactivate(self, name: str) -> None:
        self._active.discard(name)

    def get_active_skills(self) -> list[_FakeSkill]:
        return [self._skills[name] for name in sorted(self._active)]


class _FakeSkillRegistry:
    def __init__(self, manifests: list[SimpleNamespace], factory: dict[str, object]) -> None:
        self._manifests = manifests
        self._factory = factory

    def list_manifests(self) -> list[SimpleNamespace]:
        return list(self._manifests)

    def has(self, name: str) -> bool:
        return name in self._factory

    def create(self, name: str):
        factory = self._factory[name]
        return factory()


class _LifecycleAgent(_DummyAgent):
    def __init__(self, *, skill_manager: _FakeSkillManager | None = None) -> None:
        super().__init__()
        self.skill_manager = skill_manager or _FakeSkillManager()
        self.invocations: list[str] = []
        self.close_calls = 0
        self.permission_context = PermissionContext()
        self.history: list[object] = []
        self.agent_runtime = None

    def invoke(self, prompt: str, *, max_iter: int = 20) -> str:
        self.invocations.append(prompt)
        self.history.append({"role": "user", "content": prompt})
        self.history.append({"role": "assistant", "content": "invoked"})
        return "invoked"

    def get_canonical_history(self) -> list[object]:
        return list(self.history)

    def _set_history_entries(self, messages: list[object], *, rebuild_replay: bool = True) -> None:
        self.history = list(messages)

    def get_context_usage(self) -> dict[str, object]:
        return {
            "used_tokens": len(self.history),
            "remaining_tokens": 1000,
            "max_tokens": 1000,
            "last_history_compaction": {},
        }

    def compact_history(self, max_tokens: int | None = None) -> bool:
        if not self.history:
            return False
        self.history = self.history[-1:]
        return True

    def get_trace_summary(self, *, limit_turns: int = 5) -> list[dict[str, object]]:
        return [{"query": "test", "status": "ok", "durationMs": 1}]

    def get_recent_observability_events(self, *, limit: int = 500, event_type: str | None = None) -> list[dict[str, object]]:
        return []

    def set_permission_mode(self, mode: str) -> None:
        self.permission_context.set_mode(PermissionMode(mode))

    def add_permission_rule(self, rule, *, source: str | None = None, priority: int | None = None) -> None:
        self.permission_context.add_rule(rule, source=source, priority=priority)

    def clear_permission_rules(self, *, source: str | None = None) -> None:
        self.permission_context.clear_rules(source=source)

    def close(self) -> dict[str, object]:
        self.close_calls += 1
        return {
            "status": "closed",
            "metadata": {"closeCalls": self.close_calls},
            "components": {},
            "issues": [],
        }

    def get_execution_mode(self):
        return SimpleNamespace(value="execute")


def test_query_engine_compact_history_uses_last_history_compaction_payload() -> None:
    class _CompactionAgent:
        def __init__(self) -> None:
            self.calls: list[int | None] = []

        def compact_history(self, max_tokens: int | None = None) -> bool:
            self.calls.append(max_tokens)
            return True

        def get_context_usage(self) -> dict[str, object]:
            return {
                "last_history_compaction": {
                    "was_compacted": True,
                    "compaction_possible": True,
                    "tokens_before": 25000,
                    "tokens_after": 9000,
                    "budget": 24000,
                }
            }

    autosaves: list[bool] = []
    agent = _CompactionAgent()
    engine = object.__new__(query_engine.S4QueryEngine)
    engine.bundle = SimpleNamespace(agent=agent)
    engine.ensure_autosave = lambda: autosaves.append(True)  # type: ignore[method-assign]

    result = query_engine.S4QueryEngine.compact_history(engine, max_tokens=24000)

    assert result == "Conversation compacted.\nbefore=25000 after=9000 budget=24000"
    assert agent.calls == [24000]
    assert autosaves == [True]


class _FakeSessionManager:
    def __init__(self, record: dict | None = None) -> None:
        self.store = object()
        self._record = record

    def new_session_id(self, project: ProjectContext) -> str:
        return f"s4-{project.project_name}-new"

    def get_record(self, session_id: str) -> dict | None:
        return self._record

    def build_metadata(
        self,
        *,
        project: ProjectContext,
        title: str,
        settings_payload: dict,
        session_overrides: dict,
        forked_from_session_id: str | None = None,
    ) -> dict[str, object]:
        return {
            "project_root": str(project.project_root),
            "title": title,
            "session_overrides": session_overrides,
            "forked_from_session_id": forked_from_session_id,
            "settings_payload": settings_payload,
        }

    def list_sessions(self, *, limit: int = 30) -> list[object]:
        return []


def _paths(tmp_path: Path) -> S4Paths:
    return S4Paths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        global_config_path=tmp_path / "config" / "config.yaml",
        session_db_path=tmp_path / "data" / "sessions.db",
        task_db_path=tmp_path / "data" / "tasks.db",
        agent_storage_dir=tmp_path / "data" / "agents",
        logs_dir=tmp_path / "data" / "logs",
    ).ensure()


def _settings(*, mcp_servers: list[MCPServerSettings] | None = None) -> S4Settings:
    llm = LLMSettings(
        provider="openai",
        model="dummy-model",
        base_url=None,
        api_key=None,
        temperature=None,
        max_tokens=None,
        timeout=None,
        reasoning_effort=None,
        reasoning_summary=None,
    )
    return S4Settings(
        active_model_profile="default",
        model_profiles={"default": llm},
        llm=llm,
        mcp_servers=list(mcp_servers or []),
    )


class _FakeMCPConnectionManager:
    def __init__(
        self,
        *,
        status: str = "connected",
        persist_connection: bool = True,
        last_error: str = "",
    ) -> None:
        self.persist_connection = persist_connection
        self._state = {
            "status": status,
            "lastOperation": "connect",
            "lastError": last_error,
            "lastErrorType": "RuntimeError" if last_error else "",
            "lastConnectedAt": 1710000000.0,
            "lastDisconnectedAt": None,
            "retryCount": 0,
            "transport": {"transport_type": "stdio", "command": "python"},
        }

    def describe_state(self) -> dict[str, object]:
        return dict(self._state)


class _FakeMCPManager:
    def __init__(
        self,
        name: str,
        *,
        status: str = "connected",
        tools: list[dict[str, object]] | None = None,
        resources: list[dict[str, object]] | None = None,
        prompts: list[dict[str, object]] | None = None,
        persist_connection: bool = True,
    ) -> None:
        self.registry_server_name = name
        self.source_identifier = f"python:{name}.py"
        self.include_resources = True
        self.connection_manager = _FakeMCPConnectionManager(
            status=status,
            persist_connection=persist_connection,
        )
        self._snapshot = SimpleNamespace(
            tools=list(tools or []),
            resources=list(resources or []),
            prompts=list(prompts or []),
        )
        self.connect_calls = 0
        self.close_calls = 0
        self.snapshot_refresh_calls: list[bool] = []

    def snapshot(self, *, refresh: bool = False):
        self.snapshot_refresh_calls.append(refresh)
        return self._snapshot

    def connect(self) -> None:
        self.connect_calls += 1

    def close(self) -> dict[str, object]:
        self.close_calls += 1
        return {"status": "closed"}


class _CountingAgentRuntime:
    def __init__(self) -> None:
        self.calls = 0

    def list_handles(self, limit: int = 20) -> list[object]:
        self.calls += 1
        return [
            SimpleNamespace(
                agent_id="agent-1",
                status="running",
                name="worker",
                execution_context=SimpleNamespace(current_task_id="task-1"),
                output_file="out.log",
            )
        ][:limit]


class _CountingTaskService:
    def __init__(self) -> None:
        self.calls = 0

    def list_tasks(self, limit: int = 20) -> list[object]:
        self.calls += 1
        return [
            SimpleNamespace(
                task_id="task-1",
                status=SimpleNamespace(value="running"),
                title="Run tests",
            )
        ][:limit]


class _CountingProcessManager:
    def __init__(self) -> None:
        self.calls = 0

    def list_tasks(self) -> list[object]:
        self.calls += 1
        return [
            SimpleNamespace(
                task_id="bg-1",
                status="running",
                cwd="/tmp",
                command="pytest -q",
                return_code=None,
                started_at=10.0,
                finished_at=None,
                stdout="collecting",
                stderr="",
            )
        ]


def _make_project(path: Path) -> ProjectContext:
    resolved = path.resolve()
    return ProjectContext(
        cwd=resolved,
        project_root=resolved,
        git_root=None,
        git_available=True,
        is_git_repo=False,
        branch=None,
    )


def test_query_engine_constructor_uses_session_metadata_for_resume(tmp_path: Path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    fallback_root = tmp_path / "fallback"
    restored_root = tmp_path / "restored"
    fallback_root.mkdir()
    restored_root.mkdir()

    session_record = {
        "metadata": {
            "project_root": str(restored_root),
            "title": "Restored Bug Hunt",
            "session_overrides": {"product": {"permission_mode": "bypass"}},
            "forked_from_session_id": "sess-parent",
        }
    }
    session_manager = _FakeSessionManager(record=session_record)
    build_calls: list[dict[str, object]] = []
    resolve_calls: list[dict[str, object]] = []
    dummy_agent = _DummyAgent()

    monkeypatch.setattr(query_engine, "get_s4_paths", lambda: paths)
    monkeypatch.setattr(query_engine, "S4SessionManager", lambda raw_paths: session_manager)

    def _detect(cls, cwd=None, git_binary: str = "git") -> ProjectContext:
        return _make_project(Path(cwd or fallback_root))

    monkeypatch.setattr(query_engine.ProjectContext, "detect", classmethod(_detect))

    def _resolve(raw_paths, *, project_root=None, session_overrides=None):
        settings = _settings()
        settings.ui.right_panel_open = True
        settings.product.session_auto_save = True
        resolve_calls.append(
            {
                "project_root": Path(project_root).resolve(),
                "session_overrides": session_overrides,
            }
        )
        return settings

    monkeypatch.setattr(query_engine, "resolve_settings", _resolve)

    def _build_bundle(**kwargs):
        build_calls.append(kwargs)
        return SimpleNamespace(
            agent=dummy_agent,
            registry=SimpleNamespace(
                get_tool_names=lambda: [],
                list_tool_specs=lambda: [],
                list_runtime_surfaces=lambda surface: {},
            ),
            task_service=SimpleNamespace(list_tasks=lambda limit=20: []),
            context_manager=None,
            runtime_notice_hook=None,
            startup_issues=[],
            restore_report={"status": "restored", "executionContextRestored": True, "issues": []},
        )

    monkeypatch.setattr(query_engine, "build_agent_bundle", _build_bundle)

    engine = query_engine.S4QueryEngine(
        cwd=fallback_root,
        session_id="sess-123",
        session_overrides={"llm": {"model": "override-model"}},
    )

    assert engine.was_restored is True
    assert engine.project.project_root == restored_root.resolve()
    assert engine.title == "Restored Bug Hunt"
    assert engine.forked_from_session_id == "sess-parent"
    assert engine.sidebar_visible is True
    assert build_calls[0]["project"].project_root == restored_root.resolve()
    assert build_calls[0]["restore_session_id"] == "sess-123"
    assert resolve_calls[0]["project_root"] == restored_root.resolve()
    assert engine.session_overrides == {
        "product": {"permission_mode": "bypass"},
        "llm": {"model": "override-model"},
    }
    assert dummy_agent.saved == []


def test_query_engine_new_session_does_not_autosave_until_dirty(tmp_path: Path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    project_root = tmp_path / "repo"
    project_root.mkdir()

    session_manager = _FakeSessionManager(record=None)
    dummy_agent = _DummyAgent()

    monkeypatch.setattr(query_engine, "get_s4_paths", lambda: paths)
    monkeypatch.setattr(query_engine, "S4SessionManager", lambda raw_paths: session_manager)

    def _detect(cls, cwd=None, git_binary: str = "git") -> ProjectContext:
        return _make_project(Path(cwd or project_root))

    monkeypatch.setattr(query_engine.ProjectContext, "detect", classmethod(_detect))

    def _resolve(raw_paths, *, project_root=None, session_overrides=None):
        settings = _settings()
        settings.product.session_auto_save = True
        return settings

    monkeypatch.setattr(query_engine, "resolve_settings", _resolve)
    monkeypatch.setattr(
        query_engine,
        "build_agent_bundle",
        lambda **kwargs: SimpleNamespace(
            agent=dummy_agent,
            registry=SimpleNamespace(
                get_tool_names=lambda: [],
                list_tool_specs=lambda: [],
                list_runtime_surfaces=lambda surface: {},
            ),
            task_service=SimpleNamespace(list_tasks=lambda limit=20: []),
            context_manager=None,
            runtime_notice_hook=None,
            startup_issues=[],
            restore_report=None,
        ),
    )

    engine = query_engine.S4QueryEngine(cwd=project_root)

    assert engine.session_id == "s4-repo-new"
    assert dummy_agent.saved == []

    engine.close()

    assert dummy_agent.saved == []


def test_query_engine_autosave_failure_degrades_gracefully(tmp_path: Path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    project_root = tmp_path / "repo"
    project_root.mkdir()

    session_manager = _FakeSessionManager(record=None)
    failing_agent = _DummyAgent()

    def _failing_save_session(session_id: str, *, store=None, metadata=None) -> None:
        raise PermissionError("readonly")

    failing_agent.save_session = _failing_save_session  # type: ignore[method-assign]

    monkeypatch.setattr(query_engine, "get_s4_paths", lambda: paths)
    monkeypatch.setattr(query_engine, "S4SessionManager", lambda raw_paths: session_manager)

    def _detect(cls, cwd=None, git_binary: str = "git") -> ProjectContext:
        return _make_project(Path(cwd or project_root))

    monkeypatch.setattr(query_engine.ProjectContext, "detect", classmethod(_detect))

    def _resolve(raw_paths, *, project_root=None, session_overrides=None):
        settings = _settings()
        settings.product.session_auto_save = True
        return settings

    monkeypatch.setattr(query_engine, "resolve_settings", _resolve)
    monkeypatch.setattr(
        query_engine,
        "build_agent_bundle",
        lambda **kwargs: SimpleNamespace(
            agent=failing_agent,
            registry=SimpleNamespace(
                get_tool_names=lambda: [],
                list_tool_specs=lambda: [],
                list_runtime_surfaces=lambda surface: {},
            ),
            task_service=SimpleNamespace(list_tasks=lambda limit=20: []),
            context_manager=None,
            runtime_notice_hook=None,
            startup_issues=[],
            restore_report=None,
        ),
    )

    engine = query_engine.S4QueryEngine(cwd=project_root)
    engine.create_checkpoint("save attempt")

    assert engine.settings.product.session_auto_save is False
    assert engine.bundle.startup_issues == [
        "Session persistence unavailable: PermissionError: readonly"
    ]


def test_query_engine_turn_skill_queue_is_ephemeral(tmp_path: Path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    project_root = tmp_path / "repo"
    project_root.mkdir()

    session_manager = _FakeSessionManager(record=None)
    agent = _LifecycleAgent()
    manifest = SimpleNamespace(
        name="reviewer",
        description="Review diffs",
        listing_description="Review code changes",
        when_to_use="When a focused review pass is needed",
        priority=10,
        exposure_mode="on_demand",
        execution_mode="tool",
        source_type="markdown",
        source_path=str(project_root / "skills" / "reviewer.md"),
        tool_names=[],
    )
    skill_registry = _FakeSkillRegistry(
        [manifest],
        {"reviewer": lambda: _FakeSkill("reviewer", body="Use reviewer guidance.")},
    )

    monkeypatch.setattr(query_engine, "get_s4_paths", lambda: paths)
    monkeypatch.setattr(query_engine, "S4SessionManager", lambda raw_paths: session_manager)
    monkeypatch.setattr(
        query_engine.ProjectContext,
        "detect",
        classmethod(lambda cls, cwd=None, git_binary="git": _make_project(Path(cwd or project_root))),
    )
    monkeypatch.setattr(query_engine, "resolve_settings", lambda *args, **kwargs: _settings())
    monkeypatch.setattr(
        query_engine,
        "build_agent_bundle",
        lambda **kwargs: SimpleNamespace(
            agent=agent,
            registry=SimpleNamespace(
                get_tool_names=lambda: [],
                list_tool_specs=lambda: [],
                list_runtime_surfaces=lambda surface: {},
            ),
            task_service=SimpleNamespace(list_tasks=lambda limit=20: []),
            context_manager=None,
            runtime_notice_hook=None,
            startup_issues=[],
            restore_report=None,
            skill_registry=skill_registry,
            skill_sources=(str(project_root / "skills"),),
        ),
    )

    engine = query_engine.S4QueryEngine(cwd=project_root)

    assert engine.queue_turn_skill("reviewer") == "Skill queued for the next turn: reviewer"
    assert engine.get_skill_choices()[0]["pending"] is True

    result = engine.run_prompt("Inspect the current changes.")

    assert result == "invoked"
    assert "## Turn Skills" in agent.invocations[-1]
    assert "### reviewer" in agent.invocations[-1]
    assert agent.skill_manager.has_skill("reviewer") is False
    assert engine.clear_turn_skills() == "No queued turn skills."


def test_query_engine_runtime_queries_are_cached_for_short_polling_windows(tmp_path: Path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    project_root = tmp_path / "repo"
    project_root.mkdir()

    session_manager = _FakeSessionManager(record=None)
    agent = _LifecycleAgent()
    runtime = _CountingAgentRuntime()
    task_service = _CountingTaskService()
    process_manager = _CountingProcessManager()
    agent.agent_runtime = runtime

    current_time = 100.0

    monkeypatch.setattr(query_engine, "get_s4_paths", lambda: paths)
    monkeypatch.setattr(query_engine, "S4SessionManager", lambda raw_paths: session_manager)
    monkeypatch.setattr(
        query_engine.ProjectContext,
        "detect",
        classmethod(lambda cls, cwd=None, git_binary="git": _make_project(Path(cwd or project_root))),
    )
    monkeypatch.setattr(query_engine, "resolve_settings", lambda *args, **kwargs: _settings())
    monkeypatch.setattr(query_engine.time, "monotonic", lambda: current_time)
    monkeypatch.setattr(
        query_engine,
        "build_agent_bundle",
        lambda **kwargs: SimpleNamespace(
            agent=agent,
            registry=SimpleNamespace(
                get_tool_names=lambda: ["Bash"],
                list_tool_specs=lambda: [],
                list_runtime_surfaces=lambda surface: {},
                get_tool=lambda name: (
                    SimpleNamespace(process_manager=process_manager)
                    if name == "Bash"
                    else None
                ),
            ),
            task_service=task_service,
            context_manager=None,
            runtime_notice_hook=None,
            startup_issues=[],
            restore_report=None,
            skill_registry=_FakeSkillRegistry([], {}),
            skill_sources=(),
        ),
    )

    engine = query_engine.S4QueryEngine(cwd=project_root)

    assert engine.get_agent_choices(limit=5) == engine.get_agent_choices(limit=5)
    assert runtime.calls == 1

    first_tasks = engine.get_task_choices(limit=5)
    second_tasks = engine.get_task_choices(limit=5)
    assert first_tasks == second_tasks
    assert task_service.calls == 1
    assert process_manager.calls == 1

    assert engine.has_live_runtime_activity() is True
    assert engine.has_live_runtime_activity() is True
    assert runtime.calls == 2
    assert task_service.calls == 1

    current_time = 100.5
    engine.get_agent_choices(limit=5)
    engine.get_task_choices(limit=5)
    assert runtime.calls == 3
    assert task_service.calls == 2
    assert process_manager.calls == 2

    engine.format_sidebar(force=True)
    assert runtime.calls == 4
    assert task_service.calls == 3
    assert process_manager.calls == 4


def test_query_engine_permission_rules_are_session_persisted(tmp_path: Path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    project_root = tmp_path / "repo"
    project_root.mkdir()

    session_manager = _FakeSessionManager(record=None)
    agent = _LifecycleAgent()

    monkeypatch.setattr(query_engine, "get_s4_paths", lambda: paths)
    monkeypatch.setattr(query_engine, "S4SessionManager", lambda raw_paths: session_manager)
    monkeypatch.setattr(
        query_engine.ProjectContext,
        "detect",
        classmethod(lambda cls, cwd=None, git_binary="git": _make_project(Path(cwd or project_root))),
    )
    monkeypatch.setattr(query_engine, "resolve_settings", lambda *args, **kwargs: _settings())
    monkeypatch.setattr(
        query_engine,
        "build_agent_bundle",
        lambda **kwargs: SimpleNamespace(
            agent=agent,
            registry=SimpleNamespace(
                get_tool_names=lambda: [],
                list_tool_specs=lambda: [],
                list_runtime_surfaces=lambda surface: {},
            ),
            task_service=SimpleNamespace(list_tasks=lambda limit=20: []),
            context_manager=None,
            runtime_notice_hook=None,
            startup_issues=[],
            restore_report=None,
            skill_registry=_FakeSkillRegistry([], {}),
            skill_sources=(),
        ),
    )

    engine = query_engine.S4QueryEngine(cwd=project_root)

    message = engine.add_permission_rule_from_tokens(
        behavior="allow",
        tool_name="WebFetch",
        tokens=["host=example.com", "source=session", "desc=docs"],
    )

    assert "allow WebFetch" in message
    assert engine.session_overrides["product"]["permission_rules"] == [
        {
            "tool_name": "WebFetch",
            "behavior": "allow",
            "matcher": {"hosts": ["example.com"]},
            "source": "session",
            "description": "docs",
        }
    ]
    assert engine.settings.product.permission_rules[0].matcher == {"hosts": ["example.com"]}
    assert engine.get_permission_status_payload()["ruleCount"] == 1
    assert "rule_added" in engine.format_permission_history()

    assert engine.update_permission_mode("dont_ask") == "Permission mode set to dont_ask"
    assert engine.session_overrides["product"]["permission_mode"] == "dont_ask"
    assert agent.permission_context.mode == PermissionMode.DONT_ASK

    assert engine.clear_permission_rules(source="session") == "Permission rules cleared: session"
    assert engine.session_overrides["product"]["permission_rules"] == []
    assert engine.get_permission_status_payload()["ruleCount"] == 0


def test_query_engine_theme_switch_is_session_persisted(tmp_path: Path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    project_root = tmp_path / "repo"
    project_root.mkdir()

    session_manager = _FakeSessionManager(record=None)
    agent = _LifecycleAgent()

    monkeypatch.setattr(query_engine, "get_s4_paths", lambda: paths)
    monkeypatch.setattr(query_engine, "S4SessionManager", lambda raw_paths: session_manager)
    monkeypatch.setattr(
        query_engine.ProjectContext,
        "detect",
        classmethod(lambda cls, cwd=None, git_binary="git": _make_project(Path(cwd or project_root))),
    )
    monkeypatch.setattr(query_engine, "resolve_settings", lambda *args, **kwargs: _settings())
    monkeypatch.setattr(
        query_engine,
        "build_agent_bundle",
        lambda **kwargs: SimpleNamespace(
            agent=agent,
            registry=SimpleNamespace(
                get_tool_names=lambda: [],
                list_tool_specs=lambda: [],
                list_runtime_surfaces=lambda surface: {},
                get_tool=lambda name: None,
            ),
            task_service=SimpleNamespace(list_tasks=lambda limit=20: []),
            context_manager=None,
            runtime_notice_hook=None,
            startup_issues=[],
            restore_report=None,
            skill_registry=_FakeSkillRegistry([], {}),
            skill_sources=(),
        ),
    )

    engine = query_engine.S4QueryEngine(cwd=project_root)

    message = engine.update_theme("ember")

    assert message == "Theme set to ember"
    assert engine.settings.ui.theme == "ember"
    assert engine.session_overrides["ui"]["theme"] == "ember"
    assert agent.saved[-1]["metadata"]["session_overrides"]["ui"]["theme"] == "ember"
    assert "* ember" in engine.format_themes()


def test_query_engine_resume_closes_previous_bundle_and_close_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    current_root = tmp_path / "current"
    restored_root = tmp_path / "restored"
    current_root.mkdir()
    restored_root.mkdir()

    session_record = {
        "metadata": {
            "project_root": str(restored_root),
            "title": "Restored Session",
            "session_overrides": {},
        }
    }
    session_manager = _FakeSessionManager(record=session_record)
    agent_first = _LifecycleAgent()
    agent_second = _LifecycleAgent()
    bundles = [
        SimpleNamespace(
            agent=agent_first,
            registry=SimpleNamespace(
                get_tool_names=lambda: [],
                list_tool_specs=lambda: [],
                list_runtime_surfaces=lambda surface: {},
            ),
            task_service=SimpleNamespace(list_tasks=lambda limit=20: []),
            context_manager=None,
            runtime_notice_hook=None,
            startup_issues=[],
            restore_report=None,
            skill_registry=_FakeSkillRegistry([], {}),
            skill_sources=(),
        ),
        SimpleNamespace(
            agent=agent_second,
            registry=SimpleNamespace(
                get_tool_names=lambda: [],
                list_tool_specs=lambda: [],
                list_runtime_surfaces=lambda surface: {},
            ),
            task_service=SimpleNamespace(list_tasks=lambda limit=20: []),
            context_manager=None,
            runtime_notice_hook=None,
            startup_issues=[],
            restore_report=None,
            skill_registry=_FakeSkillRegistry([], {}),
            skill_sources=(),
        ),
    ]

    monkeypatch.setattr(query_engine, "get_s4_paths", lambda: paths)
    monkeypatch.setattr(query_engine, "S4SessionManager", lambda raw_paths: session_manager)
    monkeypatch.setattr(
        query_engine.ProjectContext,
        "detect",
        classmethod(lambda cls, cwd=None, git_binary="git": _make_project(Path(cwd or current_root))),
    )
    monkeypatch.setattr(query_engine, "resolve_settings", lambda *args, **kwargs: _settings())
    monkeypatch.setattr(query_engine, "build_agent_bundle", lambda **kwargs: bundles.pop(0))

    engine = query_engine.S4QueryEngine(cwd=current_root)

    message = engine.resume_session("sess-restored")

    assert "Resumed session sess-restored" in message
    assert agent_first.close_calls == 1
    assert engine.was_restored is True
    assert engine.project.project_root == restored_root.resolve()
    assert engine._closed is False

    report = engine.close()
    assert report["metadata"]["sessionId"] == "sess-restored"
    assert agent_second.close_calls == 1
    assert engine.close() == report
    assert agent_second.close_calls == 1


def test_query_engine_checkpoints_persist_and_rewind_history(tmp_path: Path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    project_root = tmp_path / "repo"
    project_root.mkdir()

    session_manager = _FakeSessionManager(record=None)
    agent = _LifecycleAgent()

    monkeypatch.setattr(query_engine, "get_s4_paths", lambda: paths)
    monkeypatch.setattr(query_engine, "S4SessionManager", lambda raw_paths: session_manager)
    monkeypatch.setattr(
        query_engine.ProjectContext,
        "detect",
        classmethod(lambda cls, cwd=None, git_binary="git": _make_project(Path(cwd or project_root))),
    )
    monkeypatch.setattr(query_engine, "resolve_settings", lambda *args, **kwargs: _settings())
    monkeypatch.setattr(
        query_engine,
        "build_agent_bundle",
        lambda **kwargs: SimpleNamespace(
            agent=agent,
            registry=SimpleNamespace(
                get_tool_names=lambda: [],
                list_tool_specs=lambda: [],
                list_runtime_surfaces=lambda surface: {},
                get_tool=lambda name: None,
            ),
            task_service=SimpleNamespace(list_tasks=lambda limit=20: []),
            context_manager=None,
            runtime_notice_hook=None,
            startup_issues=[],
            restore_report=None,
            skill_registry=_FakeSkillRegistry([], {}),
            skill_sources=(),
        ),
    )

    engine = query_engine.S4QueryEngine(cwd=project_root)
    agent.history = [{"role": "user", "content": "before"}]

    checkpoint = engine.create_checkpoint("safe point")
    agent.history.append({"role": "assistant", "content": "after"})

    message = engine.rewind_to_checkpoint(checkpoint["checkpoint_id"])

    assert "Rewound to cp-001" in message
    assert agent.history == [{"role": "user", "content": "before"}]
    assert engine.session_overrides["_s4code"]["checkpoints"][0]["checkpoint_id"] == "cp-001"
    assert "cp-001" in engine.format_checkpoints()
    assert "cp-001" in engine.format_timeline()


def test_query_engine_mcp_status_includes_disabled_and_unregistered_servers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _paths(tmp_path)
    project_root = tmp_path / "repo"
    project_root.mkdir()

    session_manager = _FakeSessionManager(record=None)
    agent = _LifecycleAgent()
    docs_manager = _FakeMCPManager(
        "docs",
        tools=[{"name": "search_docs"}],
        resources=[{"uri": "docs://index"}],
        prompts=[{"name": "summarize"}],
    )
    settings = _settings(
        mcp_servers=[
            MCPServerSettings(name="docs", server_source="python", server_args=["docs.py"]),
            MCPServerSettings(name="graph", server_source="python", server_args=["graph.py"], enabled=False),
            MCPServerSettings(name="stale", server_source="python", server_args=["stale.py"]),
        ]
    )

    monkeypatch.setattr(query_engine, "get_s4_paths", lambda: paths)
    monkeypatch.setattr(query_engine, "S4SessionManager", lambda raw_paths: session_manager)
    monkeypatch.setattr(
        query_engine.ProjectContext,
        "detect",
        classmethod(lambda cls, cwd=None, git_binary="git": _make_project(Path(cwd or project_root))),
    )
    monkeypatch.setattr(query_engine, "resolve_settings", lambda *args, **kwargs: settings)
    monkeypatch.setattr(
        query_engine,
        "build_agent_bundle",
        lambda **kwargs: SimpleNamespace(
            agent=agent,
            registry=SimpleNamespace(
                get_tool_names=lambda: [],
                list_tool_specs=lambda: [],
                list_runtime_surfaces=lambda surface: {"docs": docs_manager} if surface == "mcp_manager" else {},
                get_tool=lambda name: None,
            ),
            task_service=SimpleNamespace(list_tasks=lambda limit=20: []),
            context_manager=None,
            runtime_notice_hook=None,
            startup_issues=[],
            restore_report=None,
            skill_registry=_FakeSkillRegistry([], {}),
            skill_sources=(),
        ),
    )

    engine = query_engine.S4QueryEngine(cwd=project_root)
    payload = engine.get_mcp_status_payload()

    assert [item["server_name"] for item in payload] == ["docs", "graph", "stale"]
    assert payload[0]["status"] == "connected"
    assert payload[0]["tool_count"] == 1
    assert payload[0]["resource_count"] == 1
    assert payload[0]["prompt_count"] == 1
    assert payload[1]["status"] == "disabled"
    assert payload[1]["enabled"] is False
    assert payload[2]["status"] == "unregistered"
    assert payload[2]["enabled"] is True
    assert "graph | disabled" in engine.format_mcp()
    assert "stale | unregistered" in engine.format_mcp()


def test_query_engine_mcp_commands_report_disabled_and_unregistered_servers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _paths(tmp_path)
    project_root = tmp_path / "repo"
    project_root.mkdir()

    session_manager = _FakeSessionManager(record=None)
    agent = _LifecycleAgent()
    docs_manager = _FakeMCPManager(
        "docs",
        tools=[{"name": "search_docs"}],
        resources=[{"uri": "docs://index"}],
    )
    settings = _settings(
        mcp_servers=[
            MCPServerSettings(name="docs", server_source="python", server_args=["docs.py"]),
            MCPServerSettings(name="graph", server_source="python", server_args=["graph.py"], enabled=False),
            MCPServerSettings(name="stale", server_source="python", server_args=["stale.py"]),
        ]
    )

    monkeypatch.setattr(query_engine, "get_s4_paths", lambda: paths)
    monkeypatch.setattr(query_engine, "S4SessionManager", lambda raw_paths: session_manager)
    monkeypatch.setattr(
        query_engine.ProjectContext,
        "detect",
        classmethod(lambda cls, cwd=None, git_binary="git": _make_project(Path(cwd or project_root))),
    )
    monkeypatch.setattr(query_engine, "resolve_settings", lambda *args, **kwargs: settings)
    monkeypatch.setattr(
        query_engine,
        "build_agent_bundle",
        lambda **kwargs: SimpleNamespace(
            agent=agent,
            registry=SimpleNamespace(
                get_tool_names=lambda: [],
                list_tool_specs=lambda: [],
                list_runtime_surfaces=lambda surface: {"docs": docs_manager} if surface == "mcp_manager" else {},
                get_tool=lambda name: None,
            ),
            task_service=SimpleNamespace(list_tasks=lambda limit=20: []),
            context_manager=None,
            runtime_notice_hook=None,
            startup_issues=[],
            restore_report=None,
            skill_registry=_FakeSkillRegistry([], {}),
            skill_sources=(),
        ),
    )

    engine = query_engine.S4QueryEngine(cwd=project_root)

    detail = engine.format_mcp_server_detail("graph")
    assert "Enabled: False" in detail
    assert "Status: disabled" in detail
    assert "Runtime: configured but disabled" in detail
    assert engine.format_mcp_tools("graph") == "MCP server 'graph' is configured but disabled."
    assert engine.format_mcp_resources("stale") == (
        "MCP server 'stale' is configured but not registered in the runtime."
    )

    connect_output = engine.connect_mcp()
    assert "docs | connected" in connect_output
    assert "graph | disabled" in connect_output
    assert "stale | unregistered" in connect_output
    assert docs_manager.connect_calls == 1

    disconnect_output = engine.disconnect_mcp()
    assert "docs | disconnected" in disconnect_output
    assert "graph | disabled" in disconnect_output
    assert "stale | unregistered" in disconnect_output
    assert docs_manager.close_calls == 1

    refresh_output = engine.refresh_mcp()
    assert "docs | refreshed | tools=1 resources=1 prompts=0" in refresh_output
    assert "graph | disabled" in refresh_output
    assert "stale | unregistered" in refresh_output
    assert docs_manager.snapshot_refresh_calls[-1] is True


def test_query_engine_mcp_startup_notice_and_sidebar_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _paths(tmp_path)
    project_root = tmp_path / "repo"
    project_root.mkdir()

    session_manager = _FakeSessionManager(record=None)
    agent = _LifecycleAgent()
    docs_manager = _FakeMCPManager("docs")
    settings = _settings(
        mcp_servers=[
            MCPServerSettings(name="docs", server_source="python", server_args=["docs.py"]),
            MCPServerSettings(name="graph", server_source="python", server_args=["graph.py"], enabled=False),
            MCPServerSettings(name="stale", server_source="python", server_args=["stale.py"]),
        ]
    )

    monkeypatch.setattr(query_engine, "get_s4_paths", lambda: paths)
    monkeypatch.setattr(query_engine, "S4SessionManager", lambda raw_paths: session_manager)
    monkeypatch.setattr(
        query_engine.ProjectContext,
        "detect",
        classmethod(lambda cls, cwd=None, git_binary="git": _make_project(Path(cwd or project_root))),
    )
    monkeypatch.setattr(query_engine, "resolve_settings", lambda *args, **kwargs: settings)
    monkeypatch.setattr(
        query_engine,
        "build_agent_bundle",
        lambda **kwargs: SimpleNamespace(
            agent=agent,
            registry=SimpleNamespace(
                get_tool_names=lambda: [],
                list_tool_specs=lambda: [],
                list_runtime_surfaces=lambda surface: {"docs": docs_manager} if surface == "mcp_manager" else {},
                get_tool=lambda name: None,
            ),
            task_service=SimpleNamespace(list_tasks=lambda limit=20: []),
            context_manager=None,
            runtime_notice_hook=None,
            startup_issues=[],
            restore_report=None,
            skill_registry=_FakeSkillRegistry([], {}),
            skill_sources=(),
        ),
    )

    engine = query_engine.S4QueryEngine(cwd=project_root)
    notices = engine.get_startup_notices()
    sidebar = engine.format_sidebar()

    mcp_notice = next(item for item in notices if item["title"] == "MCP Startup")
    assert mcp_notice["kind"] == "warning"
    assert "Configured 3 MCP server(s): 1 connected, 1 disabled, 1 unavailable." in mcp_notice["body"]
    assert "- stale: unregistered" in mcp_notice["body"]
    assert "Use /mcp for details." in mcp_notice["body"]
    assert "MCP: 3 configured | 1 connected | 1 disabled | 1 unavailable" in sidebar


class _StreamingLifecycleAgent(_LifecycleAgent):
    async def astream_invoke_with_tool(self, prompt: str, *, max_iter: int = 20, **kwargs):
        self.history.append({"role": "user", "content": prompt})
        yield {"type": "round_start", "round": 1}
        yield {
            "type": "tool_call",
            "tool_name": "Bash",
            "tool_id": "tool-1",
            "tool_args": {"command": "python rewrite.py"},
        }
        yield {
            "type": "tool_result",
            "tool_name": "Bash",
            "tool_id": "tool-1",
            "content": "done",
            "status": "success",
            "structured_data": {"return_code": 0},
        }
        self.history.append({"role": "assistant", "content": "finished"})
        yield {"type": "final", "content": "finished"}


def test_stream_prompt_emits_bash_diff_and_checkpoints_without_runtime_card(tmp_path: Path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    project_root = tmp_path / "repo"
    project_root.mkdir()

    session_manager = _FakeSessionManager(record=None)
    agent = _StreamingLifecycleAgent()

    monkeypatch.setattr(query_engine, "get_s4_paths", lambda: paths)
    monkeypatch.setattr(query_engine, "S4SessionManager", lambda raw_paths: session_manager)
    monkeypatch.setattr(
        query_engine.ProjectContext,
        "detect",
        classmethod(lambda cls, cwd=None, git_binary="git": _make_project(Path(cwd or project_root))),
    )
    monkeypatch.setattr(query_engine, "resolve_settings", lambda *args, **kwargs: _settings())
    monkeypatch.setattr(
        query_engine,
        "build_agent_bundle",
        lambda **kwargs: SimpleNamespace(
            agent=agent,
            registry=SimpleNamespace(
                get_tool_names=lambda: [],
                list_tool_specs=lambda: [],
                list_runtime_surfaces=lambda surface: {},
                get_tool=lambda name: None,
            ),
            task_service=SimpleNamespace(list_tasks=lambda limit=20: []),
            context_manager=None,
            runtime_notice_hook=None,
            startup_issues=[],
            restore_report=None,
            skill_registry=_FakeSkillRegistry([], {}),
            skill_sources=(),
        ),
    )

    engine = query_engine.S4QueryEngine(cwd=project_root)
    diffs = iter(
        [
            "No diff.",
            "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new",
        ]
    )

    def _get_diff(self, target=None, *, max_lines: int = 400) -> str:
        return next(diffs, "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new")

    monkeypatch.setattr(query_engine.ProjectContext, "get_diff", _get_diff)

    async def _collect() -> list[dict[str, object]]:
        return [event async for event in engine.stream_prompt("change something")]

    events = asyncio.run(_collect())
    tool_result = next(event for event in events if event.get("type") == "tool_result")

    assert tool_result["structured_data"]["diff"]["relative_path"] == "Working tree diff after Bash"
    assert not any(event.get("type") == "runtime_snapshot" for event in events)
    assert [event.get("type") for event in events].count("checkpoint") == 2
    assert len(engine.get_checkpoint_choices()) == 2
