"""ThemeCommands: terminal interaction responsibilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from s4code.interfaces.terminal.theme import list_bundled_themes


class ThemeCommands:
    def __init__(self, controller):
        self.controller = controller

    def get_theme_choices(self) -> list[dict[str, Any]]:
        current = str(self.controller.settings.ui.theme or "s4")
        choices = [
            {
                "name": name,
                "active": name == current,
                "kind": "bundled",
            }
            for name in list_bundled_themes()
        ]
        if current and current not in {item["name"] for item in choices}:
            choices.append(
                {
                    "name": current,
                    "active": True,
                    "kind": "custom",
                }
            )
        return choices

    def format_themes(self) -> str:
        lines = [
            f"Current theme: {self.controller.settings.ui.theme or 's4'}",
            "",
            "Themes:",
        ]
        for item in self.get_theme_choices():
            marker = "*" if item.get("active") else "-"
            lines.append(f"{marker} {item.get('name')} ({item.get('kind')})")
        lines.append("")
        lines.append("Usage: /theme <theme-name|theme-json-path>")
        return "\n".join(lines)

    def update_theme(self, target: str) -> str:
        raw_target = str(target or "").strip()
        if not raw_target:
            return self.format_themes()
        bundled = set(list_bundled_themes())
        if raw_target in bundled:
            normalized = raw_target
        else:
            candidate = Path(raw_target).expanduser()
            if not candidate.is_absolute():
                project_candidate = (
                    self.controller.project.project_root / candidate
                ).resolve()
                candidate = (
                    project_candidate
                    if project_candidate.exists()
                    else candidate.resolve()
                )
            if not candidate.exists() or not candidate.is_file():
                return f"Unknown theme: {raw_target}\n" + self.format_themes()
            normalized = str(candidate.resolve())
        self.controller.settings.ui.theme = normalized
        self.controller.session_overrides.setdefault("ui", {})["theme"] = normalized
        self.controller._mark_session_dirty()
        self.controller.ensure_autosave()
        return f"Theme set to {normalized}"
