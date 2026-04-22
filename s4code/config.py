"""YAML-backed configuration models and resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field

from .paths import S4Paths, get_project_config_path


class LLMSettings(BaseModel):
    provider: str = "openai"
    base_url: str = "http://127.0.0.1:5124/v1"
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
    right_panel_open: bool = False


class ContextSettings(BaseModel):
    enabled: bool = True
    max_tokens: int = 24000
    history_compactor: str = "llm"
    recent_turns: int = 4


def _default_profiles() -> dict[str, dict[str, Any]]:
    return {
        "default": LLMSettings().model_dump(mode="python"),
    }


class S4Settings(BaseModel):
    active_model_profile: str = "default"
    model_profiles: dict[str, LLMSettings] = Field(default_factory=lambda: {"default": LLMSettings()})
    llm: LLMSettings = Field(default_factory=LLMSettings)
    context: ContextSettings = Field(default_factory=ContextSettings)
    product: ProductSettings = Field(default_factory=ProductSettings)
    ui: UISettings = Field(default_factory=UISettings)
    mcp_servers: list[MCPServerSettings] = Field(default_factory=list)


def _yaml_safe_load(text: str) -> dict[str, Any]:
    payload = yaml.safe_load(text)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("S4Code config 顶层必须是映射对象。")
    return dict(payload)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _yaml_safe_load(path.read_text(encoding="utf-8"))


def _load_legacy_json(path: Path) -> dict[str, Any]:
    legacy_path = path.with_suffix(".json")
    if not legacy_path.exists():
        return {}
    return _yaml_safe_load(legacy_path.read_text(encoding="utf-8"))


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _normalize_profiles(
    payload: dict[str, Any],
    *,
    allow_llm_overrides: bool,
    explicit_profiles_present: bool,
) -> dict[str, Any]:
    normalized = dict(payload)
    raw_profiles = normalized.get("model_profiles")
    synthesized_from_legacy = (not explicit_profiles_present) or not isinstance(raw_profiles, dict) or not raw_profiles
    if synthesized_from_legacy:
        raw_profiles = _default_profiles()
    legacy_llm = normalized.get("llm")
    if synthesized_from_legacy and isinstance(legacy_llm, dict) and legacy_llm:
        default_profile = dict(raw_profiles.get("default") or _default_profiles()["default"])
        raw_profiles["default"] = _deep_merge(default_profile, legacy_llm)
    active_profile = str(normalized.get("active_model_profile") or "default").strip() or "default"
    if active_profile not in raw_profiles:
        active_profile = "default" if "default" in raw_profiles else next(iter(raw_profiles.keys()))
    effective_profile = dict(raw_profiles.get(active_profile) or {})
    llm_overrides = (
        normalized.get("llm")
        if allow_llm_overrides and isinstance(normalized.get("llm"), dict)
        else {}
    )
    normalized["active_model_profile"] = active_profile
    normalized["model_profiles"] = raw_profiles
    normalized["llm"] = _deep_merge(effective_profile, dict(llm_overrides or {}))
    return normalized


def dump_settings_yaml(settings: S4Settings | dict[str, Any]) -> str:
    payload = settings.model_dump(mode="python") if isinstance(settings, S4Settings) else dict(settings)
    return yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()


def save_settings(path: Path, settings: S4Settings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_settings_yaml(settings) + "\n", encoding="utf-8")


def resolve_settings(
    paths: S4Paths,
    *,
    project_root: str | Path | None = None,
    session_overrides: Optional[dict[str, Any]] = None,
) -> S4Settings:
    global_legacy = _load_legacy_json(paths.global_config_path)
    global_yaml = _load_yaml(paths.global_config_path)
    project_legacy: dict[str, Any] = {}
    project_yaml: dict[str, Any] = {}
    if project_root is not None:
        project_config_path = get_project_config_path(project_root)
        project_legacy = _load_legacy_json(project_config_path)
        project_yaml = _load_yaml(project_config_path)

    explicit_profiles_present = any(
        isinstance(source.get("model_profiles"), dict) and bool(source.get("model_profiles"))
        for source in (global_legacy, global_yaml, project_legacy, project_yaml, session_overrides or {})
    )

    payload: dict[str, Any] = S4Settings().model_dump(mode="python")
    payload = _deep_merge(payload, global_legacy)
    payload = _deep_merge(payload, global_yaml)
    payload = _deep_merge(payload, project_legacy)
    payload = _deep_merge(payload, project_yaml)
    payload = _normalize_profiles(
        payload,
        allow_llm_overrides=False,
        explicit_profiles_present=explicit_profiles_present,
    )
    if session_overrides:
        payload = _deep_merge(payload, session_overrides)
    payload = _normalize_profiles(
        payload,
        allow_llm_overrides=True,
        explicit_profiles_present=explicit_profiles_present,
    )
    return S4Settings.model_validate(payload)
