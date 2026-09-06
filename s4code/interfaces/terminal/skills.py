"""SkillCommands: terminal interaction responsibilities."""

from __future__ import annotations

from typing import Any


class SkillCommands:
    def __init__(self, controller):
        self.controller = controller

    def _consume_pending_turn_skills(self) -> list[str]:
        skills = list(self.controller._pending_turn_skills)
        self.controller._pending_turn_skills.clear()
        return skills

    def _activate_turn_skills(
        self,
        skill_names: list[str],
    ) -> list[dict[str, Any]]:
        activated: list[dict[str, Any]] = []

        for raw_name in skill_names:
            name = str(raw_name or "").strip()
            if not name:
                continue
            try:
                activated.append(self.controller.core.activate_skill(name))
            except Exception as exc:
                activated.append({"skill": name, "success": False, "error": str(exc)})
        return activated

    def get_skill_choices(self) -> list[dict[str, Any]]:
        manifests: list[dict[str, Any]] = []
        for skill in self.controller.core.inspector.read("skills"):
            manifests.append(
                {
                    "name": skill["name"],
                    "description": skill["description"],
                    "listing_description": skill["description"],
                    "when_to_use": skill["when_to_use"],
                    "priority": 0,
                    "exposure_mode": "on_demand",
                    "execution_mode": skill["context"],
                    "source_type": "markdown",
                    "source_path": skill["file_path"],
                    "tool_names": skill["allowed_tools"],
                    "registered": True,
                    "active": False,
                    "visible": skill["visible"],
                    "pending": skill["name"] in self.controller._pending_turn_skills,
                }
            )
        return manifests

    def queue_turn_skill(self, skill_name: str) -> str:
        normalized = str(skill_name or "").strip()
        if not normalized:
            return self.format_skills()
        if normalized not in {item["name"] for item in self.get_skill_choices()}:
            raise ValueError(f"Unknown skill: {normalized}")
        if normalized not in self.controller._pending_turn_skills:
            self.controller._pending_turn_skills.append(normalized)
        return f"Skill queued for the next turn: {normalized}"

    def clear_turn_skills(self) -> str:
        if not self.controller._pending_turn_skills:
            return "No queued turn skills."
        cleared = ", ".join(self.controller._pending_turn_skills)
        self.controller._pending_turn_skills.clear()
        return f"Cleared queued turn skills: {cleared}"

    def format_skills(self) -> str:
        skills = self.get_skill_choices()
        if not skills:
            return "No skills discovered."
        lines: list[str] = []
        for item in skills:
            if item["active"]:
                status = "Active now"
            elif item["pending"]:
                status = "Queued for next turn only"
            elif item["registered"]:
                status = "Loaded but idle"
            else:
                status = "Available on demand"
            availability = (
                "Stays loaded"
                if item["exposure_mode"] == "resident"
                else "Loads for one turn"
            )
            lines.append(
                f"- {item['name']}: {status}. {availability}. "
                f"{item['listing_description'] or item['description'] or '-'}"
            )
            when_to_use = str(item.get("when_to_use") or "").strip()
            if when_to_use:
                lines.append(f"  Use it when: {when_to_use}")
        return "\n".join(lines)
