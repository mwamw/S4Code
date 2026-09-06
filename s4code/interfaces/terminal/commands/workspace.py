"""Terminal workspace commands."""

from .base import TerminalCommand
from .types import CommandResult


class HelpCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(engine.status.format_help())


class StatusCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(engine.status.format_status_overview())


class CostCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(engine.usage.format_cost())


class TraceCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(engine.usage.format_trace())


class ToolsCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(engine.status.format_tools())


class ContextCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(engine.usage.format_context())


class FilesCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(
            engine.workspace_view.format_files(invocation.arg_text or ".")
        )


class DiffCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(
            engine.workspace_view.format_diff(invocation.arg_text or None)
        )


class ReviewCommand(TerminalCommand):
    def execute(self, engine, invocation):
        target = invocation.arg_text or None
        return CommandResult.workflow(
            engine.build_review_prompt(target),
            message=f"Running review for {target or 'current diff'}...",
        )


class CommitCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.workflow(
            engine.build_commit_prompt(),
            message="Drafting commit proposal...",
        )


class HooksCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(engine.status.format_hooks())


class SidebarCommand(TerminalCommand):
    def execute(self, engine, invocation):
        if not invocation.arg_text:
            return CommandResult.info(engine.status.toggle_sidebar())
        action = invocation.arg_text.strip().lower()
        if action in {"show", "on", "open"}:
            return CommandResult.info(engine.status.toggle_sidebar(True))
        if action in {"hide", "off", "close"}:
            return CommandResult.info(engine.status.toggle_sidebar(False))
        return CommandResult.info("Usage: /sidebar [show|hide]")


class CopyCommand(TerminalCommand):
    def execute(self, engine, invocation):
        target = (invocation.arg_text or "transcript").strip().lower()
        if target not in {"transcript", "last"}:
            return CommandResult.info("Usage: /copy [transcript|last]")
        return CommandResult(
            metadata={"ui_action": "copy_to_clipboard", "copy_target": target}
        )


class ExitCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult(message="Exiting S4Code.", exit_requested=True)
