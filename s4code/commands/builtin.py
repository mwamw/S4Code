"""Builtin slash commands."""

from __future__ import annotations

from ..command_types import CommandKind, CommandResult, S4Command


def _parse_timeout_ms(raw: str | None) -> int | None:
    if raw in (None, ""):
        return None
    return int(raw)


def _help(engine, invocation):
    return CommandResult.info(engine.format_help())


def _status(engine, invocation):
    return CommandResult.info(engine.format_status())


def _model(engine, invocation):
    if not invocation.arg_text:
        return CommandResult.info(engine.format_models())
    return CommandResult.info(engine.update_model(invocation.arg_text))


def _theme(engine, invocation):
    if not invocation.args:
        return CommandResult.info(engine.format_themes())
    action = invocation.args[0].lower()
    if action in {"list", "ls", "show"}:
        return CommandResult.info(engine.format_themes())
    message = engine.update_theme(invocation.arg_text)
    if message.startswith("Unknown theme:"):
        return CommandResult.info(message)
    return CommandResult(
        message=message,
        metadata={"ui_action": "reload_theme"},
    )


def _config(engine, invocation):
    return CommandResult.info(engine.format_config())


def _doctor(engine, invocation):
    return CommandResult.info(engine.format_doctor())


def _permissions(engine, invocation):
    if not invocation.args:
        return CommandResult.info(engine.format_permissions())
    action = invocation.args[0].lower()
    mode_names = {"default", "accept_edits", "dont_ask", "bypass", "plan"}
    if action in {"show", "status", "rules", "list", "ls"}:
        return CommandResult.info(engine.format_permissions())
    if action in {"history", "log"}:
        return CommandResult.info(engine.format_permission_history())
    if action == "mode":
        if len(invocation.args) < 2:
            return CommandResult.info(engine.format_permissions())
        return CommandResult.info(engine.update_permission_mode(invocation.args[1]))
    if action in mode_names:
        return CommandResult.info(engine.update_permission_mode(action))
    if action in {"allow", "deny", "ask"}:
        if len(invocation.args) < 2:
            return CommandResult.info(
                "Usage: /permissions [allow|deny|ask] <tool|*> [path=...] [host=...] [command=...] [mcp=...] [risk=...]"
            )
        return CommandResult.info(
            engine.add_permission_rule_from_tokens(
                behavior=action,
                tool_name=invocation.args[1],
                tokens=invocation.args[2:],
            )
        )
    if action in {"clear", "reset"}:
        source = invocation.args[1] if len(invocation.args) > 1 else "session"
        return CommandResult.info(engine.clear_permission_rules(source=source))
    return CommandResult.info(engine.format_permissions())


def _plan(engine, invocation):
    action = (invocation.args[0].lower() if invocation.args else "on")
    if action in {"off", "exit", "disable"}:
        return CommandResult.info(engine.exit_plan_mode())
    return CommandResult.info(engine.enter_plan_mode())


def _resume(engine, invocation):
    if not invocation.arg_text:
        return CommandResult.info(engine.format_sessions())
    message = engine.resume_session(invocation.arg_text)
    return CommandResult(message=message, refresh_requested=True)


def _session(engine, invocation):
    if not invocation.args:
        return CommandResult.info(engine.format_current_session())
    action = invocation.args[0].lower()
    remainder = invocation.arg_text[len(invocation.args[0]) :].strip()
    if action in {"show", "current"}:
        return CommandResult.info(engine.format_current_session())
    if action in {"list", "ls"}:
        return CommandResult.info(engine.format_sessions())
    if action in {"timeline", "history"}:
        return CommandResult.info(engine.format_timeline())
    if action in {"checkpoints", "checkpoint"}:
        return CommandResult.info(engine.format_checkpoints())
    if action in {"tree", "graph"}:
        return CommandResult.info(engine.format_session_tree())
    if action == "rewind":
        return CommandResult.info(engine.rewind_to_checkpoint(remainder or None))
    if action in {"load", "resume"}:
        if not remainder:
            return CommandResult.info(engine.format_sessions())
        message = engine.resume_session(remainder)
        return CommandResult(message=message, refresh_requested=True)
    if action == "rename":
        if not remainder:
            return CommandResult.info("Usage: /session rename <title>")
        return CommandResult.info(engine.rename_session(remainder))
    if action == "fork":
        return CommandResult.info(engine.fork_session(remainder or None))
    return CommandResult.info("Usage: /session [show|list|load <id>|rename <title>|fork [title]|timeline|checkpoints|rewind <checkpoint>|tree]")


def _pending(engine, invocation):
    return CommandResult.info(engine.format_pending_interaction())


def _clear(engine, invocation):
    return CommandResult.info(engine.clear_history())


def _compact(engine, invocation):
    if not invocation.args:
        return CommandResult.info(engine.compact_history())
    if invocation.args[0].lower() in {"partial", "target"}:
        if len(invocation.args) < 2:
            return CommandResult.info("Usage: /compact [partial <max_tokens>|<max_tokens>]")
        try:
            return CommandResult.info(engine.compact_history(max_tokens=int(invocation.args[1])))
        except ValueError:
            return CommandResult.info("Usage: /compact [partial <max_tokens>|<max_tokens>]")
    try:
        return CommandResult.info(engine.compact_history(max_tokens=int(invocation.args[0])))
    except ValueError:
        return CommandResult.info("Usage: /compact [partial <max_tokens>|<max_tokens>]")


def _cost(engine, invocation):
    return CommandResult.info(engine.format_cost())


def _trace(engine, invocation):
    return CommandResult.info(engine.format_trace())


def _restore(engine, invocation):
    return CommandResult.info(engine.format_restore_report())


def _checkpoint(engine, invocation):
    if invocation.args and invocation.args[0].lower() in {"list", "ls", "show"}:
        return CommandResult.info(engine.format_checkpoints())
    label = invocation.arg_text or None
    payload = engine.create_checkpoint(label, reason="manual")
    return CommandResult.info(
        f"Checkpoint created: {payload.get('checkpoint_id')} | {payload.get('label')} | messages={payload.get('history_messages', 0)}"
    )


def _checkpoints(engine, invocation):
    return CommandResult.info(engine.format_checkpoints())


def _rewind(engine, invocation):
    return CommandResult.info(engine.rewind_to_checkpoint(invocation.arg_text or None))


def _timeline(engine, invocation):
    return CommandResult.info(engine.format_timeline())


def _tools(engine, invocation):
    return CommandResult.info(engine.format_tools())


def _context(engine, invocation):
    return CommandResult.info(engine.format_context())


def _files(engine, invocation):
    return CommandResult.info(engine.format_files(invocation.arg_text or "."))


def _diff(engine, invocation):
    return CommandResult.info(engine.format_diff(invocation.arg_text or None))


def _review(engine, invocation):
    target = invocation.arg_text or None
    return CommandResult.workflow(
        engine.build_review_prompt(target),
        message=f"Running review for {target or 'current diff'}...",
    )


def _commit(engine, invocation):
    return CommandResult.workflow(
        engine.build_commit_prompt(),
        message="Drafting commit proposal...",
    )


def _tasks(engine, invocation):
    return CommandResult.info(engine.format_tasks())


def _agents(engine, invocation):
    return CommandResult.info(engine.format_agents())


def _runtime(engine, invocation):
    return CommandResult.info(engine.format_runtime_panel())


def _mcp(engine, invocation):
    if not invocation.args:
        return CommandResult.info(engine.format_mcp())
    action = invocation.args[0].lower()
    remainder = invocation.arg_text[len(invocation.args[0]) :].strip()
    if action in {"list", "ls", "show"}:
        return CommandResult.info(engine.format_mcp())
    if action == "status":
        if not remainder:
            return CommandResult.info(engine.format_mcp())
        return CommandResult.info(engine.format_mcp_server_detail(remainder))
    if action == "tools":
        if not remainder:
            return CommandResult.info("Usage: /mcp tools <server>")
        return CommandResult.info(engine.format_mcp_tools(remainder))
    if action in {"resources", "res"}:
        if not remainder:
            return CommandResult.info("Usage: /mcp resources <server>")
        return CommandResult.info(engine.format_mcp_resources(remainder))
    if action in {"refresh", "reload"}:
        return CommandResult.info(engine.refresh_mcp(remainder or None))
    if action in {"connect", "reconnect"}:
        return CommandResult.info(engine.connect_mcp(remainder or None))
    if action in {"disconnect", "close"}:
        return CommandResult.info(engine.disconnect_mcp(remainder or None))
    return CommandResult.info(
        "Usage: /mcp [list|status <server>|tools <server>|resources <server>|refresh [server]|connect [server]|disconnect [server]]"
    )


def _hooks(engine, invocation):
    return CommandResult.info(engine.format_hooks())


def _skills(engine, invocation):
    if not invocation.args:
        return CommandResult.info(engine.format_skills())
    action = invocation.args[0].lower()
    remainder = invocation.arg_text[len(invocation.args[0]) :].strip()
    if action in {"list", "ls", "show"}:
        return CommandResult.info(engine.format_skills())
    if action in {"use", "enable", "select"}:
        if not remainder:
            return CommandResult.info(engine.format_skills())
        return CommandResult.info(engine.queue_turn_skill(remainder))
    if action in {"clear", "reset", "off"}:
        return CommandResult.info(engine.clear_turn_skills())
    return CommandResult.info("Usage: /skills [list|use <name>|clear]")


def _worktree(engine, invocation):
    if not invocation.args:
        return CommandResult.info(engine.format_worktree_status())
    action = invocation.args[0].lower()
    if action in {"show", "status"}:
        return CommandResult.info(engine.format_worktree_status())
    if action == "enter":
        name = invocation.arg_text[len(invocation.args[0]) :].strip() or None
        return CommandResult.info(engine.enter_worktree(name))
    if action in {"exit", "close"}:
        mode = "keep"
        discard = False
        for token in invocation.args[1:]:
            lowered = token.lower()
            if lowered in {"keep", "remove"}:
                mode = lowered
            elif lowered in {"discard", "force"}:
                discard = True
            else:
                return CommandResult.info("Usage: /worktree [show|enter [name]|exit [keep|remove] [discard]]")
        return CommandResult.info(engine.exit_worktree(action=mode, discard_changes=discard))
    return CommandResult.info("Usage: /worktree [show|enter [name]|exit [keep|remove] [discard]]")


def _agent(engine, invocation):
    if not invocation.args:
        return CommandResult.info(engine.format_agents())
    action = invocation.args[0].lower()
    if action in {"list", "ls"}:
        return CommandResult.info(engine.format_agents())
    if action in {"show", "get"}:
        if len(invocation.args) < 2:
            return CommandResult.info("Usage: /agent show <agent_id>")
        return CommandResult.info(engine.format_agent_detail(invocation.args[1]))
    if action == "wait":
        if len(invocation.args) < 2:
            return CommandResult.info("Usage: /agent wait <agent_id> [timeout_ms]")
        try:
            timeout_ms = _parse_timeout_ms(invocation.args[2] if len(invocation.args) > 2 else None)
        except ValueError:
            return CommandResult.info("Usage: /agent wait <agent_id> [timeout_ms]")
        return CommandResult.info(engine.wait_for_agent(invocation.args[1], timeout_ms=timeout_ms))
    if action == "stop":
        if len(invocation.args) < 2:
            return CommandResult.info("Usage: /agent stop <agent_id> [reason]")
        reason = invocation.arg_text.split(maxsplit=2)[2].strip() if len(invocation.args) > 2 else ""
        return CommandResult.info(engine.stop_agent(invocation.args[1], reason=reason))
    return CommandResult.info("Usage: /agent [list|show <agent_id>|wait <agent_id> [timeout_ms]|stop <agent_id> [reason]]")


def _task(engine, invocation):
    if not invocation.args:
        return CommandResult.info("Usage: /task [show <task_id>|output <task_id> [timeout_ms]|stop <task_id>]")
    action = invocation.args[0].lower()
    if action in {"show", "get"}:
        if len(invocation.args) < 2:
            return CommandResult.info("Usage: /task show <task_id>")
        return CommandResult.info(engine.format_task_detail(invocation.args[1]))
    if action == "output":
        if len(invocation.args) < 2:
            return CommandResult.info("Usage: /task output <task_id> [timeout_ms]")
        try:
            timeout_ms = _parse_timeout_ms(invocation.args[2] if len(invocation.args) > 2 else None)
        except ValueError:
            return CommandResult.info("Usage: /task output <task_id> [timeout_ms]")
        return CommandResult.info(engine.format_task_output(invocation.args[1], block=timeout_ms is not None, timeout_ms=timeout_ms))
    if action == "stop":
        if len(invocation.args) < 2:
            return CommandResult.info("Usage: /task stop <task_id>")
        return CommandResult.info(engine.stop_task(invocation.args[1]))
    return CommandResult.info("Usage: /task [show <task_id>|output <task_id> [timeout_ms]|stop <task_id>]")


def _confirm(engine, invocation):
    return CommandResult(
        message="Confirming the pending interaction and resuming execution...",
        metadata={"engine_action": "confirm_pending", "answer": invocation.arg_text},
    )


def _deny(engine, invocation):
    return CommandResult(
        message="Denying the pending interaction and resuming execution...",
        metadata={"engine_action": "deny_pending", "answer": invocation.arg_text},
    )


def _answer(engine, invocation):
    if not invocation.arg_text:
        return CommandResult.info("Usage: /answer <text>")
    return CommandResult(
        message="Submitting the answer and resuming execution...",
        metadata={"engine_action": "answer_pending", "answer": invocation.arg_text},
    )


def _sidebar(engine, invocation):
    if not invocation.arg_text:
        return CommandResult.info(engine.toggle_sidebar())
    action = invocation.arg_text.strip().lower()
    if action in {"show", "on", "open"}:
        return CommandResult.info(engine.toggle_sidebar(True))
    if action in {"hide", "off", "close"}:
        return CommandResult.info(engine.toggle_sidebar(False))
    return CommandResult.info("Usage: /sidebar [show|hide]")


def _copy(engine, invocation):
    target = (invocation.arg_text or "transcript").strip().lower()
    if target not in {"transcript", "last"}:
        return CommandResult.info("Usage: /copy [transcript|last]")
    return CommandResult(metadata={"ui_action": "copy_to_clipboard", "copy_target": target})


def _exit(engine, invocation):
    return CommandResult(message="Exiting S4Code.", exit_requested=True)


def register_builtin_commands(registry) -> None:
    registry.register(
        S4Command("help", CommandKind.LOCAL, "Show available slash commands.", _help, aliases=("h",), usage="[command]")
    )
    registry.register(S4Command("status", CommandKind.LOCAL, "Show the current product/runtime status.", _status))
    registry.register(
        S4Command(
            "model",
            CommandKind.LOCAL,
            "Show model profiles or switch to a profile/literal model.",
            _model,
            usage="[profile-name|literal-model]",
        )
    )
    registry.register(
        S4Command(
            "theme",
            CommandKind.LOCAL,
            "List or switch the TUI theme.",
            _theme,
            aliases=("themes",),
            usage="[list|theme-name|theme-json-path]",
        )
    )
    registry.register(S4Command("config", CommandKind.LOCAL, "Show the resolved S4Code config.", _config))
    registry.register(S4Command("doctor", CommandKind.LOCAL, "Show an end-to-end product diagnostics payload.", _doctor))
    registry.register(
        S4Command(
            "permissions",
            CommandKind.LOCAL,
            "Show mode/rules, change mode, or add/clear permission rules.",
            _permissions,
            aliases=("perm",),
            usage="[show|mode <mode>|allow|deny|ask <tool> [matchers]|clear [source]|history]",
        )
    )
    registry.register(S4Command("plan", CommandKind.LOCAL, "Enter or exit plan mode.", _plan, usage="[on|off]"))
    registry.register(S4Command("resume", CommandKind.LOCAL, "Resume a saved session or list sessions.", _resume, usage="[session_id]"))
    registry.register(
        S4Command(
            "session",
            CommandKind.LOCAL,
            "Show, list, load, rename, fork, or inspect session timeline/checkpoints.",
            _session,
            usage="[show|list|load <session_id>|rename <title>|fork [title]|timeline|checkpoints|rewind <checkpoint>|tree]",
        )
    )
    registry.register(S4Command("pending", CommandKind.LOCAL, "Show the current pending confirmation/question.", _pending))
    registry.register(
        S4Command(
            "copy",
            CommandKind.LOCAL,
            "Copy the full transcript or the latest card to the clipboard.",
            _copy,
            usage="[transcript|last]",
        )
    )
    registry.register(S4Command("clear", CommandKind.LOCAL, "Clear conversation history.", _clear))
    registry.register(S4Command("compact", CommandKind.LOCAL, "Compact conversation history.", _compact, usage="[partial <max_tokens>|<max_tokens>]"))
    registry.register(S4Command("context", CommandKind.LOCAL, "Show current context window usage and compaction state.", _context))
    registry.register(S4Command("cost", CommandKind.LOCAL, "Show observability and token usage summary.", _cost))
    registry.register(S4Command("trace", CommandKind.LOCAL, "Show recent turn-level trace summaries.", _trace))
    registry.register(S4Command("restore", CommandKind.LOCAL, "Show the latest session restore report.", _restore))
    registry.register(S4Command("checkpoint", CommandKind.LOCAL, "Create or list restorable conversation checkpoints.", _checkpoint, usage="[label|list]"))
    registry.register(S4Command("checkpoints", CommandKind.LOCAL, "List restorable conversation checkpoints.", _checkpoints))
    registry.register(S4Command("rewind", CommandKind.LOCAL, "Restore conversation history to a checkpoint.", _rewind, usage="[checkpoint_id|index|last]"))
    registry.register(S4Command("timeline", CommandKind.LOCAL, "Show session checkpoints and recent trace timeline.", _timeline))
    registry.register(S4Command("tools", CommandKind.LOCAL, "List the currently registered tool surface.", _tools))
    registry.register(S4Command("files", CommandKind.LOCAL, "List project files.", _files, usage="[path]"))
    registry.register(S4Command("diff", CommandKind.LOCAL, "Show git diff for the current repository.", _diff, usage="[target]"))
    registry.register(S4Command("review", CommandKind.WORKFLOW, "Run a code review workflow against the current diff.", _review, usage="[target]"))
    registry.register(S4Command("commit", CommandKind.WORKFLOW, "Draft a commit proposal from the current diff.", _commit))
    registry.register(S4Command("tasks", CommandKind.LOCAL, "List structured and background tasks.", _tasks))
    registry.register(
        S4Command(
            "task",
            CommandKind.LOCAL,
            "Inspect a task, read background task output, or stop a background task.",
            _task,
            usage="[show <task_id>|output <task_id> [timeout_ms]|stop <task_id>]",
        )
    )
    registry.register(S4Command("agents", CommandKind.LOCAL, "List runtime agents.", _agents))
    registry.register(
        S4Command(
            "agent",
            CommandKind.LOCAL,
            "Inspect, wait for, or stop a runtime agent handle.",
            _agent,
            usage="[list|show <agent_id>|wait <agent_id> [timeout_ms]|stop <agent_id> [reason]]",
        )
    )
    registry.register(
        S4Command(
            "runtime",
            CommandKind.LOCAL,
            "Show the live worktree, agent, and task runtime panel.",
            _runtime,
            aliases=("rt",),
        )
    )
    registry.register(
        S4Command(
            "mcp",
            CommandKind.LOCAL,
            "Inspect MCP server status and control MCP connections.",
            _mcp,
            usage="[list|status <server>|tools <server>|resources <server>|refresh [server]|connect [server]|disconnect [server]]",
        )
    )
    registry.register(
        S4Command(
            "skills",
            CommandKind.LOCAL,
            "List discovered skills or queue one for the next turn.",
            _skills,
            usage="[list|use <name>|clear]",
        )
    )
    registry.register(
        S4Command(
            "worktree",
            CommandKind.LOCAL,
            "Inspect or control the current worktree runtime.",
            _worktree,
            usage="[show|enter [name]|exit [keep|remove] [discard]]",
        )
    )
    registry.register(S4Command("hooks", CommandKind.LOCAL, "List installed hooks/guardrails.", _hooks))
    registry.register(
        S4Command(
            "confirm",
            CommandKind.LOCAL,
            "Approve the current pending confirmation and continue execution; use 'remember' to add a session rule.",
            _confirm,
            aliases=("approve",),
            usage="[note|remember]",
        )
    )
    registry.register(
        S4Command(
            "deny",
            CommandKind.LOCAL,
            "Deny the current pending confirmation/question; use 'remember' to add a session deny rule.",
            _deny,
            usage="[reason|remember]",
        )
    )
    registry.register(
        S4Command(
            "answer",
            CommandKind.LOCAL,
            "Answer the current AskUserQuestion interaction and continue execution.",
            _answer,
            usage="<text>",
        )
    )
    registry.register(S4Command("sidebar", CommandKind.LOCAL, "Show or hide the right-side info panel.", _sidebar, usage="[show|hide]"))
    registry.register(S4Command("exit", CommandKind.LOCAL, "Exit the current S4Code session.", _exit, aliases=("quit", "q")))
