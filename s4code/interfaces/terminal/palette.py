"""Shared command palette construction for S4Code frontends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CommandPaletteEntry:
    label: str
    description: str
    insert_text: str
    execute_text: str
    mode: str = "insert"
    aliases: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "description": self.description,
            "insert_text": self.insert_text,
            "execute_text": self.execute_text,
            "mode": self.mode,
            "aliases": list(self.aliases),
        }


class S4CommandPaletteBuilder:
    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def build(self, current_text: str) -> dict[str, Any]:
        entries, state_key = self.build_entries(current_text)
        return {
            "state_key": state_key,
            "entries": [entry.to_payload() for entry in entries],
        }

    def build_entries(self, current_text: str) -> tuple[list[CommandPaletteEntry], str]:
        text = str(current_text or "").strip()
        if not text.startswith("/"):
            return ([], "")
        if text == "/":
            commands = self._sort_commands_for_palette(
                self.engine.command_registry.list_commands()
            )
            return (
                [self._command_to_palette_entry(command) for command in commands],
                "commands:",
            )
        invocation = self.engine.command_registry.parse(text)
        if invocation is None:
            return ([], "")

        if invocation.name == "model":
            fragment = invocation.arg_text.strip().lower()
            entries: list[CommandPaletteEntry] = []
            for item in self.engine.status.get_model_choices():
                name = str(item["name"])
                provider = str(item["provider"])
                model = str(item["model"])
                if (
                    fragment
                    and fragment not in name.lower()
                    and fragment not in provider.lower()
                    and fragment not in model.lower()
                ):
                    continue
                marker = "* " if item.get("active") else ""
                entries.append(
                    CommandPaletteEntry(
                        label=f"{marker}{name}",
                        description=f"{provider} / {model}",
                        insert_text=f"/model {name}",
                        execute_text=f"/model {name}",
                        mode="execute",
                    )
                )
            return (entries, f"model:{fragment}")

        if invocation.name in {"theme", "themes"}:
            fragment = invocation.arg_text.strip().lower()
            entries = [
                CommandPaletteEntry(
                    "/theme list",
                    "List available TUI themes.",
                    "/theme list",
                    "/theme list",
                    mode="execute",
                ),
            ]
            for item in self.engine.theme.get_theme_choices():
                name = str(item.get("name") or "")
                kind = str(item.get("kind") or "theme")
                if (
                    fragment
                    and fragment not in name.lower()
                    and fragment not in kind.lower()
                ):
                    continue
                marker = "* " if item.get("active") else ""
                entries.append(
                    CommandPaletteEntry(
                        label=f"{marker}{name}",
                        description=f"{kind} theme",
                        insert_text=f"/theme {name}",
                        execute_text=f"/theme {name}",
                        mode="execute",
                    )
                )
            return (entries, f"theme:{fragment}")

        if invocation.name == "resume":
            fragment = invocation.arg_text.strip().lower()
            return (
                self._build_session_palette_entries(fragment, prefix="/resume "),
                f"resume:{fragment}",
            )

        if invocation.name in {"permissions", "perm"}:
            return self._build_permissions_entries(invocation)

        if invocation.name == "plan":
            fragment = invocation.arg_text.strip().lower()
            entries = [
                CommandPaletteEntry(
                    "/plan on",
                    "Enter plan mode.",
                    "/plan on",
                    "/plan on",
                    mode="execute",
                ),
                CommandPaletteEntry(
                    "/plan off",
                    "Exit plan mode.",
                    "/plan off",
                    "/plan off",
                    mode="execute",
                ),
            ]
            return (self._filter_entries(entries, fragment), f"plan:{fragment}")

        if invocation.name == "copy":
            fragment = invocation.arg_text.strip().lower()
            entries = [
                CommandPaletteEntry(
                    "/copy transcript",
                    "Copy the full transcript.",
                    "/copy transcript",
                    "/copy transcript",
                    mode="execute",
                ),
                CommandPaletteEntry(
                    "/copy last",
                    "Copy only the latest card.",
                    "/copy last",
                    "/copy last",
                    mode="execute",
                ),
            ]
            return (self._filter_entries(entries, fragment), f"copy:{fragment}")

        if invocation.name == "skills":
            if not invocation.args:
                entries = [
                    CommandPaletteEntry(
                        "/skills list",
                        "List discovered skills.",
                        "/skills list",
                        "/skills list",
                        mode="execute",
                    ),
                    CommandPaletteEntry(
                        "/skills clear",
                        "Clear the next-turn skill queue.",
                        "/skills clear",
                        "/skills clear",
                        mode="execute",
                    ),
                ]
                entries.extend(
                    self._build_skill_palette_entries("", prefix="/skills use ")
                )
                return (entries, "skills:root")
            subcommand = invocation.args[0].lower()
            remainder = invocation.arg_text[len(invocation.args[0]) :].strip().lower()
            if subcommand in {"use", "enable", "select", "queue"}:
                return (
                    self._build_skill_palette_entries(remainder, prefix="/skills use "),
                    f"skills-use:{remainder}",
                )

        if invocation.name == "mcp":
            return self._build_mcp_entries(invocation)

        if invocation.name == "worktree":
            return self._build_worktree_entries(invocation)

        if invocation.name == "agent":
            return self._build_agent_entries(invocation)

        if invocation.name == "task":
            return self._build_task_entries(invocation)

        if invocation.name == "session":
            return self._build_session_entries(invocation)

        if invocation.name == "rewind":
            fragment = invocation.arg_text.strip().lower()
            return (
                self._build_checkpoint_palette_entries(fragment, prefix="/rewind "),
                f"rewind:{fragment}",
            )

        if invocation.name in {"checkpoint", "checkpoints"}:
            fragment = invocation.arg_text.strip().lower()
            entries = [
                CommandPaletteEntry(
                    "/checkpoint list",
                    "List restorable checkpoints.",
                    "/checkpoint list",
                    "/checkpoint list",
                    mode="execute",
                ),
                CommandPaletteEntry(
                    "/checkpoint",
                    "Create a checkpoint with an optional label.",
                    "/checkpoint ",
                    "/checkpoint ",
                    mode="insert",
                ),
            ]
            return (self._filter_entries(entries, fragment), f"checkpoint:{fragment}")

        if invocation.name == "sidebar":
            fragment = invocation.arg_text.strip().lower()
            entries = [
                CommandPaletteEntry(
                    "/sidebar show",
                    "Show the right-side info panel.",
                    "/sidebar show",
                    "/sidebar show",
                    mode="execute",
                ),
                CommandPaletteEntry(
                    "/sidebar hide",
                    "Hide the right-side info panel.",
                    "/sidebar hide",
                    "/sidebar hide",
                    mode="execute",
                ),
            ]
            return (self._filter_entries(entries, fragment), f"sidebar:{fragment}")

        command_fragment = invocation.name
        if " " not in text[1:]:
            matches = self._sort_commands_for_palette(
                self.engine.command_registry.match_commands(command_fragment)
            )
            return (
                [self._command_to_palette_entry(command) for command in matches],
                f"commands:{command_fragment}",
            )
        return ([], f"noop:{text}")

    def _build_permissions_entries(
        self, invocation: Any
    ) -> tuple[list[CommandPaletteEntry], str]:
        if not invocation.args:
            entries = [
                CommandPaletteEntry(
                    "/permissions show",
                    "Show current permission mode and rules.",
                    "/permissions show",
                    "/permissions show",
                    mode="execute",
                ),
                CommandPaletteEntry(
                    "/permissions history",
                    "Show permission mode/rule change history.",
                    "/permissions history",
                    "/permissions history",
                    mode="execute",
                ),
                CommandPaletteEntry(
                    "/permissions mode",
                    "Switch permission mode.",
                    "/permissions mode ",
                    "/permissions mode ",
                    mode="insert",
                ),
                CommandPaletteEntry(
                    "/permissions allow",
                    "Add an allow rule.",
                    "/permissions allow ",
                    "/permissions allow ",
                    mode="insert",
                ),
                CommandPaletteEntry(
                    "/permissions deny",
                    "Add a deny rule.",
                    "/permissions deny ",
                    "/permissions deny ",
                    mode="insert",
                ),
                CommandPaletteEntry(
                    "/permissions ask",
                    "Add an ask/confirm rule.",
                    "/permissions ask ",
                    "/permissions ask ",
                    mode="insert",
                ),
                CommandPaletteEntry(
                    "/permissions clear session",
                    "Clear session-scoped permission rules.",
                    "/permissions clear session",
                    "/permissions clear session",
                    mode="execute",
                ),
                CommandPaletteEntry(
                    "/permissions clear all",
                    "Clear all permission rule sources.",
                    "/permissions clear all",
                    "/permissions clear all",
                    mode="execute",
                ),
            ]
            return (entries, "permissions:root")
        subcommand = invocation.args[0].lower()
        if subcommand == "mode":
            fragment = invocation.arg_text[len(invocation.args[0]) :].strip().lower()
            modes = ("default", "accept_edits", "dont_ask", "bypass", "plan")
            entries = [
                CommandPaletteEntry(
                    label=mode,
                    description=f"Set permission mode to {mode}.",
                    insert_text=f"/permissions mode {mode}",
                    execute_text=f"/permissions mode {mode}",
                    mode="execute",
                )
                for mode in modes
                if not fragment or fragment in mode
            ]
            return (entries, f"permissions-mode:{fragment}")
        if subcommand in {"allow", "deny", "ask"}:
            fragment = invocation.arg_text[len(invocation.args[0]) :].strip().lower()
            entries = [
                CommandPaletteEntry(
                    label=f"/permissions {subcommand} *",
                    description="Match all tools. Add path=, host=, command=, mcp=, or risk= to narrow scope.",
                    insert_text=f"/permissions {subcommand} * ",
                    execute_text=f"/permissions {subcommand} * ",
                    mode="insert",
                ),
                CommandPaletteEntry(
                    label=f"/permissions {subcommand} FileEdit path=",
                    description="Match file edits under a path prefix.",
                    insert_text=f"/permissions {subcommand} FileEdit path=",
                    execute_text=f"/permissions {subcommand} FileEdit path=",
                    mode="insert",
                ),
                CommandPaletteEntry(
                    label=f"/permissions {subcommand} WebFetch host=",
                    description="Match WebFetch by hostname/domain.",
                    insert_text=f"/permissions {subcommand} WebFetch host=",
                    execute_text=f"/permissions {subcommand} WebFetch host=",
                    mode="insert",
                ),
                CommandPaletteEntry(
                    label=f"/permissions {subcommand} Bash command=",
                    description="Match shell commands by command prefix.",
                    insert_text=f"/permissions {subcommand} Bash command=",
                    execute_text=f"/permissions {subcommand} Bash command=",
                    mode="insert",
                ),
            ]
            return (
                self._filter_entries(entries, fragment),
                f"permissions-rule:{subcommand}:{fragment}",
            )
        if subcommand in {"clear", "reset"}:
            fragment = invocation.arg_text[len(invocation.args[0]) :].strip().lower()
            sources = ("session", "all")
            entries = [
                CommandPaletteEntry(
                    label=source,
                    description=f"Clear {source} permission rules.",
                    insert_text=f"/permissions clear {source}",
                    execute_text=f"/permissions clear {source}",
                    mode="execute",
                )
                for source in sources
                if not fragment or fragment in source
            ]
            return (entries, f"permissions-clear:{fragment}")
        return ([], f"permissions:{subcommand}")

    def _build_mcp_entries(
        self, invocation: Any
    ) -> tuple[list[CommandPaletteEntry], str]:
        if not invocation.args:
            entries = [
                CommandPaletteEntry(
                    "/mcp list",
                    "List MCP services and connection status.",
                    "/mcp list",
                    "/mcp list",
                    mode="execute",
                ),
                CommandPaletteEntry(
                    "/mcp status",
                    "Show one MCP service in detail.",
                    "/mcp status ",
                    "/mcp status ",
                    mode="insert",
                ),
                CommandPaletteEntry(
                    "/mcp tools",
                    "List tools exposed by one MCP service.",
                    "/mcp tools ",
                    "/mcp tools ",
                    mode="insert",
                ),
                CommandPaletteEntry(
                    "/mcp resources",
                    "List resources exposed by one MCP service.",
                    "/mcp resources ",
                    "/mcp resources ",
                    mode="insert",
                ),
                CommandPaletteEntry(
                    "/mcp refresh",
                    "Refresh one MCP service or all services.",
                    "/mcp refresh ",
                    "/mcp refresh ",
                    mode="insert",
                ),
                CommandPaletteEntry(
                    "/mcp connect",
                    "Connect one MCP service or all services.",
                    "/mcp connect ",
                    "/mcp connect ",
                    mode="insert",
                ),
                CommandPaletteEntry(
                    "/mcp disconnect",
                    "Disconnect one MCP service or all services.",
                    "/mcp disconnect ",
                    "/mcp disconnect ",
                    mode="insert",
                ),
            ]
            return (entries, "mcp:root")
        subcommand = invocation.args[0].lower()
        remainder = invocation.arg_text[len(invocation.args[0]) :].strip().lower()
        if subcommand == "status":
            return (
                self._build_mcp_palette_entries(remainder, prefix="/mcp status "),
                f"mcp-status:{remainder}",
            )
        if subcommand == "tools":
            return (
                self._build_mcp_palette_entries(remainder, prefix="/mcp tools "),
                f"mcp-tools:{remainder}",
            )
        if subcommand in {"resources", "res"}:
            return (
                self._build_mcp_palette_entries(remainder, prefix="/mcp resources "),
                f"mcp-resources:{remainder}",
            )
        if subcommand in {"refresh", "reload"}:
            return (
                self._build_mcp_palette_entries(
                    remainder, prefix="/mcp refresh ", include_all=True
                ),
                f"mcp-refresh:{remainder}",
            )
        if subcommand in {"connect", "reconnect"}:
            return (
                self._build_mcp_palette_entries(
                    remainder, prefix="/mcp connect ", include_all=True
                ),
                f"mcp-connect:{remainder}",
            )
        if subcommand in {"disconnect", "close"}:
            return (
                self._build_mcp_palette_entries(
                    remainder, prefix="/mcp disconnect ", include_all=True
                ),
                f"mcp-disconnect:{remainder}",
            )
        return ([], f"mcp:{subcommand}")

    def _build_worktree_entries(
        self, invocation: Any
    ) -> tuple[list[CommandPaletteEntry], str]:
        if not invocation.args:
            payload = self.engine.runtime.get_worktree_status_payload()
            active = payload.get("active") or {}
            description = "Show the current worktree runtime status."
            if active:
                description = f"Active: {active.get('branch') or '-'} · {active.get('path') or '-'}"
            entries = [
                CommandPaletteEntry(
                    "/worktree show",
                    description,
                    "/worktree show",
                    "/worktree show",
                    mode="execute",
                ),
                CommandPaletteEntry(
                    "/worktree enter",
                    "Create and enter a managed worktree.",
                    "/worktree enter ",
                    "/worktree enter ",
                    mode="insert",
                ),
                CommandPaletteEntry(
                    "/worktree exit keep",
                    "Leave the active worktree and keep it on disk.",
                    "/worktree exit keep",
                    "/worktree exit keep",
                    mode="execute",
                ),
                CommandPaletteEntry(
                    "/worktree exit remove discard",
                    "Leave and delete the active worktree, discarding changes.",
                    "/worktree exit remove discard",
                    "/worktree exit remove discard",
                    mode="execute",
                ),
            ]
            return (entries, "worktree:root")
        subcommand = invocation.args[0].lower()
        if subcommand in {"exit", "close"}:
            entries = [
                CommandPaletteEntry(
                    "/worktree exit keep",
                    "Leave the active worktree and keep it on disk.",
                    "/worktree exit keep",
                    "/worktree exit keep",
                    mode="execute",
                ),
                CommandPaletteEntry(
                    "/worktree exit remove",
                    "Leave the active worktree and remove it if clean.",
                    "/worktree exit remove",
                    "/worktree exit remove",
                    mode="execute",
                ),
                CommandPaletteEntry(
                    "/worktree exit remove discard",
                    "Leave and delete the active worktree, discarding changes.",
                    "/worktree exit remove discard",
                    "/worktree exit remove discard",
                    mode="execute",
                ),
            ]
            return (entries, f"worktree-exit:{subcommand}")
        return ([], f"worktree:{subcommand}")

    def _build_agent_entries(
        self, invocation: Any
    ) -> tuple[list[CommandPaletteEntry], str]:
        if not invocation.args:
            entries = [
                CommandPaletteEntry(
                    "/agent list",
                    "List runtime agent handles.",
                    "/agent list",
                    "/agent list",
                    mode="execute",
                ),
            ]
            entries.extend(self._build_agent_palette_entries("", prefix="/agent show "))
            return (entries, "agent:root")
        subcommand = invocation.args[0].lower()
        remainder = invocation.arg_text[len(invocation.args[0]) :].strip().lower()
        if subcommand in {"show", "get"}:
            return (
                self._build_agent_palette_entries(
                    remainder, prefix=f"/agent {subcommand} "
                ),
                f"agent-show:{remainder}",
            )
        if subcommand == "wait":
            return (
                self._build_agent_palette_entries(remainder, prefix="/agent wait "),
                f"agent-wait:{remainder}",
            )
        if subcommand == "stop":
            return (
                self._build_agent_palette_entries(remainder, prefix="/agent stop "),
                f"agent-stop:{remainder}",
            )
        return ([], f"agent:{subcommand}")

    def _build_task_entries(
        self, invocation: Any
    ) -> tuple[list[CommandPaletteEntry], str]:
        if not invocation.args:
            entries = [
                CommandPaletteEntry(
                    "/tasks",
                    "List structured tasks.",
                    "/tasks",
                    "/tasks",
                    mode="execute",
                ),
            ]
            entries.extend(self._build_task_palette_entries("", prefix="/task show "))
            return (entries, "task:root")
        subcommand = invocation.args[0].lower()
        remainder = invocation.arg_text[len(invocation.args[0]) :].strip().lower()
        if subcommand in {"show", "get"}:
            return (
                self._build_task_palette_entries(
                    remainder, prefix=f"/task {subcommand} "
                ),
                f"task-show:{remainder}",
            )
        if subcommand == "output":
            return (
                self._build_task_palette_entries(remainder, prefix="/task output "),
                f"task-output:{remainder}",
            )
        if subcommand == "stop":
            return (
                self._build_task_palette_entries(remainder, prefix="/task stop "),
                f"task-stop:{remainder}",
            )
        return ([], f"task:{subcommand}")

    def _build_session_entries(
        self, invocation: Any
    ) -> tuple[list[CommandPaletteEntry], str]:
        if not invocation.args:
            entries = [
                CommandPaletteEntry(
                    "/session show",
                    "Show the current session details.",
                    "/session show",
                    "/session show",
                    mode="execute",
                ),
                CommandPaletteEntry(
                    "/session list",
                    "List saved S4Code sessions.",
                    "/session list",
                    "/session list",
                    mode="execute",
                ),
                CommandPaletteEntry(
                    "/session timeline",
                    "Show checkpoint and trace timeline.",
                    "/session timeline",
                    "/session timeline",
                    mode="execute",
                ),
                CommandPaletteEntry(
                    "/session checkpoints",
                    "List restorable checkpoints.",
                    "/session checkpoints",
                    "/session checkpoints",
                    mode="execute",
                ),
                CommandPaletteEntry(
                    "/session tree",
                    "Show fork/restore session tree.",
                    "/session tree",
                    "/session tree",
                    mode="execute",
                ),
                CommandPaletteEntry(
                    "/session rewind",
                    "Restore history to a checkpoint.",
                    "/session rewind ",
                    "/session rewind ",
                    mode="insert",
                ),
                CommandPaletteEntry(
                    "/session load",
                    "Load a saved session.",
                    "/session load ",
                    "/session load ",
                    mode="insert",
                ),
                CommandPaletteEntry(
                    "/session rename",
                    "Rename the current session.",
                    "/session rename ",
                    "/session rename ",
                    mode="insert",
                ),
                CommandPaletteEntry(
                    "/session fork",
                    "Fork the current session into a new branch session.",
                    "/session fork ",
                    "/session fork ",
                    mode="insert",
                ),
            ]
            entries.extend(
                self._build_session_palette_entries("", prefix="/session load ")
            )
            return (entries, "session:root")
        subcommand = invocation.args[0].lower()
        remainder = invocation.arg_text[len(invocation.args[0]) :].strip().lower()
        if subcommand in {"load", "resume"}:
            return (
                self._build_session_palette_entries(
                    remainder, prefix=f"/session {subcommand} "
                ),
                f"session-load:{remainder}",
            )
        if subcommand == "rewind":
            return (
                self._build_checkpoint_palette_entries(
                    remainder, prefix="/session rewind "
                ),
                f"session-rewind:{remainder}",
            )
        return ([], f"session:{subcommand}")

    @staticmethod
    def _filter_entries(
        entries: list[CommandPaletteEntry], fragment: str
    ) -> list[CommandPaletteEntry]:
        if not fragment:
            return entries
        return [
            entry
            for entry in entries
            if fragment in entry.label.lower() or fragment in entry.description.lower()
        ]

    def _command_to_palette_entry(self, command: Any) -> CommandPaletteEntry:
        usage = f" {command.usage}" if command.usage else ""
        insert_text = f"/{command.name}"
        if command.usage:
            insert_text += " "
        return CommandPaletteEntry(
            label=f"/{command.name}{usage}",
            description=f"[{command.category}] {command.description}",
            insert_text=insert_text,
            execute_text=f"/{command.name}",
            mode="insert",
            aliases=tuple(command.aliases),
        )

    def _sort_commands_for_palette(self, commands: list[Any]) -> list[Any]:
        pending_active = self._safe_call(
            lambda: self.engine.permissions.get_pending_interaction() is not None, False
        )
        background_active = any(
            str(item.get("status") or "").lower() in {"running", "queued", "waiting"}
            for item in self._safe_call(
                lambda: self.engine.runtime.get_task_choices(limit=30), []
            )
        )
        recent_usage = {
            name: index
            for index, name in enumerate(
                self._safe_call(self.engine.get_recent_command_usage, [])
            )
        }

        def _score(command: Any) -> tuple[int, int, int, str]:
            name = str(command.name)
            state_bonus = 0
            if pending_active and name in {"confirm", "deny", "answer", "pending"}:
                state_bonus = -1000
            elif background_active and name in {"tasks", "task", "runtime"}:
                state_bonus = -800
            elif self.engine.session_view.was_restored() and name in {
                "restore",
                "session",
                "pending",
                "diff",
            }:
                state_bonus = -600
            recent_bonus = recent_usage.get(name, 999)
            return (
                state_bonus - int(getattr(command, "priority", 0) or 0),
                recent_bonus,
                0 if getattr(command, "category", "") else 1,
                name,
            )

        return sorted(commands, key=_score)

    def _build_session_palette_entries(
        self, fragment: str, *, prefix: str
    ) -> list[CommandPaletteEntry]:
        entries: list[CommandPaletteEntry] = []
        for item in self._safe_call(self.engine.session_view.get_session_choices, []):
            session_id = str(item["session_id"])
            title = str(item["title"] or session_id)
            project_root = str(item.get("project_root") or "-")
            model = str(item.get("model") or "-")
            provider = str(item.get("provider") or "-")
            search_blob = " ".join(
                [session_id, title, project_root, model, provider]
            ).lower()
            if fragment and fragment not in search_blob:
                continue
            marker = "* " if item.get("current") else ""
            entries.append(
                CommandPaletteEntry(
                    label=f"{marker}{session_id}",
                    description=f"{title} · {provider}/{model} · {project_root}",
                    insert_text=f"{prefix}{session_id}",
                    execute_text=f"{prefix}{session_id}",
                    mode="execute",
                )
            )
        return entries

    def _build_skill_palette_entries(
        self, fragment: str, *, prefix: str
    ) -> list[CommandPaletteEntry]:
        entries: list[CommandPaletteEntry] = []
        for item in self._safe_call(self.engine.skills.get_skill_choices, []):
            name = str(item["name"])
            listing = str(
                item.get("listing_description") or item.get("description") or name
            )
            source = str(item.get("source_path") or item.get("source_type") or "-")
            search_blob = " ".join(
                [name, listing, str(item.get("when_to_use") or ""), source]
            ).lower()
            if fragment and fragment not in search_blob:
                continue
            marker = "* " if item.get("pending") else ""
            entries.append(
                CommandPaletteEntry(
                    label=f"{marker}{name}",
                    description=f"{item.get('exposure_mode')}/{item.get('execution_mode')} · {listing} · {source}",
                    insert_text=f"{prefix}{name}",
                    execute_text=f"{prefix}{name}",
                    mode="execute",
                )
            )
        return entries

    def _build_agent_palette_entries(
        self, fragment: str, *, prefix: str
    ) -> list[CommandPaletteEntry]:
        entries: list[CommandPaletteEntry] = []
        for item in self._safe_call(self.engine.runtime.get_agent_choices, []):
            agent_id = str(item.get("agent_id") or "")
            status = str(item.get("status") or "-")
            name = str(item.get("name") or "-")
            task_id = str(item.get("task_id") or "-")
            output_file = str(item.get("output_file") or "-")
            search_blob = " ".join(
                [agent_id, status, name, task_id, output_file]
            ).lower()
            if fragment and fragment not in search_blob:
                continue
            entries.append(
                CommandPaletteEntry(
                    label=agent_id,
                    description=f"{status} · {name} · task={task_id} · output={output_file}",
                    insert_text=f"{prefix}{agent_id}",
                    execute_text=f"{prefix}{agent_id}",
                    mode="execute",
                )
            )
        return entries

    def _build_task_palette_entries(
        self, fragment: str, *, prefix: str
    ) -> list[CommandPaletteEntry]:
        entries: list[CommandPaletteEntry] = []
        for item in self._safe_call(self.engine.runtime.get_task_choices, []):
            task_id = str(item.get("task_id") or "")
            status = str(item.get("status") or "-")
            title = str(item.get("title") or task_id)
            kind = str(item.get("kind") or "-")
            search_blob = " ".join([task_id, status, title, kind]).lower()
            if fragment and fragment not in search_blob:
                continue
            entries.append(
                CommandPaletteEntry(
                    label=task_id,
                    description=f"{status} · {kind} · {title}",
                    insert_text=f"{prefix}{task_id}",
                    execute_text=f"{prefix}{task_id}",
                    mode="execute",
                )
            )
        return entries

    def _build_checkpoint_palette_entries(
        self, fragment: str, *, prefix: str
    ) -> list[CommandPaletteEntry]:
        entries: list[CommandPaletteEntry] = []
        for item in self._safe_call(self.engine.checkpoints.get_checkpoint_choices, []):
            checkpoint_id = str(item.get("checkpoint_id") or "")
            label = str(item.get("label") or checkpoint_id)
            reason = str(item.get("reason") or "-")
            created_at = str(item.get("created_at") or "-")
            search_blob = " ".join([checkpoint_id, label, reason, created_at]).lower()
            if fragment and fragment not in search_blob:
                continue
            entries.append(
                CommandPaletteEntry(
                    label=checkpoint_id,
                    description=f"{label} · {reason} · {created_at}",
                    insert_text=f"{prefix}{checkpoint_id}",
                    execute_text=f"{prefix}{checkpoint_id}",
                    mode="execute",
                )
            )
        if not entries and not fragment:
            entries.append(
                CommandPaletteEntry(
                    label="last",
                    description="Rewind to the latest checkpoint.",
                    insert_text=f"{prefix}last",
                    execute_text=f"{prefix}last",
                    mode="execute",
                )
            )
        return entries

    def _build_mcp_palette_entries(
        self, fragment: str, *, prefix: str, include_all: bool = False
    ) -> list[CommandPaletteEntry]:
        entries: list[CommandPaletteEntry] = []
        if include_all and (not fragment or "all".startswith(fragment)):
            entries.append(
                CommandPaletteEntry(
                    label="all",
                    description="Apply this action to all MCP services.",
                    insert_text=prefix.rstrip(),
                    execute_text=prefix.rstrip(),
                    mode="execute",
                )
            )
        for item in self._safe_call(
            lambda: self.engine.mcp.get_mcp_status_payload(include_capabilities=False),
            [],
        ):
            server_name = str(item.get("server_name") or "").strip()
            if not server_name:
                continue
            status = str(item.get("status") or "-").strip()
            transport = str(item.get("transport_summary") or "-").strip()
            last_error = str(item.get("last_error") or "").strip()
            search_blob = " ".join([server_name, status, transport, last_error]).lower()
            if fragment and fragment not in search_blob:
                continue
            marker = "* " if status == "connected" else ""
            description = f"{status} · {transport}"
            if last_error:
                description += f" · {last_error}"
            entries.append(
                CommandPaletteEntry(
                    label=f"{marker}{server_name}",
                    description=description,
                    insert_text=f"{prefix}{server_name}",
                    execute_text=f"{prefix}{server_name}",
                    mode="execute",
                )
            )
        return entries

    @staticmethod
    def _safe_call(producer: Any, fallback: Any) -> Any:
        try:
            return producer()
        except Exception:
            return fallback
