from s4code.config import LLMSettings, MCPServerSettings, S4Settings
from s4code.easyagent_adapter import _connect_registered_mcp_servers, _register_mcp_servers


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
