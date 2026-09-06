"""Terminal settings commands."""

from .base import TerminalCommand
from .types import CommandResult


class ModelCommand(TerminalCommand):
    def execute(self, engine, invocation):
        if not invocation.arg_text:
            return CommandResult.info(engine.status.format_models())
        return CommandResult.info(engine.update_model(invocation.arg_text))


class ThemeCommand(TerminalCommand):
    def execute(self, engine, invocation):
        if not invocation.args:
            return CommandResult.info(engine.theme.format_themes())
        action = invocation.args[0].lower()
        if action in {"list", "ls", "show"}:
            return CommandResult.info(engine.theme.format_themes())
        message = engine.theme.update_theme(invocation.arg_text)
        if message.startswith("Unknown theme:"):
            return CommandResult.info(message)
        return CommandResult(
            message=message,
            metadata={"ui_action": "reload_theme"},
        )


class ConfigCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(engine.status.format_config())


class DoctorCommand(TerminalCommand):
    def execute(self, engine, invocation):
        return CommandResult.info(engine.status.format_doctor())


class PermissionsCommand(TerminalCommand):
    def execute(self, engine, invocation):
        if not invocation.args:
            return CommandResult.info(engine.permissions.format_permissions())
        action = invocation.args[0].lower()
        mode_names = {"default", "accept_edits", "dont_ask", "bypass", "plan"}
        if action in {"show", "status", "rules", "list", "ls"}:
            return CommandResult.info(engine.permissions.format_permissions())
        if action in {"history", "log"}:
            return CommandResult.info(engine.permissions.format_permission_history())
        if action == "mode":
            if len(invocation.args) < 2:
                return CommandResult.info(engine.permissions.format_permissions())
            return CommandResult.info(
                engine.permissions.update_permission_mode(invocation.args[1])
            )
        if action in mode_names:
            return CommandResult.info(engine.permissions.update_permission_mode(action))
        if action in {"allow", "deny", "ask"}:
            if len(invocation.args) < 2:
                return CommandResult.info(
                    "Usage: /permissions [allow|deny|ask] <tool|*> [path=...] [host=...] [command=...] [mcp=...] [risk=...]"
                )
            return CommandResult.info(
                engine.permissions.add_permission_rule_from_tokens(
                    behavior=action,
                    tool_name=invocation.args[1],
                    tokens=invocation.args[2:],
                )
            )
        if action in {"clear", "reset"}:
            source = invocation.args[1] if len(invocation.args) > 1 else "session"
            return CommandResult.info(
                engine.permissions.clear_permission_rules(source=source)
            )
        return CommandResult.info(engine.permissions.format_permissions())


class PlanCommand(TerminalCommand):
    def execute(self, engine, invocation):
        action = invocation.args[0].lower() if invocation.args else "on"
        if action in {"off", "exit", "disable"}:
            return CommandResult.info(engine.permissions.exit_plan_mode())
        return CommandResult.info(engine.permissions.enter_plan_mode())
