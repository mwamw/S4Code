"""YAML-backed configuration models and resolution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import yaml
from .settings import S4AgentSettings, ProductSettings, ContextSettings

from s4code.core.paths import (
    S4Paths,
    get_project_config_dir,
    get_project_config_path,
    get_project_mcp_config_path,
)


_LLM_OPTIONAL_KEYS = (
    "base_url",
    "api_key",
    "temperature",
    "max_tokens",
    "timeout",
    "reasoning_effort",
    "reasoning_summary",
    "user_agent",
)

_SPLIT_SECTION_FILES = {
    "models.yaml": "models",
    "context.yaml": "context",
    "product.yaml": "product",
    "ui.yaml": "ui",
}


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


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if isinstance(payload, list):
        return {"servers": payload}
    if not isinstance(payload, dict):
        raise ValueError(f"S4Code JSON config 顶层必须是对象或数组: {path}")
    return dict(payload)


def _load_legacy_json(path: Path) -> dict[str, Any]:
    legacy_path = path.with_suffix(".json")
    if not legacy_path.exists():
        return {}
    return _yaml_safe_load(legacy_path.read_text(encoding="utf-8"))


def _normalize_split_section_payload(
    raw: dict[str, Any],
    *,
    section_name: str,
    source: Path,
) -> dict[str, Any]:
    payload = dict(raw or {})
    if not payload:
        return {}
    if section_name == "models":
        normalized = {
            key: value
            for key, value in payload.items()
            if key in {"active_model_profile", "model_profiles", "llm"}
        }
        if not normalized:
            raise ValueError(
                f"Split config `{source.name}` 必须包含 active_model_profile、model_profiles 或 llm。"
            )
        return normalized

    if section_name in payload:
        value = payload.get(section_name)
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise ValueError(
                f"Split config `{source.name}` 中的 `{section_name}` 必须是对象。"
            )
        return {section_name: dict(value)}

    return {section_name: payload}


def _load_split_yaml_dir(base_dir: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for filename, section_name in _SPLIT_SECTION_FILES.items():
        path = base_dir / filename
        raw = _load_yaml(path)
        if not raw:
            continue
        normalized = _normalize_split_section_payload(
            raw,
            section_name=section_name,
            source=path,
        )
        payload = _deep_merge(payload, normalized)
    return payload


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _base_settings_payload() -> dict[str, Any]:
    return {
        "active_model_profile": "default",
        "model_profiles": {},
        "context": ContextSettings().model_dump(mode="python"),
        "product": ProductSettings().model_dump(mode="python"),
        "mcp_servers": [],
    }


def _normalize_mcp_config_payload(
    raw: dict[str, Any], *, source: Path
) -> list[dict[str, Any]]:
    payload = dict(raw or {})
    servers = payload.get("servers", payload.get("mcp_servers", []))
    if servers in (None, ""):
        return []
    if not isinstance(servers, list):
        raise ValueError(f"MCP config `servers` 必须是数组: {source}")
    normalized: list[dict[str, Any]] = []
    for item in servers:
        if not isinstance(item, dict):
            raise ValueError(f"MCP server 项必须是对象: {source}")
        server = dict(item)
        name = str(server.get("name") or "").strip()
        if not name:
            raise ValueError(f"MCP server 缺少 name: {source}")
        normalized.append(server)
    return normalized


def _merge_mcp_server_lists(*server_lists: Any) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw_list in server_lists:
        if not isinstance(raw_list, list):
            continue
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            if name not in merged:
                merged[name] = dict(item)
                order.append(name)
            else:
                merged[name] = _deep_merge(merged[name], dict(item))
    return [merged[name] for name in order]


def _complete_llm_payload(payload: dict[str, Any]) -> dict[str, Any]:
    completed = dict(payload or {})
    for key in _LLM_OPTIONAL_KEYS:
        completed.setdefault(key, "medium" if key == "reasoning_effort" else None)
    return completed


def _normalize_profiles(
    payload: dict[str, Any],
    *,
    allow_llm_overrides: bool,
) -> dict[str, Any]:
    normalized = dict(payload)
    raw_profiles = normalized.get("model_profiles")
    legacy_llm = normalized.get("llm")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        if isinstance(legacy_llm, dict) and legacy_llm:
            raw_profiles = {"default": _complete_llm_payload(dict(legacy_llm))}
        else:
            raise ValueError(
                "S4Code LLM 配置缺失。请在全局或项目 config.yaml 中配置 model_profiles，"
                "或至少配置 legacy llm.provider 与 llm.model。"
            )
    else:
        raw_profiles = {
            str(name): _complete_llm_payload(dict(profile or {}))
            for name, profile in raw_profiles.items()
        }
    active_profile = (
        str(normalized.get("active_model_profile") or "default").strip() or "default"
    )
    if active_profile not in raw_profiles:
        active_profile = (
            "default" if "default" in raw_profiles else next(iter(raw_profiles.keys()))
        )
    effective_profile = dict(raw_profiles.get(active_profile) or {})
    llm_overrides = (
        normalized.get("llm")
        if allow_llm_overrides and isinstance(normalized.get("llm"), dict)
        else {}
    )
    normalized["active_model_profile"] = active_profile
    normalized["model_profiles"] = raw_profiles
    normalized["llm"] = _complete_llm_payload(
        _deep_merge(effective_profile, dict(llm_overrides or {}))
    )
    return normalized


def dump_settings_yaml(settings: S4AgentSettings | dict[str, Any]) -> str:
    payload = (
        settings.model_dump(mode="python")
        if isinstance(settings, S4AgentSettings)
        else dict(settings)
    )
    return yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()


def save_settings(path: Path, settings: S4AgentSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_settings_yaml(settings) + "\n", encoding="utf-8")


def load_settings_payload(
    paths: S4Paths,
    *,
    project_root: str | Path | None = None,
    session_overrides: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    global_legacy = _load_legacy_json(paths.global_config_path)
    global_yaml = _load_yaml(paths.global_config_path)
    global_split_yaml = _load_split_yaml_dir(paths.config_dir)
    global_mcp = _normalize_mcp_config_payload(
        _load_json_object(
            (paths.global_mcp_config_path or (paths.config_dir / "mcp.json")).resolve()
        ),
        source=(
            paths.global_mcp_config_path or (paths.config_dir / "mcp.json")
        ).resolve(),
    )
    project_legacy: dict[str, Any] = {}
    project_yaml: dict[str, Any] = {}
    project_split_yaml: dict[str, Any] = {}
    project_mcp: list[dict[str, Any]] = []
    if project_root is not None:
        project_config_path = get_project_config_path(project_root)
        project_legacy = _load_legacy_json(project_config_path)
        project_yaml = _load_yaml(project_config_path)
        project_split_yaml = _load_split_yaml_dir(get_project_config_dir(project_root))
        project_mcp_path = get_project_mcp_config_path(project_root)
        project_mcp = _normalize_mcp_config_payload(
            _load_json_object(project_mcp_path),
            source=project_mcp_path,
        )

    payload: dict[str, Any] = _base_settings_payload()
    payload = _deep_merge(payload, global_legacy)
    payload = _deep_merge(payload, global_yaml)
    payload = _deep_merge(payload, global_split_yaml)
    payload = _deep_merge(payload, project_legacy)
    payload = _deep_merge(payload, project_yaml)
    payload = _deep_merge(payload, project_split_yaml)
    payload["mcp_servers"] = _merge_mcp_server_lists(
        payload.get("mcp_servers"),
        global_mcp,
        project_mcp,
    )
    payload = _normalize_profiles(
        payload,
        allow_llm_overrides=False,
    )
    if session_overrides:
        payload = _deep_merge(payload, session_overrides)
        payload["mcp_servers"] = _merge_mcp_server_lists(payload.get("mcp_servers"))
    payload = _normalize_profiles(
        payload,
        allow_llm_overrides=True,
    )
    return payload


class S4ConfigLoader:
    """Explicit disk configuration loading; constructing an Agent never reads it."""

    def __init__(self, paths: S4Paths | None = None):
        from .paths import get_s4_paths

        self.paths = paths or get_s4_paths()

    def load_agent_settings(self, workspace=None, *, overrides=None) -> S4AgentSettings:
        from .project import ProjectContext

        project_root = (
            ProjectContext.detect(workspace).project_root
            if workspace is not None
            else None
        )
        return S4AgentSettings.model_validate(
            load_settings_payload(
                self.paths,
                project_root=project_root,
                session_overrides=overrides,
            )
        )


def resolve_settings(
    paths: S4Paths, *, project_root=None, session_overrides=None
) -> S4AgentSettings:
    return S4ConfigLoader(paths).load_agent_settings(
        project_root, overrides=session_overrides
    )
