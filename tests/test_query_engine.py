from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import s4code.query_engine as query_engine
from s4code.config import S4Settings
from s4code.paths import S4Paths
from s4code.project import ProjectContext


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
        settings = S4Settings()
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


def test_query_engine_new_session_autosaves_immediately(tmp_path: Path, monkeypatch) -> None:
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
        settings = S4Settings()
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
    assert len(dummy_agent.saved) == 1
    assert dummy_agent.saved[0]["session_id"] == "s4-repo-new"
    assert dummy_agent.saved[0]["metadata"]["project_root"] == str(project_root.resolve())


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
        settings = S4Settings()
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

    assert engine.settings.product.session_auto_save is False
    assert engine.bundle.startup_issues == [
        "Session persistence unavailable: PermissionError: readonly"
    ]
