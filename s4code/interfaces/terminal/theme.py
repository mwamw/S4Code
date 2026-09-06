"""JSON-backed TUI theme loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_THEME: dict[str, Any] = {
    "name": "s4",
    "layout": {
        "background": "transparent",
        "text": "#e2e8f0",
        "muted": "#94a3b8",
        "header_text": "#e2e8f0",
        "footer_text": "#94a3b8",
        "transcript_border": "#38bdf8",
        "sidebar_border": "#475569",
        "sidebar_text": "#cbd5e1",
        "palette_border": "#334155",
        "input_border": "#22d3ee",
        "input_text": "#e2e8f0",
        "separator": "#475569",
        "checkpoint": "bold #fbbf24",
    },
    "cards": {
        "system": {"border": "#fb923c", "title": "#ffedd5"},
        "user": {"border": "#10b981", "title": "#dcfce7"},
        "assistant": {"border": "#60a5fa", "title": "#dbeafe"},
        "thinking": {"border": "#a78bfa", "title": "#ede9fe", "text": "#c4b5fd"},
        "tool": {"border": "#f59e0b", "title": "#fef3c7"},
        "warning": {"border": "#facc15", "title": "#fef9c3"},
        "error": {"border": "#f87171", "title": "#fee2e2"},
        "round": {"border": "#475569", "title": "#94a3b8", "text": "#94a3b8"},
        "runtime": {"border": "#14b8a6", "title": "#ccfbf1"},
        "default": {"border": "#64748b", "title": "#e2e8f0"},
    },
    "palette": {
        "selected_prefix": "bold #082f49 on #67e8f9",
        "selected_label": "bold #082f49 on #67e8f9",
        "selected_spacer": "on #67e8f9",
        "selected_description": "#0f172a on #a5f3fc",
        "selected_alias": "#164e63 on #cffafe",
        "prefix": "#475569",
        "label": "#cbd5e1",
        "spacer": "#cbd5e1",
        "description": "#94a3b8",
        "alias": "#64748b",
        "empty": "#facc15",
        "hidden_count": "#475569",
        "border": "#22d3ee",
    },
    "diff": {
        "summary": "#e2e8f0",
        "hunk_border": "#334155",
        "prelude_border": "#475569",
        "file_label": "bold #bfdbfe",
        "git_header": "bold #93c5fd",
        "new_file": "#86efac",
        "deleted_file": "#fca5a5",
        "prelude": "#94a3b8",
        "add_prefix": "bold #4ade80 on #052e16",
        "add_background": "#052e16",
        "delete_prefix": "bold #f87171 on #3f1111",
        "delete_background": "#3f1111",
        "context_prefix": "#64748b",
        "escape": "italic #94a3b8",
        "plain": "#cbd5e1",
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def bundled_theme_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "themes"


def list_bundled_themes() -> list[str]:
    theme_dir = bundled_theme_dir()
    if not theme_dir.exists():
        return []
    return sorted(path.stem for path in theme_dir.glob("*.json"))


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Theme must be a JSON object: {path}")
    return payload


def resolve_theme_path(name_or_path: str | None) -> Path:
    raw = str(name_or_path or "s4").strip() or "s4"
    candidate = Path(raw).expanduser()
    if candidate.exists():
        return candidate.resolve()
    return bundled_theme_dir() / f"{raw}.json"


def load_tui_theme(name_or_path: str | None) -> dict[str, Any]:
    path = resolve_theme_path(name_or_path)
    if not path.exists():
        path = bundled_theme_dir() / "s4.json"
    if not path.exists():
        return dict(DEFAULT_THEME)
    return _deep_merge(DEFAULT_THEME, _load_json(path))
