from pathlib import Path
from types import SimpleNamespace
from s4code.core.configuration import S4ConfigLoader
from s4code.core.project import ProjectContext

from s4code.interfaces.terminal.settings import (
    LLMSettings,
    ProductSettings,
    S4Settings,
    dump_settings_yaml,
    resolve_settings,
    save_settings,
)
from s4code.core.paths import S4Paths


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


def _llm(provider: str = "openai", model: str = "global-model") -> LLMSettings:
    return LLMSettings(
        provider=provider,
        model=model,
        base_url=None,
        api_key=None,
        temperature=None,
        max_tokens=None,
        timeout=None,
        reasoning_effort=None,
        reasoning_summary=None,
    )


def _settings() -> S4Settings:
    llm = _llm()
    return S4Settings(
        active_model_profile="default",
        model_profiles={"default": llm},
        llm=llm,
    )


def test_core_loader_uses_detected_repository_root(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    nested = root / "src"
    nested.mkdir(parents=True)
    config = root / ".s4code" / "config.yaml"
    config.parent.mkdir()
    config.write_text(
        "llm:\n  provider: openai\n  model: repository-model\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        ProjectContext, "detect", lambda workspace: SimpleNamespace(project_root=root)
    )
    result = S4ConfigLoader(_paths(tmp_path)).load_agent_settings(nested)
    assert result.llm.model == "repository-model"
    assert not hasattr(result, "ui")


def test_resolve_settings_merges_yaml_global_project_and_session_with_profiles(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    project_root = tmp_path / "repo"
    project_root.mkdir()

    save_settings(
        paths.global_config_path,
        S4Settings(
            active_model_profile="default",
            model_profiles={
                "default": _llm("openai", "global-model"),
                "claude": _llm("anthropic_native", "claude-sonnet"),
            },
            llm=_llm("openai", "global-model"),
            product=ProductSettings(permission_mode="accept_edits"),
        ),
    )

    project_config = project_root / ".s4code" / "config.yaml"
    project_config.parent.mkdir(parents=True)
    project_config.write_text(
        "\n".join(
            [
                "active_model_profile: claude",
                "product:",
                "  permission_mode: bypass",
                "ui:",
                "  theme: project-theme",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    resolved = resolve_settings(
        paths,
        project_root=project_root,
        session_overrides={"llm": {"model": "session-model"}},
    )
    assert resolved.active_model_profile == "claude"
    assert resolved.llm.provider == "anthropic_native"
    assert resolved.llm.model == "session-model"
    assert resolved.product.permission_mode == "bypass"
    assert resolved.ui.theme == "project-theme"


def test_resolve_settings_supports_legacy_llm_payload_without_profiles(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    paths.global_config_path.write_text(
        "\n".join(
            [
                "llm:",
                "  provider: google_native",
                "  model: gemini-2.5-pro",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    resolved = resolve_settings(paths)
    assert resolved.active_model_profile == "default"
    assert "default" in resolved.model_profiles
    assert resolved.llm.provider == "google_native"
    assert resolved.llm.model == "gemini-2.5-pro"
    assert resolved.llm.reasoning_effort == "medium"
    assert resolved.ui.show_thinking is True


def test_resolve_settings_allows_disabling_default_reasoning(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.global_config_path.write_text(
        "\n".join(
            [
                "model_profiles:",
                "  default:",
                "    provider: openai",
                "    model: gpt-4.1",
                "    reasoning_effort: null",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    resolved = resolve_settings(paths)

    assert resolved.llm.reasoning_effort is None


def test_resolve_settings_supports_split_config_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    project_root = tmp_path / "repo"
    project_root.mkdir()

    (paths.config_dir / "models.yaml").write_text(
        "\n".join(
            [
                "active_model_profile: default",
                "model_profiles:",
                "  default:",
                "    provider: openai",
                "    model: gpt-4.1",
                "  local:",
                "    provider: openai",
                "    model: qwen-local",
                "    base_url: http://127.0.0.1:8000/v1",
                "    api_key: local-key",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (paths.config_dir / "product.yaml").write_text(
        "\n".join(
            [
                "permission_mode: accept_edits",
                "enable_mcp: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (paths.config_dir / "context.yaml").write_text(
        "\n".join(
            [
                "max_tokens: 32000",
                "recent_turns: 6",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (paths.config_dir / "ui.yaml").write_text(
        "\n".join(
            [
                "theme: graphite",
                "show_thinking: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    project_config_dir = project_root / ".s4code"
    project_config_dir.mkdir(parents=True)
    (project_config_dir / "models.yaml").write_text(
        "\n".join(
            [
                "active_model_profile: local",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (project_config_dir / "ui.yaml").write_text(
        "\n".join(
            [
                "ui:",
                "  theme: ember",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    resolved = resolve_settings(paths, project_root=project_root)

    assert resolved.active_model_profile == "local"
    assert resolved.llm.model == "qwen-local"
    assert resolved.context.max_tokens == 32000
    assert resolved.context.recent_turns == 6
    assert resolved.product.permission_mode == "accept_edits"
    assert resolved.ui.theme == "ember"
    assert resolved.ui.show_thinking is False


def test_split_config_files_override_same_scope_config_yaml(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    paths.global_config_path.write_text(
        "\n".join(
            [
                "active_model_profile: default",
                "model_profiles:",
                "  default:",
                "    provider: openai",
                "    model: yaml-model",
                "context:",
                "  max_tokens: 24000",
                "ui:",
                "  theme: yaml-theme",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (paths.config_dir / "context.yaml").write_text(
        "max_tokens: 48000\n",
        encoding="utf-8",
    )
    (paths.config_dir / "ui.yaml").write_text(
        "theme: split-theme\n",
        encoding="utf-8",
    )

    resolved = resolve_settings(paths)

    assert resolved.llm.model == "yaml-model"
    assert resolved.context.max_tokens == 48000
    assert resolved.ui.theme == "split-theme"


def test_resolve_settings_merges_global_and_project_mcp_json_by_server_name(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    project_root = tmp_path / "repo"
    project_root.mkdir()

    paths.global_mcp_config_path.write_text(
        "\n".join(
            [
                "{",
                '  "servers": [',
                '    {"name": "docs", "server_source": "python", "server_args": ["global.py"], "tool_prefix": "docs_", "persist_connection": true},',
                '    {"name": "fs", "server_source": "python", "server_args": ["fs.py"], "include_resources": true}',
                "  ]",
                "}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    project_mcp_path = project_root / ".s4code" / "mcp.json"
    project_mcp_path.parent.mkdir(parents=True)
    project_mcp_path.write_text(
        "\n".join(
            [
                "{",
                '  "servers": [',
                '    {"name": "docs", "server_args": ["project.py"], "include_resources": false},',
                '    {"name": "graph", "server_source": "python", "server_args": ["graph.py"], "enabled": false}',
                "  ]",
                "}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    save_settings(paths.global_config_path, _settings())
    resolved = resolve_settings(paths, project_root=project_root)

    assert [server.name for server in resolved.mcp_servers] == ["docs", "fs", "graph"]
    docs = resolved.mcp_servers[0]
    assert docs.server_args == ["project.py"]
    assert docs.tool_prefix == "docs_"
    assert docs.persist_connection is True
    assert docs.include_resources is False
    fs = resolved.mcp_servers[1]
    assert fs.server_source == "python"
    assert fs.include_resources is True
    graph = resolved.mcp_servers[2]
    assert graph.enabled is False


def test_resolve_settings_accepts_extra_metadata_in_mcp_catalog_entries(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    save_settings(paths.global_config_path, _settings())
    paths.global_mcp_config_path.write_text(
        "\n".join(
            [
                "{",
                '  "name": "catalog",',
                '  "notes": ["template"],',
                '  "servers": [',
                '    {"name": "github", "server_source": "https://api.githubcopilot.com/mcp/", "transport_type": "http", "enabled": false, "tags": ["official-vendor"], "why": "template", "source_url": "https://github.com/github/github-mcp-server"}',
                "  ]",
                "}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    resolved = resolve_settings(paths)

    assert len(resolved.mcp_servers) == 1
    assert resolved.mcp_servers[0].name == "github"
    assert resolved.mcp_servers[0].transport_type == "http"
    assert resolved.mcp_servers[0].enabled is False


def test_save_settings_writes_yaml(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    settings = _settings()
    save_settings(paths.global_config_path, settings)
    content = paths.global_config_path.read_text(encoding="utf-8")
    assert "active_model_profile:" in content
    assert "model_profiles:" in content
    assert "context:" in content
    assert dump_settings_yaml(settings).startswith("active_model_profile:")


def test_resolve_settings_requires_llm_configuration(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    try:
        resolve_settings(paths)
    except ValueError as exc:
        assert "LLM 配置缺失" in str(exc)
    else:
        raise AssertionError(
            "resolve_settings should require explicit LLM configuration"
        )
