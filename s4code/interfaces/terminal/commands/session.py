"""Terminal session commands."""

from .base import TerminalCommand
from .types import CommandResult


class ResumeCommand(TerminalCommand):
    def execute(self, engine, invocation):
        if not invocation.arg_text:
            return CommandResult.info(engine.session_view.format_sessions())
        message = engine.resume_session(invocation.arg_text)
        return CommandResult(message=message, refresh_requested=True)


class SessionCommand(TerminalCommand):
    def execute(self, engine, invocation):
        if not invocation.args:
            return CommandResult.info(engine.session_view.format_current_session())
        action = invocation.args[0].lower()
        remainder = invocation.arg_text[len(invocation.args[0]) :].strip()
        if action in {"show", "current"}:
            return CommandResult.info(engine.session_view.format_current_session())
        if action in {"list", "ls"}:
            return CommandResult.info(engine.session_view.format_sessions())
        if action in {"timeline", "history"}:
            return CommandResult.info(engine.checkpoints.format_timeline())
        if action in {"checkpoints", "checkpoint"}:
            return CommandResult.info(engine.checkpoints.format_checkpoints())
        if action in {"tree", "graph"}:
            return CommandResult.info(engine.session_view.format_session_tree())
        if action == "rewind":
            return CommandResult.info(
                engine.checkpoints.rewind_to_checkpoint(remainder or None)
            )
        if action in {"load", "resume"}:
            if not remainder:
                return CommandResult.info(engine.session_view.format_sessions())
            message = engine.resume_session(remainder)
            return CommandResult(message=message, refresh_requested=True)
        if action == "rename":
            if not remainder:
                return CommandResult.info("Usage: /session rename <title>")
            return CommandResult.info(engine.rename_session(remainder))
        if action == "fork":
            return CommandResult.info(engine.fork_session(remainder or None))
        return CommandResult.info(
            "Usage: /session [show|list|load <id>|rename <title>|fork [title]|timeline|checkpoints|rewind <checkpoint>|tree]"
        )


class ClearCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(engine.clear_history())


class CompactCommand(TerminalCommand):
    def execute(self, engine, invocation):
        if not invocation.args:
            return CommandResult.info(engine.compact_history())
        if invocation.args[0].lower() in {"partial", "target"}:
            if len(invocation.args) < 2:
                return CommandResult.info(
                    "Usage: /compact [partial <max_tokens>|<max_tokens>]"
                )
            try:
                return CommandResult.info(
                    engine.compact_history(max_tokens=int(invocation.args[1]))
                )
            except ValueError:
                return CommandResult.info(
                    "Usage: /compact [partial <max_tokens>|<max_tokens>]"
                )
        try:
            return CommandResult.info(
                engine.compact_history(max_tokens=int(invocation.args[0]))
            )
        except ValueError:
            return CommandResult.info(
                "Usage: /compact [partial <max_tokens>|<max_tokens>]"
            )


class RestoreCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(engine.session_view.format_restore_report())


class CheckpointCommand(TerminalCommand):
    def execute(self, engine, invocation):
        if invocation.args and invocation.args[0].lower() in {"list", "ls", "show"}:
            return CommandResult.info(engine.checkpoints.format_checkpoints())
        label = invocation.arg_text or None
        payload = engine.checkpoints.create_checkpoint(label, reason="manual")
        return CommandResult.info(
            f"Checkpoint created: {payload.get('checkpoint_id')} | {payload.get('label')} | messages={payload.get('history_messages', 0)}"
        )


class CheckpointsCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(engine.checkpoints.format_checkpoints())


class RewindCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(
            engine.checkpoints.rewind_to_checkpoint(invocation.arg_text or None)
        )


class TimelineCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(engine.checkpoints.format_timeline())
