"""Configuration models and resolution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from .paths import S4Paths, get_project_config_path


class LLMSettings(BaseModel):
    provider: str = "anthropic_native"
    base_url: str = "http://127.0.0.1:5124"
    api_key: str = "122"
    model: str = "qwen3.5-9b"
    temperature: float = 0.2
    max_tokens: Optional[int] = None
    timeout: int = 120
    reasoning_effort: str = "high"
    reasoning_summary: str = "auto"


class MCPServerSettings(BaseModel):
    name: str
    server_source: str
    server_args: list[str] = Field(default_factory=list)
    transport_type: Optional[str] = None
    tool_prefix: str = ""
    auto_connect: bool = True
    include_resources: bool = True
    env: dict[str, str] = Field(default_factory=dict)


class ProductSettings(BaseModel):
    permission_mode: str = "accept_edits"
    enable_codeintel: bool = True
    enable_mcp: bool = True
    enable_worktree: bool = True
    git_binary: str = "git"
    shell: str = "bash"
    command_timeout_ms: int = 120000
    max_background_tasks: int = 4
    session_auto_save: bool = True
    default_review_depth: str = "full"
    enable_verifier: bool = True


class UISettings(BaseModel):
    theme: str = "s4"
    show_thinking: bool = True
    right_panel_open: bool = True


class S4Settings(BaseModel):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    product: ProductSettings = Field(default_factory=ProductSettings)
    ui: UISettings = Field(default_factory=UISettings)
    mcp_servers: list[MCPServerSettings] = Field(default_factory=list)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def save_settings(path: Path, settings: S4Settings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings.model_dump(mode="python"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def resolve_settings(
    paths: S4Paths,
    *,
    project_root: str | Path | None = None,
    session_overrides: Optional[dict[str, Any]] = None,
) -> S4Settings:
    payload: dict[str, Any] = S4Settings().model_dump(mode="python")
    payload = _deep_merge(payload, _load_json(paths.global_config_path))
    if project_root is not None:
        payload = _deep_merge(payload, _load_json(get_project_config_path(project_root)))
    if session_overrides:
        payload = _deep_merge(payload, session_overrides)
    return S4Settings.model_validate(payload)

