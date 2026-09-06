"""RuntimePresenter: terminal interaction responsibilities."""

from __future__ import annotations

from datetime import datetime
import time
from typing import Any, Optional


class RuntimePresenter:
    def __init__(self, controller):
        self.controller = controller

    def _get_background_task_snapshots(
        self, *, limit: int = 20, force: bool = False
    ) -> list[dict[str, Any]]:
        def _produce() -> list[dict[str, Any]]:
            try:
                snapshots = self.controller.core.inspector.read(
                    "processes", limit=limit
                )
            except Exception:
                return []
            result: list[dict[str, Any]] = []
            for snapshot in snapshots[: max(int(limit), 0)]:
                stdout = str(snapshot.get("stdout", "") or "")
                stderr = str(snapshot.get("stderr", "") or "")
                started_at = snapshot.get("started_at", None)
                finished_at = snapshot.get("finished_at", None)
                duration_seconds = None
                if isinstance(started_at, (int, float)):
                    end_time = (
                        finished_at
                        if isinstance(finished_at, (int, float))
                        else time.time()
                    )
                    duration_seconds = max(float(end_time) - float(started_at), 0.0)
                result.append(
                    {
                        "task_id": snapshot.get("task_id", ""),
                        "status": snapshot.get("status", ""),
                        "cwd": snapshot.get("cwd", ""),
                        "command": snapshot.get("command", ""),
                        "return_code": snapshot.get("return_code", None),
                        "started_at": started_at,
                        "finished_at": finished_at,
                        "duration_seconds": duration_seconds,
                        "stdout_tail": self._tail_text(stdout, max_chars=1200),
                        "stderr_tail": self._tail_text(stderr, max_chars=1200),
                        "stdout_bytes": len(stdout.encode("utf-8", errors="ignore")),
                        "stderr_bytes": len(stderr.encode("utf-8", errors="ignore")),
                    }
                )
            return result

        return self.controller._get_cached_runtime_value(
            f"background:{int(limit)}",
            max_age=0.35,
            force=force,
            producer=_produce,
        )

    @staticmethod
    def _tail_text(value: str, *, max_chars: int = 1200) -> str:
        text = str(value or "")
        if len(text) <= max_chars:
            return text
        return text[-max_chars:]

    def get_runtime_snapshot_payload(self) -> dict[str, Any]:
        structured_tasks = []
        try:
            tasks = self.controller.core.inspector.read("tasks", limit=20)
        except Exception:
            tasks = []
        for task in tasks:
            structured_tasks.append(
                {
                    "task_id": task.get("task_id", ""),
                    "status": task["status"],
                    "title": task.get("title", ""),
                    "parent_task_id": task.get("parent_task_id", None),
                }
            )
        try:
            context = self.controller.core.inspector.read("context")
        except Exception:
            context = {}
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "session": {
                "session_id": self.controller.session_id,
                "title": self.controller.title,
                "checkpoints": self.controller.checkpoints.count,
            },
            "worktree": self.get_worktree_status_payload(),
            "agents": self.get_agent_choices(limit=20),
            "tasks": structured_tasks,
            "background_tasks": self._get_background_task_snapshots(limit=20),
            "context": context,
        }

    def get_worktree_status_payload(self) -> dict[str, Any]:
        payload = self.controller.core.inspector.read("worktree")
        return {**payload, "available": payload["enabled"]}

    def format_worktree_status(self) -> str:
        payload = self.get_worktree_status_payload()
        if not payload.get("available"):
            return "Worktree support is not available in this session."
        active = payload.get("active")
        managed = list(payload.get("managed") or [])
        lines = [f"Managed worktrees: {len(managed)}"]
        if active:
            lines.append(
                f"Current worktree: {active.get('branch') or '-'} @ {active.get('path') or '-'}"
            )
            lines.append(f"Original cwd: {active.get('original_cwd') or '-'}")
            lines.append(
                "Next step: use `/worktree exit keep` to leave it, or `/worktree exit remove discard` only if you want to throw local changes away."
            )
        else:
            lines.append("Current worktree: none")
            lines.append(
                "Next step: use `/worktree enter <name>` to start an isolated coding branch."
            )
        return "\n".join(lines)

    def enter_worktree(self, name: Optional[str] = None) -> str:
        parameters = {"name": str(name).strip()} if str(name or "").strip() else {}
        result = self.controller.core.runtime_action("worktree.enter", parameters)
        self.controller.ensure_autosave()
        return result["text"]

    def exit_worktree(
        self, *, action: str = "keep", discard_changes: bool = False
    ) -> str:
        result = self.controller.core.runtime_action(
            "worktree.exit",
            {
                "action": action,
                "discard_changes": discard_changes,
            },
        )
        self.controller.ensure_autosave()
        return result["text"]

    def get_agent_choices(
        self, *, limit: int = 20, force: bool = False
    ) -> list[dict[str, Any]]:
        def _produce() -> list[dict[str, Any]]:
            return self.controller.core.inspector.read("agents", limit=limit)

        return self.controller._get_cached_runtime_value(
            f"agents:{int(limit)}",
            max_age=0.35,
            force=force,
            producer=_produce,
        )

    def get_task_choices(
        self, *, limit: int = 20, force: bool = False
    ) -> list[dict[str, Any]]:
        def _produce() -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            for task in self.controller.core.inspector.read("tasks", limit=limit):
                seen_ids.add(task["task_id"])
                result.append(
                    {
                        "task_id": task["task_id"],
                        "status": task["status"],
                        "title": task["title"],
                        "kind": "structured",
                    }
                )
            for snapshot in self._get_background_task_snapshots(
                limit=limit, force=force
            ):
                task_id = str(snapshot.get("task_id") or "")
                if not task_id or task_id in seen_ids:
                    continue
                result.append(
                    {
                        "task_id": task_id,
                        "status": str(snapshot.get("status") or ""),
                        "title": str(
                            snapshot.get("command") or snapshot.get("cwd") or task_id
                        ),
                        "kind": "background",
                    }
                )
            return result

        return self.controller._get_cached_runtime_value(
            f"tasks:{int(limit)}",
            max_age=0.35,
            force=force,
            producer=_produce,
        )

    def has_live_runtime_activity(self, *, force: bool = False) -> bool:
        live_task_statuses = {"open", "in_progress", "blocked", "running"}
        live_agent_statuses = {"running", "queued", "waiting", "busy"}
        if any(
            str(item.get("status") or "").lower() in live_agent_statuses
            for item in self.get_agent_choices(limit=100, force=force)
        ):
            return True
        if any(
            str(item.get("status") or "").lower() in live_task_statuses
            for item in self.get_task_choices(limit=100, force=force)
        ):
            return True
        return False

    def format_agent_detail(self, agent_id: str) -> str:
        import json

        return json.dumps(
            self.controller.core.inspector.read("agent", target=agent_id),
            ensure_ascii=False,
            indent=2,
        )

    def wait_for_agent(self, agent_id: str, *, timeout_ms: Optional[int] = None) -> str:
        result = self.controller.core.runtime_action(
            "agent.wait",
            {
                "agent_id": agent_id,
                "timeout_ms": timeout_ms,
            },
        )
        return result["text"]

    def stop_agent(
        self,
        agent_id: str,
        *,
        reason: str = "",
        wait: bool = False,
        timeout_ms: Optional[int] = None,
    ) -> str:
        result = self.controller.core.runtime_action(
            "agent.stop",
            {
                "agent_id": agent_id,
                "reason": reason,
                "wait": wait,
                "timeout_ms": timeout_ms,
            },
        )
        self.controller.ensure_autosave()
        return result["text"]

    def format_task_detail(self, task_id: str) -> str:
        try:
            task = self.controller.core.inspector.read("task", target=task_id)
            lines = [
                f"Task `{task['task_id']}`",
                f"- Status: {task['status']}",
                f"- Title: {task['title']}",
                f"- Parent: {task.get('parent_task_id', None) or 'none'}",
            ]
            return "\n".join(lines)
        except Exception:
            pass
        try:
            snapshot = self.controller.core.inspector.read("process", target=task_id)
        except Exception as exc:
            raise ValueError(f"Task not found: {task_id}") from exc
        stdout_tail = self._tail_text(
            str(snapshot.get("stdout", "") or ""), max_chars=400
        )
        stderr_tail = self._tail_text(
            str(snapshot.get("stderr", "") or ""), max_chars=400
        )
        lines = [
            f"Background task `{snapshot.get('task_id', task_id)}`",
            f"- Status: {snapshot.get('status', '-')}",
            f"- Command: {self.controller.status._format_command_value(snapshot.get('command', '')) or '-'}",
            f"- Working directory: {snapshot.get('cwd', '-') or '-'}",
            f"- Return code: {snapshot.get('return_code', None)}",
        ]
        if stdout_tail.strip():
            lines.append(f"- Stdout tail: {stdout_tail.replace(chr(10), ' ')}")
        if stderr_tail.strip():
            lines.append(f"- Stderr tail: {stderr_tail.replace(chr(10), ' ')}")
        lines.append(
            "Next step: use `/task output <id>` to stream more output or `/task stop <id>` to stop it."
        )
        return "\n".join(lines)

    def format_task_output(
        self, task_id: str, *, block: bool = False, timeout_ms: Optional[int] = None
    ) -> str:
        result = self.controller.core.runtime_action(
            "task.output",
            {
                "task_id": task_id,
                "block": block,
                "timeout": timeout_ms,
            },
        )
        return result["text"]

    def stop_task(self, task_id: str) -> str:
        result = self.controller.core.runtime_action(
            "task.stop",
            {
                "task_id": task_id,
            },
        )
        return result["text"]

    def format_tasks(self, *, limit: int = 20) -> str:
        tasks = self.controller.core.inspector.read("tasks", limit=limit)
        background_tasks = self._get_background_task_snapshots(limit=limit)
        if not tasks and not background_tasks:
            return "No tasks yet."
        active_statuses = {
            "running",
            "queued",
            "waiting",
            "open",
            "in_progress",
            "blocked",
        }
        failed_statuses = {"failed", "error"}

        def _priority(status: str) -> tuple[int, str]:
            lowered = status.lower()
            if lowered in active_statuses:
                return (0, lowered)
            if lowered in failed_statuses:
                return (1, lowered)
            return (2, lowered)

        lines: list[str] = []
        if tasks:
            lines.append("Structured Tasks:")
            for task in sorted(tasks, key=lambda item: _priority(item["status"])):
                lines.append(
                    f"- {task['task_id']} | {task['status']} | {task['title']}"
                )
        if background_tasks:
            if lines:
                lines.append("")
            lines.append("Background Tasks:")
            for item in sorted(
                background_tasks,
                key=lambda task: _priority(str(task.get("status") or "")),
            ):
                command = (
                    self.controller.status._format_command_value(item.get("command"))
                    .replace("\n", " ")
                    .strip()
                )
                if len(command) > 120:
                    command = command[:117].rstrip() + "..."
                duration = item.get("duration_seconds")
                duration_text = (
                    f" | {float(duration):.1f}s"
                    if isinstance(duration, (int, float))
                    else ""
                )
                lines.append(
                    f"- {item.get('task_id') or '-'} | {item.get('status') or '-'} | "
                    f"rc={item.get('return_code')}{duration_text} | {command or item.get('cwd') or '-'}"
                )
                stdout_tail = (
                    str(item.get("stdout_tail") or "").strip().replace(chr(10), " ")
                )
                stderr_tail = (
                    str(item.get("stderr_tail") or "").strip().replace(chr(10), " ")
                )
                if stdout_tail:
                    lines.append(
                        f"  stdout: {self._tail_text(stdout_tail, max_chars=180)}"
                    )
                if stderr_tail:
                    lines.append(
                        f"  stderr: {self._tail_text(stderr_tail, max_chars=180)}"
                    )
        return "\n".join(lines)

    def format_agents(self, *, limit: int = 20) -> str:
        handles = self.get_agent_choices(limit=limit)
        if not handles:
            return "No agents running."
        return "\n".join(
            f"{handle['agent_id']} | {handle['status']} | {handle['name'] or '-'} | "
            f"task={handle['task_id'] or '-'} | output={handle['output_file'] or '-'}"
            for handle in handles
        )

    def format_runtime_panel(self) -> str:
        return self._format_runtime_snapshot(self.get_runtime_snapshot_payload())

    def _format_runtime_snapshot(self, payload: dict[str, Any]) -> str:
        worktree = dict(payload.get("worktree") or {})
        agents = list(payload.get("agents") or [])
        tasks = list(payload.get("tasks") or [])
        background_tasks = list(payload.get("background_tasks") or [])
        context = self.controller.usage._context_usage_summary(
            dict(payload.get("context") or {})
        )
        active_worktree = worktree.get("active") or {}
        lines = [
            f"Runtime snapshot: {payload.get('generated_at') or '-'}",
            f"Session: {self.controller.session_id} | checkpoints={self.controller.checkpoints.count}",
            "",
            "Worktree:",
        ]
        if active_worktree:
            lines.append(
                f"- active: {active_worktree.get('branch') or '-'} @ {active_worktree.get('path') or '-'}"
            )
        else:
            lines.append("- active: none")
        lines.append(f"- managed: {len(list(worktree.get('managed') or []))}")
        lines.extend(["", "Agents:"])
        if agents:
            for agent in agents:
                lines.append(
                    f"- {agent.get('agent_id') or '-'} | {agent.get('status') or '-'} | "
                    f"{agent.get('name') or '-'} | task={agent.get('task_id') or '-'}"
                )
        else:
            lines.append("- none")
        lines.extend(["", "Structured Tasks:"])
        if tasks:
            for task in tasks:
                lines.append(
                    f"- {task.get('task_id') or '-'} | {task.get('status') or '-'} | {task.get('title') or '-'}"
                )
        else:
            lines.append("- none")
        lines.extend(["", "Background Tasks:"])
        if background_tasks:
            for task in background_tasks:
                command = (
                    self.controller.status._format_command_value(task.get("command"))
                    .replace("\n", " ")
                    .strip()
                )
                if len(command) > 120:
                    command = command[:117].rstrip() + "..."
                duration = task.get("duration_seconds")
                duration_text = (
                    f" | {float(duration):.1f}s"
                    if isinstance(duration, (int, float))
                    else ""
                )
                lines.append(
                    f"- {task.get('task_id') or '-'} | {task.get('status') or '-'} | "
                    f"rc={task.get('return_code')}{duration_text} | {command or task.get('cwd') or '-'}"
                )
                stdout_tail = str(task.get("stdout_tail") or "").strip()
                stderr_tail = str(task.get("stderr_tail") or "").strip()
                if stdout_tail:
                    lines.append(
                        f"  stdout tail: {self._tail_text(stdout_tail.replace(chr(10), ' '), max_chars=240)}"
                    )
                if stderr_tail:
                    lines.append(
                        f"  stderr tail: {self._tail_text(stderr_tail.replace(chr(10), ' '), max_chars=240)}"
                    )
        else:
            lines.append("- none")
        if context:
            lines.extend(
                [
                    "",
                    self.controller.usage._format_context_meter_line(context),
                ]
            )
        return "\n".join(lines)

    def poll_runtime_notices(self) -> list[dict[str, str]]:
        snapshots = self._get_background_task_snapshots(limit=50, force=True)
        if not self.controller._last_background_notice_states:
            self.controller._last_background_notice_states = {
                str(item.get("task_id") or ""): str(item.get("status") or "")
                for item in snapshots
                if str(item.get("task_id") or "")
            }
            return []
        notices: list[dict[str, str]] = []
        current_states: dict[str, str] = {}
        for item in snapshots:
            task_id = str(item.get("task_id") or "").strip()
            if not task_id:
                continue
            status = str(item.get("status") or "").strip().lower()
            current_states[task_id] = status
            previous = (
                str(self.controller._last_background_notice_states.get(task_id) or "")
                .strip()
                .lower()
            )
            if not previous or previous == status:
                continue
            if status in {"completed", "failed", "error", "stopped"}:
                command = (
                    self.controller.status._format_command_value(item.get("command"))
                    .replace("\n", " ")
                    .strip()
                )
                stdout_tail = self._tail_text(
                    str(item.get("stdout_tail") or "").replace("\n", " "), max_chars=180
                ).strip()
                stderr_tail = self._tail_text(
                    str(item.get("stderr_tail") or "").replace("\n", " "), max_chars=180
                ).strip()
                headline = {
                    "completed": "Background task finished successfully.",
                    "failed": "Background task failed.",
                    "error": "Background task failed.",
                    "stopped": "Background task was stopped.",
                }[status]
                lines = [
                    headline,
                    f"Task: `{task_id}`",
                    f"Command: {command or '-'}",
                    f"Exit code: {item.get('return_code')}",
                ]
                if stdout_tail:
                    lines.append(f"Stdout: {stdout_tail}")
                if stderr_tail:
                    lines.append(f"Stderr: {stderr_tail}")
                if status == "completed":
                    lines.append(
                        "Next step: inspect the result or continue with the next task."
                    )
                elif status == "stopped":
                    lines.append("Next step: rerun it if you still need the work.")
                else:
                    lines.append(
                        "Next step: use `/task output <id>` for more logs, then retry or fix the failure."
                    )
                notices.append(
                    {
                        "type": "system_notice",
                        "title": "Background Task Update",
                        "content": "\n".join(lines),
                    }
                )
        self.controller._last_background_notice_states = current_states
        return notices
