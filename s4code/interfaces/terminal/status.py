"""StatusPresenter: terminal interaction responsibilities."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Optional

import yaml


class StatusPresenter:
    def __init__(self, controller):
        self.controller = controller

    def _permission_mode_label(self) -> str:
        return self.controller.core.inspector.read("permissions")["mode"]

    def _permission_rule_count(self) -> int:
        return int(
            self.controller.permissions.get_permission_status_payload().get("ruleCount")
            or 0
        )

    def _deferred_tool_summary(self) -> dict[str, int]:
        total = 0
        loaded = 0
        immediate = 0
        for spec in self.controller.core.inspector.read("tool_specs"):
            visibility_scope = str(
                spec.get("visibility_scope", "resident") or "resident"
            )
            if visibility_scope == "resident":
                immediate += 1
            if (
                bool(spec.get("expose_in_deferred", False))
                or visibility_scope != "resident"
            ):
                total += 1
                if visibility_scope != "resident":
                    loaded += 1
        return {
            "total": total,
            "loaded": loaded,
            "pending_schema": max(total - loaded, 0),
            "immediate": immediate,
        }

    def get_sidebar_payload(self, *, force: bool = False) -> dict[str, Any]:
        skills = self.controller.skills.get_skill_choices()
        background_tasks = self.controller.runtime._get_background_task_snapshots(
            limit=8, force=force
        )
        active_background = [
            item
            for item in background_tasks
            if str(item.get("status") or "").lower() in {"running", "queued", "waiting"}
        ]
        failed_background = [
            item
            for item in background_tasks
            if str(item.get("status") or "").lower() in {"failed", "error"}
        ]
        deferred_tools = self._deferred_tool_summary()
        context_panel = self.controller.usage.get_context_panel_payload()
        restore = self.controller.session_view.get_restore_continuity_payload()
        pending = self.controller.permissions.get_pending_risk_payload()
        mcp = self.controller.mcp.get_mcp_summary_payload()
        return {
            "project_name": self.controller.project.project_name,
            "branch": self.controller.project.branch or "-",
            "profile": self.controller.settings.active_model_profile,
            "model": self.controller.core.info().model,
            "provider": self.controller.core.info().provider,
            "session_id": self.controller.session_id,
            "permission_mode": self._permission_mode_label(),
            "permission_rules": self._permission_rule_count(),
            "worktree": self.controller.runtime.get_worktree_status_payload(),
            "skills": {
                "active": [item["name"] for item in skills if item.get("active")],
                "queued": [item["name"] for item in skills if item.get("pending")],
            },
            "deferred_tools": deferred_tools,
            "mcp": mcp,
            "background_tasks": background_tasks,
            "active_background_count": len(active_background),
            "failed_background_count": len(failed_background),
            "context": context_panel,
            "pending": pending,
            "restore": restore,
        }

    def get_welcome_notice(self) -> dict[str, str]:
        permission_label = self._permission_mode_label()
        skills = self.controller.skills.get_skill_choices()
        active_skills = [item["name"] for item in skills if item["active"]]
        pending_skills = [item["name"] for item in skills if item["pending"]]
        startup_issues = list(self.controller.core.state()["startup_issues"])
        lines = [
            f"Project: `{self.controller.project.project_name}`",
            f"Root: `{self.controller.project.project_root}`",
            f"Branch: `{self.controller.project.branch or '-'}`",
            f"Model: `{self.controller.core.info().model}` via `{self.controller.core.info().provider}`",
            f"Session: `{self.controller.session_id}`",
            f"Permissions: `{permission_label}`",
            "",
            "Start here:",
            "- Ask directly for a bug fix, code change, review, test run, or repo walkthrough.",
            "- Use `/status` to inspect the current workspace and runtime state.",
            "- Use `/help` for command guidance by task.",
            "- Use `/session list` to restore an earlier session.",
            "",
            "Recommended first prompts:",
            "- Fix the failing test in the current branch.",
            "- Read this repo and explain the main flow before editing.",
            "- Review the current diff and focus on regressions.",
            "- Run the relevant tests for my last change.",
            "- Explain the current git diff in plain English.",
        ]
        if not self.controller.project.is_git_repo:
            lines.append(
                "- This folder is not a git repository, so `/diff`, branch status, and worktree features will be limited."
            )
        if permission_label in {"plan", "default"}:
            lines.append(
                f"- Permission mode is `{permission_label}`, so risky actions may pause for approval."
            )
        if startup_issues:
            lines.append("- Startup issues: " + "; ".join(startup_issues[:3]))
        if active_skills:
            lines.append(f"- Active skills: {', '.join(active_skills[:4])}")
        if pending_skills:
            lines.append(f"- Queued for next turn: {', '.join(pending_skills[:4])}")
        return {
            "kind": "system",
            "title": "Welcome",
            "body": "\n".join(lines),
        }

    def format_help(self) -> str:
        grouped_commands: dict[str, list[str]] = {}
        lines = [
            "S4Code quick start",
            "",
            "Ask in plain language when you want S4Code to inspect code, make edits, run tests, review a diff, or explain a repository.",
            "",
            "Good first prompts:",
            "- Find the bug in the current branch and fix it.",
            "- Review the current diff and focus on regressions.",
            "- Explain how this module works before changing it.",
            "- Run the relevant tests for my last change.",
            "",
            "Task-oriented command map:",
            "- Understand the workspace: `/status`, `/context`, `/tools`, `/skills`, `/worktree`",
            "- Review or explain changes: `/diff`, `/review`, `/trace`",
            "- Follow long-running work: `/tasks`, `/task output <id>`, `/task stop <id>`",
            "- Restore continuity: `/session list`, `/session load <id>`, `/restore`, `/pending`",
            "- Handle approvals: `/pending`, `/confirm`, `/deny`, `/answer`",
            "",
            "Command-oriented reference:",
        ]
        for command in self.controller.command_registry.list_commands():
            usage = f" {command.usage}" if command.usage else ""
            aliases = (
                f" ({', '.join('/' + alias for alias in command.aliases)})"
                if command.aliases
                else ""
            )
            grouped_commands.setdefault(command.category, []).append(
                f"- `/{command.name}{usage}`{aliases}: {command.description}"
            )
        for category in sorted(grouped_commands):
            lines.append(f"{category}:")
            lines.extend(grouped_commands[category])
        return "\n".join(lines)

    def format_status_overview(self) -> str:
        permission_label = self._permission_mode_label()
        skills = self.controller.skills.get_skill_choices()
        active_skills = [item["name"] for item in skills if item["active"]]
        queued_skills = [item["name"] for item in skills if item["pending"]]
        worktree = self.controller.runtime.get_worktree_status_payload()
        background_tasks = self.controller.runtime._get_background_task_snapshots(
            limit=10
        )
        live_background = [
            item
            for item in background_tasks
            if str(item.get("status") or "").lower() in {"running", "queued", "waiting"}
        ]
        context_panel = self.controller.usage.get_context_panel_payload()
        lines = [
            "S4Code status",
            f"- Project: {self.controller.project.project_name}",
            f"- Root: {self.controller.project.project_root}",
            f"- Branch: {self.controller.project.branch or '-'}",
            f"- Session: {self.controller.session_id}",
            f"- Model: {self.controller.core.info().model}",
            f"- Provider: {self.controller.core.info().provider}",
            f"- Permissions: {permission_label}",
            f"- Tools: {len(self.controller.core.inspector.read('tools'))}",
            f"- Skills: {len(skills)} available, {len(active_skills)} active",
            (
                "- Worktree: "
                + (
                    f"{worktree['active']['branch'] or '-'} @ {worktree['active']['path']}"
                    if worktree.get("active")
                    else "none"
                )
            ),
            f"- {self.controller.usage._format_context_meter_line(context_panel)}",
            f"- Background tasks: {len(background_tasks)} total, {len(live_background)} active",
        ]
        if active_skills:
            lines.append(f"- Active skills: {', '.join(active_skills[:6])}")
        if queued_skills:
            lines.append(f"- Queued for next turn: {', '.join(queued_skills[:6])}")
        if context_panel.get("cache_enabled"):
            lines.append(
                f"- Cache status: enabled (anchor active: {context_panel.get('cache_anchor_active')})"
            )
        if live_background:
            lines.append("")
            lines.append("Active background tasks:")
            for item in live_background[:5]:
                lines.append(
                    f"- {item.get('task_id') or '-'} | {item.get('status') or '-'} | {item.get('command') or item.get('cwd') or '-'}"
                )
            lines.append(
                "Use `/task output <id>` to inspect logs or `/task stop <id>` to stop one."
            )
        lines.extend(
            [
                "",
                "Next useful commands:",
                "- `/help`",
                "- `/diff`",
                "- `/tasks`",
                "- `/session list`",
            ]
        )
        return "\n".join(lines)

    def format_status(self) -> str:
        agent_mode = self.controller.core.inspector.read("mode")
        agent_count = len(self.controller.core.inspector.read("agents", limit=1000))
        task_count = len(self.controller.core.inspector.read("tasks", limit=1000))
        background_task_count = len(
            self.controller.runtime._get_background_task_snapshots(limit=1000)
        )
        restore_report = self.controller.session_view.get_restore_report()
        worktree = self.controller.runtime.get_worktree_status_payload()
        skills = self.controller.skills.get_skill_choices()
        permissions = self.controller.permissions.get_permission_status_payload()
        status = {
            "sessionId": self.controller.session_id,
            "title": self.controller.title,
            "projectRoot": str(self.controller.project.project_root),
            "branch": self.controller.project.branch,
            "activeModelProfile": self.controller.settings.active_model_profile,
            "model": self.controller.core.info().model,
            "provider": self.controller.core.info().provider,
            "executionMode": agent_mode,
            "permissionMode": self._permission_mode_label(),
            "permissions": {
                "mode": permissions.get("mode"),
                "ruleCount": permissions.get("ruleCount"),
                "sourceCounts": permissions.get("sourceCounts"),
                "behaviorCounts": permissions.get("behaviorCounts"),
            },
            "agents": agent_count,
            "tasks": task_count,
            "backgroundTasks": background_task_count,
            "checkpoints": self.controller.checkpoints.count,
            "toolCount": len(self.controller.core.inspector.read("tools")),
            "codeintelEnabled": self.controller.settings.product.enable_codeintel,
            "mcpServers": [
                item["name"]
                for item in self.controller.core.inspector.read("mcp_status")
                if item["registered"]
            ],
            "skills": {
                "available": len(skills),
                "registered": sum(1 for item in skills if item["registered"]),
                "active": sum(1 for item in skills if item["active"]),
                "pendingTurn": list(self.controller._pending_turn_skills),
                "sources": self.controller.core.inspector.read("skill_sources"),
            },
            "worktree": worktree,
            "context": self.controller.core.inspector.read("context"),
            "startupIssues": list(self.controller.core.state()["startup_issues"]),
            "closed": self.controller._closed,
            "lastCloseStatus": (
                str(self.controller._last_close_report.get("status") or "")
                if isinstance(self.controller._last_close_report, dict)
                else None
            ),
            "restore": (
                {
                    "status": restore_report.get("status"),
                    "issueCount": len(list(restore_report.get("issues") or [])),
                    "missingTools": list(restore_report.get("missingTools") or []),
                    "missingSkills": list(restore_report.get("missingSkills") or []),
                }
                if isinstance(restore_report, dict)
                else None
            ),
        }
        return json.dumps(status, ensure_ascii=False, indent=2)

    def format_sidebar(self, *, force: bool = False) -> str:
        payload = self.get_sidebar_payload(force=force)
        worktree = dict(payload.get("worktree") or {})
        active_worktree = worktree.get("active") or {}
        context_panel = dict(payload.get("context") or {})
        pending = dict(payload.get("pending") or {})
        restore = dict(payload.get("restore") or {})
        deferred = dict(payload.get("deferred_tools") or {})
        mcp = dict(payload.get("mcp") or {})
        skills = dict(payload.get("skills") or {})
        lines = [
            f"Project: {payload.get('project_name')}",
            f"Branch: {payload.get('branch')}",
            f"Model: {payload.get('model')} via {payload.get('provider')}",
            f"Session: {payload.get('session_id')}",
            f"Permissions: {payload.get('permission_mode')} ({payload.get('permission_rules')} rules)",
            (
                "MCP: "
                + (
                    f"{mcp.get('configured', 0)} configured | {mcp.get('connected', 0)} connected | "
                    f"{mcp.get('disabled', 0)} disabled | {mcp.get('unavailable', 0)} unavailable"
                    if mcp.get("enabled")
                    else "disabled"
                )
            ),
            (
                "Worktree: "
                + (
                    f"{active_worktree.get('branch') or '-'} @ {active_worktree.get('path') or '-'}"
                    if active_worktree
                    else "none"
                )
            ),
            "",
            self.controller.usage._format_context_meter_line(context_panel),
            f"Deferred tools: {deferred.get('loaded', 0)} loaded now, {deferred.get('pending_schema', 0)} need schema load",
            "",
            "Skills:",
        ]
        active_skills = list(skills.get("active") or [])
        queued_skills = list(skills.get("queued") or [])
        if active_skills:
            lines.append("- Active: " + ", ".join(active_skills[:4]))
        else:
            lines.append("- Active: none")
        if queued_skills:
            lines.append("- Next turn: " + ", ".join(queued_skills[:4]))
        else:
            lines.append("- Next turn: none")
        lines.append("")
        lines.append(
            f"Background tasks: {payload.get('active_background_count', 0)} active, "
            f"{payload.get('failed_background_count', 0)} failed"
        )
        for item in list(payload.get("background_tasks") or [])[:4]:
            lines.append(f"- {item.get('task_id') or '-'}: {item.get('status') or '-'}")
        if pending.get("active"):
            lines.append("")
            lines.append(
                f"Pending: {pending.get('title') or 'Approval needed'} "
                f"({pending.get('risk_level') or 'unknown'} risk)"
            )
        if restore.get("summary"):
            lines.append("")
            lines.append("Restore: " + str(restore.get("summary")))
        else:
            lines.append("")
            lines.append("Restore: current session only")
        return "\n".join(lines)

    def toggle_sidebar(self, visible: Optional[bool] = None) -> str:
        if visible is None:
            self.controller.sidebar_visible = not self.controller.sidebar_visible
        else:
            self.controller.sidebar_visible = bool(visible)
        return (
            "Sidebar shown." if self.controller.sidebar_visible else "Sidebar hidden."
        )

    def get_model_choices(self) -> list[dict[str, Any]]:
        choices: list[dict[str, Any]] = []
        for name, profile in self.controller.settings.model_profiles.items():
            choices.append(
                {
                    "name": name,
                    "provider": profile.provider,
                    "model": profile.model,
                    "active": name == self.controller.settings.active_model_profile,
                }
            )
        return choices

    def format_config(self) -> str:
        return yaml.safe_dump(
            {
                **self.controller.core.inspector.read("configuration"),
                "ui": self.controller.settings.ui.model_dump(mode="json"),
            },
            allow_unicode=True,
            sort_keys=False,
        )

    def format_tools(self) -> str:
        specs = sorted(
            self.controller.core.inspector.read("tool_specs"),
            key=lambda item: item["name"].lower(),
        )
        if not specs:
            return "No tools registered."
        lines: list[str] = []
        for spec in specs:
            if spec["visibility_scope"] == "resident":
                availability = "Available now"
            elif spec["visibility_scope"] == "runtime":
                availability = "Loaded for the current runtime"
            elif spec["visibility_scope"] == "turn":
                availability = "Loaded for this turn only"
            elif bool(spec.get("expose_in_deferred", False)):
                availability = "Available after loading its schema"
            else:
                availability = "Not exposed by default"
            risk = "Read-only"
            if spec["destructive"]:
                risk = "High-risk change"
            elif spec["requires_confirmation"]:
                risk = "Needs approval"
            elif spec["side_effect_level"] != "none":
                risk = "Writes or changes state"
            lines.append(
                f"- {spec['name']}: {availability}. {risk}. {spec['description']}"
            )
        return "\n".join(lines)

    def format_models(self) -> str:
        lines = [
            f"Active profile: {self.controller.settings.active_model_profile}",
            f"Current provider: {self.controller.settings.llm.provider}",
            f"Current model: {self.controller.settings.llm.model}",
            "",
            "Profiles:",
        ]
        for name, profile in self.controller.settings.model_profiles.items():
            marker = (
                "*" if name == self.controller.settings.active_model_profile else "-"
            )
            lines.append(f"{marker} {name}: {profile.provider} / {profile.model}")
        lines.append("")
        lines.append("Usage: /model <profile-name|literal-model>")
        return "\n".join(lines)

    def _background_task_notice_from_event(
        self, event: dict[str, Any]
    ) -> Optional[dict[str, str]]:
        structured = event.get("structured_data")
        if not isinstance(structured, dict):
            return None
        task_id = str(structured.get("task_id") or "").strip()
        status = str(structured.get("status") or "").strip().lower()
        if not task_id or status not in {"running", "queued", "waiting"}:
            return None
        command = (
            self._format_command_value(structured.get("command"))
            .replace("\n", " ")
            .strip()
        )
        description = str(
            structured.get("description") or event.get("description") or ""
        ).strip()
        lines = [f"Started background task `{task_id}`."]
        if description:
            lines.append(f"Purpose: {description}")
        elif command:
            lines.append(
                f"Command: {self.controller.runtime._tail_text(command, max_chars=140)}"
            )
        lines.append("Use `/task output " + task_id + "` to stream logs.")
        lines.append("Use `/task stop " + task_id + "` to stop it.")
        return {
            "type": "system_notice",
            "title": "Background Task Started",
            "content": "\n".join(lines),
        }

    @staticmethod
    def _format_command_value(value: Any) -> str:
        if isinstance(value, (list, tuple)):
            return " ".join(str(item) for item in value)
        return str(value or "")

    @staticmethod
    def _format_epoch(value: Any) -> str:
        if not isinstance(value, (int, float)):
            return "-"
        try:
            return datetime.fromtimestamp(float(value)).isoformat(timespec="seconds")
        except Exception:
            return "-"

    def format_hooks(self) -> str:
        hooks = self.controller.core.inspector.read("hooks")
        if not hooks:
            return "No hooks installed."
        return "\n".join(hooks)

    def format_doctor(self) -> str:
        payload = {
            "project": self.controller.project.to_status_dict(),
            "status": json.loads(self.format_status()),
            "restoreReport": self.controller.session_view.get_restore_report(),
            "lastCloseReport": self.get_last_close_report(),
            "startupIssues": list(self.controller.core.state()["startup_issues"]),
            "mcp": self.controller.mcp.get_mcp_status_payload(),
            "skills": self.controller.skills.get_skill_choices(),
            "backgroundTasks": self.controller.runtime._get_background_task_snapshots(
                limit=20
            ),
            "tools": [
                {
                    "name": spec["name"],
                    "description": spec["description"],
                    "readOnly": spec["read_only"],
                    "requiresConfirmation": spec["requires_confirmation"],
                    "destructive": spec["destructive"],
                    "visibility": spec["visibility_scope"],
                    "sideEffectLevel": spec["side_effect_level"],
                }
                for spec in self.controller.core.inspector.read("tool_specs")
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def get_last_close_report(self) -> Optional[dict[str, Any]]:
        if self.controller._last_close_report is None:
            self.controller._last_close_report = self.controller.core.close_report()
        return (
            dict(self.controller._last_close_report)
            if isinstance(self.controller._last_close_report, dict)
            else None
        )

    def get_startup_notices(self) -> list[dict[str, str]]:
        notices: list[dict[str, str]] = []
        background_tasks = self.controller.runtime._get_background_task_snapshots(
            limit=10
        )
        self.controller._last_background_notice_states = {
            str(item.get("task_id") or ""): str(item.get("status") or "")
            for item in background_tasks
            if str(item.get("task_id") or "")
        }
        live_background = [
            item
            for item in background_tasks
            if str(item.get("status") or "").lower() in {"running", "queued", "waiting"}
        ]
        if live_background:
            lines = [
                f"Restored {len(live_background)} active background task(s).",
            ]
            for item in live_background[:5]:
                lines.append(
                    f"- {item.get('task_id') or '-'} | {item.get('status') or '-'} | {item.get('command') or item.get('cwd') or '-'}"
                )
            lines.append(
                "Use /tasks to list them all, /task output <id> to stream logs, or /task stop <id> to stop one."
            )
            notices.append(
                {
                    "kind": "system",
                    "title": "Background Tasks",
                    "body": "\n".join(lines),
                }
            )
        mcp_summary = self.controller.mcp.get_mcp_summary_payload()
        if mcp_summary.get("enabled") and int(mcp_summary.get("configured") or 0) > 0:
            configured = int(mcp_summary.get("configured") or 0)
            connected = int(mcp_summary.get("connected") or 0)
            disabled = int(mcp_summary.get("disabled") or 0)
            unavailable = int(mcp_summary.get("unavailable") or 0)
            lines = [
                (
                    f"Configured {configured} MCP server(s): "
                    f"{connected} connected, {disabled} disabled, {unavailable} unavailable."
                )
            ]
            for item in list(mcp_summary.get("issues") or [])[:8]:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("server_name") or "").strip() or "-"
                status = str(item.get("status") or "unknown").strip() or "unknown"
                last_error = str(item.get("last_error") or "").strip()
                line = f"- {name}: {status}"
                if last_error:
                    line += f" | {last_error}"
                lines.append(line)
            lines.append("Use /mcp for details.")
            notices.append(
                {
                    "kind": "warning" if unavailable > 0 else "system",
                    "title": "MCP Startup",
                    "body": "\n".join(lines),
                }
            )
        if self.controller.core.state()["startup_issues"]:
            notices.append(
                {
                    "kind": "warning",
                    "title": "Startup Issues",
                    "body": "\n".join(
                        f"- {issue}"
                        for issue in self.controller.core.state()["startup_issues"]
                    ),
                }
            )
        restore_payload = self.controller.session_view.get_restore_continuity_payload()
        restore_summary = self.controller.session_view.summarize_restore_report(
            detailed=True
        )
        restore_report = self.controller.session_view.get_restore_report()
        if restore_summary and (
            self.controller.session_view.was_restored
            or (
                isinstance(restore_report, dict)
                and (
                    str(restore_report.get("status") or "restored") != "restored"
                    or bool(restore_report.get("issues"))
                )
            )
        ):
            kind = "warning"
            if (
                isinstance(restore_report, dict)
                and str(restore_report.get("status") or "restored") == "restored"
            ):
                kind = "system"
            notices.append(
                {
                    "kind": kind,
                    "title": "Session Restored",
                    "body": restore_summary
                    + (
                        "\n\nRecommended next step: /pending, /tasks, /diff, or continue the last task."
                        if restore_payload
                        else ""
                    ),
                }
            )
        return notices
