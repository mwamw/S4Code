from pathlib import Path

from s4code.config import LLMSettings, MCPServerSettings, S4Settings
from s4code.easyagent_adapter import (
    SkillManager,
    SkillRegistry,
    ToolRegistry,
    _connect_registered_mcp_servers,
    _preregister_meta_skill,
    _register_mcp_servers,
    _register_worktree_tools_if_enabled,
)
from s4code.project import ProjectContext


class _FakeRegistry:
    def __init__(self) -> None:
        self._surfaces: dict[str, dict[str, object]] = {}

    def register_runtime_surface(self, surface: str, name: str, value: object) -> None:
        self._surfaces.setdefault(surface, {})[name] = value

    def list_runtime_surfaces(self, surface: str):
        return dict(self._surfaces.get(surface, {}))


class _FakeHub:
    pass


class _FakeMCPToolManager:
    instances: list["_FakeMCPToolManager"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = dict(kwargs)
        self.client = self
        self.connect_calls = 0
        self.closed = False
        self.connected = False
        self.registry_server_name = ""
        _FakeMCPToolManager.instances.append(self)

    def is_connected(self) -> bool:
        return self.connected

    def connect(self) -> None:
        self.connect_calls += 1
        self.connected = True

    def close(self) -> dict[str, object]:
        self.closed = True
        self.connected = False
        return {"status": "closed"}

    def register_to_registry(self, registry, *, hub=None, server_name=None, legacy_resource_tools=None) -> None:
        self.registry_server_name = str(server_name or "mcp")
        self.hub = hub
        self.legacy_resource_tools = legacy_resource_tools
        registry.register_runtime_surface("mcp_manager", self.registry_server_name, self)


def _settings() -> S4Settings:
    llm = LLMSettings(
        provider="openai",
        model="gpt-4.1",
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
        mcp_servers=[
            MCPServerSettings(
                name="docs",
                server_source="python",
                server_args=["docs.py"],
                persist_connection=True,
                include_resources=True,
            ),
            MCPServerSettings(
                name="disabled",
                server_source="python",
                server_args=["disabled.py"],
                enabled=False,
            ),
        ],
    )


def test_register_mcp_servers_uses_manual_connect_and_hub(monkeypatch) -> None:
    registry = _FakeRegistry()
    startup_issues: list[str] = []
    settings = _settings()
    _FakeMCPToolManager.instances.clear()

    monkeypatch.setattr("s4code.easyagent_adapter.MCPHub", _FakeHub)
    monkeypatch.setattr("s4code.easyagent_adapter.MCPToolManager", _FakeMCPToolManager)

    _register_mcp_servers(
        registry,
        settings=settings,
        startup_issues=startup_issues,
    )

    assert startup_issues == []
    assert len(_FakeMCPToolManager.instances) == 1
    manager = _FakeMCPToolManager.instances[0]
    assert manager.kwargs["auto_connect"] is False
    assert manager.kwargs["persist_connection"] is True
    assert manager.connect_calls == 1
    assert manager.registry_server_name == "docs"
    assert isinstance(manager.hub, _FakeHub)
    assert manager.legacy_resource_tools is False
    assert "docs" in registry.list_runtime_surfaces("mcp_manager")


def test_connect_registered_mcp_servers_connects_disconnected_only() -> None:
    registry = _FakeRegistry()
    startup_issues: list[str] = []
    disconnected = _FakeMCPToolManager(server_source="python")
    connected = _FakeMCPToolManager(server_source="python")
    connected.connected = True
    registry.register_runtime_surface("mcp_manager", "docs", disconnected)
    registry.register_runtime_surface("mcp_manager", "graph", connected)

    _connect_registered_mcp_servers(
        registry,
        startup_issues=startup_issues,
    )

    assert startup_issues == []
    assert disconnected.connect_calls == 1
    assert connected.connect_calls == 0


def test_preregister_meta_skill_registers_skill_and_tools() -> None:
    registry = ToolRegistry()
    skill_registry = SkillRegistry()
    skill_manager = SkillManager()
    skill_manager.bind_registry(skill_registry)
    startup_issues: list[str] = []

    _preregister_meta_skill(
        registry=registry,
        skill_registry=skill_registry,
        skill_manager=skill_manager,
        startup_issues=startup_issues,
    )

    assert startup_issues == []
    assert skill_manager.has_skill("meta_skill")
    assert registry.has_tool("skill_discovery_tool")
    assert registry.has_tool("skill_tool")
    assert registry.has_tool("load_skill_tool")
    assert registry.has_tool("unload_skill_tool")


def test_register_worktree_tools_if_enabled(monkeypatch, tmp_path) -> None:
    registry = ToolRegistry()
    startup_issues: list[str] = []
    calls: dict[str, object] = {}

    class _FakeWorktreeManager:
        def __init__(self, repo_root, *, git_binary="git", original_cwd=None):
            calls["repo_root"] = repo_root
            calls["git_binary"] = git_binary
            calls["original_cwd"] = original_cwd

        @staticmethod
        def detect_repo_root(workspace_root, *, git_binary="git"):
            calls["detect_workspace_root"] = workspace_root
            calls["detect_git_binary"] = git_binary
            return workspace_root

    def _register_worktree_tools(registry_obj, *, worktree_manager):
        calls["registered"] = True
        registry_obj.register_runtime_surface("worktree_manager", "primary", worktree_manager)

    monkeypatch.setattr("Tool.runtime.WorktreeManager", _FakeWorktreeManager)
    monkeypatch.setattr("s4code.easyagent_adapter.register_worktree_tools", _register_worktree_tools)

    project_root = tmp_path / "repo"
    project_root.mkdir()
    project = ProjectContext(
        cwd=project_root,
        project_root=project_root,
        git_root=project_root,
        git_available=True,
        is_git_repo=True,
        branch="main",
        git_binary="git",
    )

    _register_worktree_tools_if_enabled(
        registry,
        project=project,
        settings=_settings(),
        startup_issues=startup_issues,
    )

    assert startup_issues == []
    assert calls["detect_workspace_root"] == str(project_root)
    assert calls["registered"] is True
    assert registry.list_runtime_surfaces("worktree_manager")
