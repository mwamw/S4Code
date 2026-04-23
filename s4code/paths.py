"""Filesystem locations for S4Code."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _xdg_dir(env_name: str, default_suffix: str) -> Path:
    raw = os.getenv(env_name)
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / default_suffix).resolve()


@dataclass(slots=True)
class S4Paths:
    config_dir: Path
    data_dir: Path
    cache_dir: Path
    global_config_path: Path
    session_db_path: Path
    task_db_path: Path
    agent_storage_dir: Path
    logs_dir: Path
    skills_dir: Path | None = None
    global_mcp_config_path: Path | None = None

    def ensure(self) -> "S4Paths":
        if self.skills_dir is None:
            self.skills_dir = self.data_dir / "skills"
        if self.global_mcp_config_path is None:
            self.global_mcp_config_path = self.config_dir / "mcp.json"
        for path in (
            self.config_dir,
            self.data_dir,
            self.cache_dir,
            self.agent_storage_dir,
            self.logs_dir,
            self.skills_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.global_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.global_mcp_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.task_db_path.parent.mkdir(parents=True, exist_ok=True)
        return self


def get_s4_paths() -> S4Paths:
    config_home = _xdg_dir("XDG_CONFIG_HOME", ".config") / "s4code"
    data_home = _xdg_dir("XDG_DATA_HOME", ".local/share") / "s4code"
    cache_home = _xdg_dir("XDG_CACHE_HOME", ".cache") / "s4code"
    return S4Paths(
        config_dir=config_home,
        data_dir=data_home,
        cache_dir=cache_home,
        global_config_path=config_home / "config.yaml",
        session_db_path=data_home / "sessions.db",
        task_db_path=data_home / "tasks.db",
        agent_storage_dir=data_home / "agents",
        logs_dir=data_home / "logs",
        skills_dir=data_home / "skills",
        global_mcp_config_path=config_home / "mcp.json",
    )


def get_project_config_path(project_root: str | Path) -> Path:
    root = Path(project_root).expanduser().resolve()
    return root / ".s4code" / "config.yaml"


def get_project_skills_path(project_root: str | Path) -> Path:
    root = Path(project_root).expanduser().resolve()
    return root / ".s4code" / "skills"


def get_project_mcp_config_path(project_root: str | Path) -> Path:
    root = Path(project_root).expanduser().resolve()
    return root / ".s4code" / "mcp.json"


def get_project_skills_paths(project_root: str | Path) -> tuple[Path, ...]:
    root = Path(project_root).expanduser().resolve()
    return (
        root / "skills",
        get_project_skills_path(root),
    )


def get_s4_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def get_s4_repo_skills_path() -> Path:
    return get_s4_repo_root() / "skills"
