"""Session summaries, lineage and restoration reports for terminals."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


class SessionPresenter:
    def __init__(self, controller):
        self.controller = controller

    @property
    def was_restored(self) -> bool:
        return self.controller._restored_session

    def format_session_tree(self) -> str:
        sessions = self.get_session_choices(limit=100)
        if not sessions:
            return "No S4Code sessions found."
        by_parent: dict[str, list[dict[str, Any]]] = {}
        roots: list[dict[str, Any]] = []
        known_ids = {str(item.get("session_id") or "") for item in sessions}
        for item in sessions:
            parent = str(item.get("forked_from_session_id") or "")
            if parent and parent in known_ids:
                by_parent.setdefault(parent, []).append(item)
            else:
                roots.append(item)

        def _render(item: dict[str, Any], prefix: str = "") -> list[str]:
            marker = "*" if item.get("current") else "-"
            line = f"{prefix}{marker} {item.get('session_id')} | {item.get('title') or '-'}"
            children = sorted(
                by_parent.get(str(item.get("session_id")), []),
                key=lambda child: str(child.get("updated_at") or ""),
                reverse=True,
            )
            lines = [line]
            for child in children:
                lines.extend(_render(child, prefix + "  "))
            return lines

        ordered_roots = sorted(
            roots, key=lambda item: str(item.get("updated_at") or ""), reverse=True
        )
        lines: list[str] = []
        for item in ordered_roots:
            lines.extend(_render(item))
        return "\n".join(lines)

    def format_current_session(self) -> str:
        lines = [
            "Current session",
            f"- Title: {self.controller.title}",
            f"- Session ID: {self.controller.session_id}",
            f"- Project: {self.controller.project.project_name}",
            f"- Root: {self.controller.project.project_root}",
            f"- Model: {self.controller.core.info().model}",
            f"- Permissions: {self.controller.status._permission_mode_label()}",
            f"- Forked from: {self.controller.forked_from_session_id or 'none'}",
            f"- Checkpoints: {len(self.controller.checkpoints.get_checkpoint_choices())}",
        ]
        restore = self.get_restore_continuity_payload()
        if restore.get("summary"):
            lines.append(f"- Restore state: {restore.get('summary')}")
        lines.extend(
            [
                "",
                "Next step:",
                "- Use `/session list` to switch sessions.",
                "- Use `/session checkpoints` or `/rewind` to move through history.",
            ]
        )
        return "\n".join(lines)

    def get_session_choices(self, *, limit: int = 20) -> list[dict[str, Any]]:
        choices: list[dict[str, Any]] = []
        for item in self.controller.session_manager.list_sessions(
            limit=limit, project_root=self.controller.project.project_root
        ):
            choices.append(
                {
                    "session_id": item.session_id,
                    "title": item.title,
                    "model": item.model,
                    "provider": item.provider,
                    "project_root": item.project_root,
                    "permission_mode": item.permission_mode,
                    "branch": item.branch,
                    "forked_from_session_id": item.forked_from_session_id,
                    "updated_at": item.updated_at.isoformat()
                    if item.updated_at is not None
                    else None,
                    "current": item.session_id == self.controller.session_id,
                }
            )
        return choices

    def format_sessions(self, *, limit: int = 20) -> str:
        sessions = self.controller.session_manager.list_sessions(
            limit=limit, project_root=self.controller.project.project_root
        )
        if not sessions:
            return f"No S4Code sessions found for project `{self.controller.project.project_root}`."
        lines = []
        for item in sessions:
            marker = "*" if item.session_id == self.controller.session_id else "-"
            updated = (
                item.updated_at.isoformat(timespec="seconds")
                if item.updated_at is not None
                else "-"
            )
            project_name = Path(item.project_root).name if item.project_root else "-"
            lines.append(
                f"{marker} {item.title or item.session_id} | project={project_name} | "
                f"id={item.session_id} | updated={updated} | model={item.model or '-'} | permissions={item.permission_mode or '-'}"
            )
        return "\n".join(lines)

    def get_restore_report(self) -> Optional[dict[str, Any]]:
        return self.controller.core.inspector.read("restore")

    def summarize_restore_report(self, *, detailed: bool = False) -> str:
        payload = self.get_restore_continuity_payload()
        if not payload:
            return ""
        lines = [str(payload.get("summary") or "Session restored.")]
        if payload.get("restored_items"):
            lines.append(
                "Restored: "
                + ", ".join(str(item) for item in payload["restored_items"][:6])
            )
        if payload.get("missing_tools"):
            lines.append(
                "Missing tools: "
                + ", ".join(str(item) for item in payload["missing_tools"][:6])
            )
        if payload.get("missing_skills"):
            lines.append(
                "Missing skills: "
                + ", ".join(str(item) for item in payload["missing_skills"][:6])
            )
        if detailed and payload.get("issues"):
            for issue in list(payload["issues"])[:5]:
                if not isinstance(issue, dict):
                    continue
                lines.append(
                    f"- {str(issue.get('severity') or 'warning').upper()} "
                    f"{str(issue.get('component') or 'restore')}: {str(issue.get('message') or '').strip()}"
                )
        return "\n".join(lines)

    def format_restore_report(self) -> str:
        payload = self.get_restore_continuity_payload()
        if not payload:
            return "No restore report for the current session."
        lines = [
            "Session restore",
            f"- {payload.get('summary')}",
            f"- Execution context restored: {payload.get('execution_context_restored')}",
            f"- Pending interaction restored: {payload.get('has_pending_interaction')}",
            f"- Active background tasks restored: {payload.get('active_background_tasks')}",
        ]
        if payload.get("missing_tools"):
            lines.append(
                "- Missing tools: "
                + ", ".join(str(item) for item in payload["missing_tools"][:6])
            )
        if payload.get("missing_skills"):
            lines.append(
                "- Missing skills: "
                + ", ".join(str(item) for item in payload["missing_skills"][:6])
            )
        lines.extend(
            [
                "",
                "Recommended next step:",
                "- Use `/pending` if execution paused on a question or approval.",
                "- Use `/tasks` if background work was restored.",
                "- Use `/diff` or continue your last task if everything looks healthy.",
            ]
        )
        return "\n".join(lines)

    def get_restore_continuity_payload(self) -> dict[str, Any]:
        report = self.get_restore_report()
        if report is None:
            return {}
        missing_tools = list(report.get("missingTools") or [])
        missing_skills = list(report.get("missingSkills") or [])
        issues = list(report.get("issues") or [])
        restored_items = list(report.get("restoredItems") or [])
        active_background_tasks = len(
            [
                item
                for item in self.controller.runtime._get_background_task_snapshots(
                    limit=20
                )
                if str(item.get("status") or "").lower()
                in {"running", "queued", "waiting"}
            ]
        )
        has_pending = self.controller.permissions.get_pending_interaction() is not None
        status = str(report.get("status") or "restored")
        if (
            status == "restored"
            and not issues
            and not missing_tools
            and not missing_skills
        ):
            summary = "Everything important from the previous session is available."
        elif status == "restored":
            summary = "Most of the previous session is back, but some capabilities were not restored."
        else:
            summary = "The session was restored with gaps. Review the missing pieces before continuing."
        return {
            "status": status,
            "summary": summary,
            "execution_context_restored": bool(report.get("executionContextRestored")),
            "restored_items": restored_items,
            "missing_tools": missing_tools,
            "missing_skills": missing_skills,
            "issues": issues,
            "has_pending_interaction": has_pending,
            "active_background_tasks": active_background_tasks,
        }
