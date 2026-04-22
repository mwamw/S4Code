from pathlib import Path

from s4code.config import (
    LLMSettings,
    ProductSettings,
    S4Settings,
    dump_settings_yaml,
    resolve_settings,
    save_settings,
)
from s4code.paths import S4Paths


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


def test_resolve_settings_merges_yaml_global_project_and_session_with_profiles(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    project_root = tmp_path / "repo"
    project_root.mkdir()

    save_settings(
        paths.global_config_path,
        S4Settings(
            active_model_profile="default",
            model_profiles={
                "default": LLMSettings(provider="openai", model="global-model"),
                "claude": LLMSettings(provider="anthropic_native", model="claude-sonnet"),
            },
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


def test_resolve_settings_supports_legacy_llm_payload_without_profiles(tmp_path: Path) -> None:
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


def test_save_settings_writes_yaml(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    save_settings(paths.global_config_path, S4Settings())
    content = paths.global_config_path.read_text(encoding="utf-8")
    assert "active_model_profile:" in content
    assert "model_profiles:" in content
    assert "context:" in content
    assert dump_settings_yaml(S4Settings()).startswith("active_model_profile:")
