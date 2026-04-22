"""Builtin slash commands."""

from __future__ import annotations

from ..command_types import CommandKind, CommandResult, S4Command


def _help(engine, invocation):
    return CommandResult.info(engine.format_help())


def _status(engine, invocation):
    return CommandResult.info(engine.format_status())


def _model(engine, invocation):
    if not invocation.arg_text:
        return CommandResult.info(engine.format_models())
    return CommandResult.info(engine.update_model(invocation.arg_text))


def _config(engine, invocation):
    return CommandResult.info(engine.format_config())


def _permissions(engine, invocation):
    if not invocation.arg_text:
        return CommandResult.info(
            f"Current permission mode: {engine.agent.permission_context.mode.value}"
        )
    return CommandResult.info(engine.update_permission_mode(invocation.arg_text))


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
    return CommandResult.info(engine.format_current_session())


def _pending(engine, invocation):
    return CommandResult.info(engine.format_pending_interaction())


def _clear(engine, invocation):
    return CommandResult.info(engine.clear_history())


def _compact(engine, invocation):
    return CommandResult.info(engine.compact_history())


def _cost(engine, invocation):
    return CommandResult.info(engine.format_cost())


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


def _mcp(engine, invocation):
    return CommandResult.info(engine.format_mcp())


def _hooks(engine, invocation):
    return CommandResult.info(engine.format_hooks())


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
    registry.register(S4Command("config", CommandKind.LOCAL, "Show the resolved S4Code config.", _config))
    registry.register(
        S4Command(
            "permissions",
            CommandKind.LOCAL,
            "Show or change the permission mode.",
            _permissions,
            aliases=("perm",),
            usage="[default|accept_edits|dont_ask|bypass|plan]",
        )
    )
    registry.register(S4Command("plan", CommandKind.LOCAL, "Enter or exit plan mode.", _plan, usage="[on|off]"))
    registry.register(S4Command("resume", CommandKind.LOCAL, "Resume a saved session or list sessions.", _resume, usage="[session_id]"))
    registry.register(S4Command("session", CommandKind.LOCAL, "Show the current session details.", _session))
    registry.register(S4Command("pending", CommandKind.LOCAL, "Show the current pending confirmation/question.", _pending))
    registry.register(S4Command("clear", CommandKind.LOCAL, "Clear conversation history.", _clear))
    registry.register(S4Command("compact", CommandKind.LOCAL, "Compact conversation history.", _compact))
    registry.register(S4Command("context", CommandKind.LOCAL, "Show current context window usage and compaction state.", _context))
    registry.register(S4Command("cost", CommandKind.LOCAL, "Show observability and token usage summary.", _cost))
    registry.register(S4Command("files", CommandKind.LOCAL, "List project files.", _files, usage="[path]"))
    registry.register(S4Command("diff", CommandKind.LOCAL, "Show git diff for the current repository.", _diff, usage="[target]"))
    registry.register(S4Command("review", CommandKind.WORKFLOW, "Run a code review workflow against the current diff.", _review, usage="[target]"))
    registry.register(S4Command("commit", CommandKind.WORKFLOW, "Draft a commit proposal from the current diff.", _commit))
    registry.register(S4Command("tasks", CommandKind.LOCAL, "List structured tasks.", _tasks))
    registry.register(S4Command("agents", CommandKind.LOCAL, "List runtime agents.", _agents))
    registry.register(S4Command("mcp", CommandKind.LOCAL, "Show configured MCP servers.", _mcp))
    registry.register(S4Command("hooks", CommandKind.LOCAL, "List installed hooks/guardrails.", _hooks))
    registry.register(
        S4Command(
            "confirm",
            CommandKind.LOCAL,
            "Approve the current pending confirmation and continue execution.",
            _confirm,
            aliases=("approve",),
            usage="[note]",
        )
    )
    registry.register(
        S4Command(
            "deny",
            CommandKind.LOCAL,
            "Deny the current pending confirmation/question and continue execution.",
            _deny,
            usage="[reason]",
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
