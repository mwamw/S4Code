from pathlib import Path

from s4code.config import LLMSettings, ProductSettings, S4Settings, resolve_settings, save_settings
from s4code.paths import S4Paths


def _paths(tmp_path: Path) -> S4Paths:
    return S4Paths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        global_config_path=tmp_path / "config" / "config.json",
        session_db_path=tmp_path / "data" / "sessions.db",
        task_db_path=tmp_path / "data" / "tasks.db",
        agent_storage_dir=tmp_path / "data" / "agents",
        logs_dir=tmp_path / "data" / "logs",
    ).ensure()


def test_resolve_settings_merges_global_project_and_session(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    project_root = tmp_path / "repo"
    project_root.mkdir()

    save_settings(
        paths.global_config_path,
        S4Settings(
            llm=LLMSettings(provider="openai", model="global-model"),
            product=ProductSettings(permission_mode="accept_edits"),
        ),
    )

    project_config = project_root / ".s4code" / "config.json"
    project_config.parent.mkdir(parents=True)
    project_config.write_text(
        '{"product": {"permission_mode": "bypass"}, "ui": {"theme": "project-theme"}}',
        encoding="utf-8",
    )

    resolved = resolve_settings(
        paths,
        project_root=project_root,
        session_overrides={"llm": {"model": "session-model"}},
    )
    assert resolved.llm.model == "session-model"
    assert resolved.product.permission_mode == "bypass"
    assert resolved.ui.theme == "project-theme"
