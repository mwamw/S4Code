"""Terminal runtime commands."""

from .base import TerminalCommand
from .types import CommandResult


def _parse_timeout_ms(raw):
    return None if raw in (None, "") else int(raw)


class PendingCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(engine.permissions.format_pending_interaction())


class TasksCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(engine.runtime.format_tasks())


class AgentsCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(engine.runtime.format_agents())


class RuntimeCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(engine.runtime.format_runtime_panel())


class McpCommand(TerminalCommand):
    def execute(self, engine, invocation):
        if not invocation.args:
            return CommandResult.info(engine.mcp.format_mcp())
        action = invocation.args[0].lower()
        remainder = invocation.arg_text[len(invocation.args[0]) :].strip()
        if action in {"list", "ls", "show"}:
            return CommandResult.info(engine.mcp.format_mcp())
        if action == "status":
            if not remainder:
                return CommandResult.info(engine.mcp.format_mcp())
            return CommandResult.info(engine.mcp.format_mcp_server_detail(remainder))
        if action == "tools":
            if not remainder:
                return CommandResult.info("Usage: /mcp tools <server>")
            return CommandResult.info(engine.mcp.format_mcp_tools(remainder))
        if action in {"resources", "res"}:
            if not remainder:
                return CommandResult.info("Usage: /mcp resources <server>")
            return CommandResult.info(engine.mcp.format_mcp_resources(remainder))
        if action in {"refresh", "reload"}:
            return CommandResult.info(engine.mcp.refresh_mcp(remainder or None))
        if action in {"connect", "reconnect"}:
            return CommandResult.info(engine.mcp.connect_mcp(remainder or None))
        if action in {"disconnect", "close"}:
            return CommandResult.info(engine.mcp.disconnect_mcp(remainder or None))
        return CommandResult.info(
            "Usage: /mcp [list|status <server>|tools <server>|resources <server>|refresh [server]|connect [server]|disconnect [server]]"
        )


class SkillsCommand(TerminalCommand):
    def execute(self, engine, invocation):
        if not invocation.args:
            return CommandResult.info(engine.skills.format_skills())
        action = invocation.args[0].lower()
        remainder = invocation.arg_text[len(invocation.args[0]) :].strip()
        if action in {"list", "ls", "show"}:
            return CommandResult.info(engine.skills.format_skills())
        if action in {"use", "enable", "select"}:
            if not remainder:
                return CommandResult.info(engine.skills.format_skills())
            return CommandResult.info(engine.skills.queue_turn_skill(remainder))
        if action in {"clear", "reset", "off"}:
            return CommandResult.info(engine.skills.clear_turn_skills())
        return CommandResult.info("Usage: /skills [list|use <name>|clear]")


class WorktreeCommand(TerminalCommand):
    def execute(self, engine, invocation):
        if not invocation.args:
            return CommandResult.info(engine.runtime.format_worktree_status())
        action = invocation.args[0].lower()
        if action in {"show", "status"}:
            return CommandResult.info(engine.runtime.format_worktree_status())
        if action == "enter":
            name = invocation.arg_text[len(invocation.args[0]) :].strip() or None
            return CommandResult.info(engine.runtime.enter_worktree(name))
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
                    return CommandResult.info(
                        "Usage: /worktree [show|enter [name]|exit [keep|remove] [discard]]"
                    )
            return CommandResult.info(
                engine.runtime.exit_worktree(action=mode, discard_changes=discard)
            )
        return CommandResult.info(
            "Usage: /worktree [show|enter [name]|exit [keep|remove] [discard]]"
        )


class AgentCommand(TerminalCommand):
    def execute(self, engine, invocation):
        if not invocation.args:
            return CommandResult.info(engine.runtime.format_agents())
        action = invocation.args[0].lower()
        if action in {"list", "ls"}:
            return CommandResult.info(engine.runtime.format_agents())
        if action in {"show", "get"}:
            if len(invocation.args) < 2:
                return CommandResult.info("Usage: /agent show <agent_id>")
            return CommandResult.info(
                engine.runtime.format_agent_detail(invocation.args[1])
            )
        if action == "wait":
            if len(invocation.args) < 2:
                return CommandResult.info("Usage: /agent wait <agent_id> [timeout_ms]")
            try:
                timeout_ms = _parse_timeout_ms(
                    invocation.args[2] if len(invocation.args) > 2 else None
                )
            except ValueError:
                return CommandResult.info("Usage: /agent wait <agent_id> [timeout_ms]")
            return CommandResult.info(
                engine.runtime.wait_for_agent(invocation.args[1], timeout_ms=timeout_ms)
            )
        if action == "stop":
            if len(invocation.args) < 2:
                return CommandResult.info("Usage: /agent stop <agent_id> [reason]")
            reason = (
                invocation.arg_text.split(maxsplit=2)[2].strip()
                if len(invocation.args) > 2
                else ""
            )
            return CommandResult.info(
                engine.runtime.stop_agent(invocation.args[1], reason=reason)
            )
        return CommandResult.info(
            "Usage: /agent [list|show <agent_id>|wait <agent_id> [timeout_ms]|stop <agent_id> [reason]]"
        )


class TaskCommand(TerminalCommand):
    def execute(self, engine, invocation):
        if not invocation.args:
            return CommandResult.info(
                "Usage: /task [show <task_id>|output <task_id> [timeout_ms]|stop <task_id>]"
            )
        action = invocation.args[0].lower()
        if action in {"show", "get"}:
            if len(invocation.args) < 2:
                return CommandResult.info("Usage: /task show <task_id>")
            return CommandResult.info(
                engine.runtime.format_task_detail(invocation.args[1])
            )
        if action == "output":
            if len(invocation.args) < 2:
                return CommandResult.info("Usage: /task output <task_id> [timeout_ms]")
            try:
                timeout_ms = _parse_timeout_ms(
                    invocation.args[2] if len(invocation.args) > 2 else None
                )
            except ValueError:
                return CommandResult.info("Usage: /task output <task_id> [timeout_ms]")
            return CommandResult.info(
                engine.runtime.format_task_output(
                    invocation.args[1],
                    block=timeout_ms is not None,
                    timeout_ms=timeout_ms,
                )
            )
        if action == "stop":
            if len(invocation.args) < 2:
                return CommandResult.info("Usage: /task stop <task_id>")
            return CommandResult.info(engine.runtime.stop_task(invocation.args[1]))
        return CommandResult.info(
            "Usage: /task [show <task_id>|output <task_id> [timeout_ms]|stop <task_id>]"
        )


class ConfirmCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult(
            message="Confirming the pending interaction and resuming execution...",
            metadata={
                "engine_action": "confirm_pending",
                "answer": invocation.arg_text,
            },
        )


class DenyCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult(
            message="Denying the pending interaction and resuming execution...",
            metadata={"engine_action": "deny_pending", "answer": invocation.arg_text},
        )


class AnswerCommand(TerminalCommand):
    def execute(self, engine, invocation):
        if not invocation.arg_text:
            return CommandResult.info("Usage: /answer <text>")
        return CommandResult(
            message="Submitting the answer and resuming execution...",
            metadata={"engine_action": "answer_pending", "answer": invocation.arg_text},
        )
