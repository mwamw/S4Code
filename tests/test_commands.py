from s4code.command_registry import S4CommandRegistry
from s4code.command_types import CommandKind, CommandResult, S4Command, parse_command
from s4code.commands import register_builtin_commands


class _DummyEngine:
    def format_doctor(self) -> str:
        return "doctor"

    def format_models(self) -> str:
        return "models"

    def update_model(self, target: str) -> str:
        return f"switch:{target}"

    def format_context(self) -> str:
        return "context"

    def format_pending_interaction(self) -> str:
        return "pending"

    def format_sessions(self) -> str:
        return "sessions"

    def resume_session(self, session_id: str) -> str:
        return f"resumed:{session_id}"

    def format_current_session(self) -> str:
        return "current-session"

    def format_tools(self) -> str:
        return "tools"

    def format_restore_report(self) -> str:
        return "restore"

    def format_trace(self) -> str:
        return "trace"

    def format_hooks(self) -> str:
        return "hooks"

    def rename_session(self, title: str) -> str:
        return f"renamed:{title}"

    def fork_session(self, title: str | None = None) -> str:
        return f"forked:{title or 'default'}"


def test_parse_command() -> None:
    invocation = parse_command("/review src")
    assert invocation is not None
    assert invocation.name == "review"
    assert invocation.args == ["src"]
    assert invocation.arg_text == "src"


def test_registry_alias_resolution() -> None:
    registry = S4CommandRegistry()

    def _handler(engine, invocation):
        return CommandResult.info(f"handled:{invocation.name}")

    registry.register(
        S4Command(
            name="help",
            kind=CommandKind.LOCAL,
            description="help",
            handler=_handler,
            aliases=("h",),
        )
    )
    result = registry.execute(_DummyEngine(), "/h")
    assert result is not None
    assert result.message == "handled:h"


def test_registry_match_commands() -> None:
    registry = S4CommandRegistry()

    def _handler(engine, invocation):
        return CommandResult.info("ok")

    registry.register(S4Command("help", CommandKind.LOCAL, "help", _handler, aliases=("h",)))
    registry.register(S4Command("hooks", CommandKind.LOCAL, "hooks", _handler))
    registry.register(S4Command("review", CommandKind.WORKFLOW, "review", _handler))

    matches = registry.match_commands("ho")
    assert [item.name for item in matches] == ["hooks"]


def test_registry_match_commands_keeps_full_result_set() -> None:
    registry = S4CommandRegistry()

    def _handler(engine, invocation):
        return CommandResult.info("ok")

    for name in ("help", "hooks", "history", "home", "hosts", "hover", "hold", "howto", "hotfix", "hostsfile"):
        registry.register(S4Command(name, CommandKind.LOCAL, name, _handler))

    matches = registry.match_commands("ho")
    assert len(matches) == 8
    assert matches[0].name == "hold"


def test_builtin_model_and_context_commands() -> None:
    registry = S4CommandRegistry()
    register_builtin_commands(registry)
    engine = _DummyEngine()

    result = registry.execute(engine, "/model")
    assert result is not None
    assert result.message == "models"

    result = registry.execute(engine, "/model local-qwen")
    assert result is not None
    assert result.message == "switch:local-qwen"

    result = registry.execute(engine, "/context")
    assert result is not None
    assert result.message == "context"

    result = registry.execute(engine, "/doctor")
    assert result is not None
    assert result.message == "doctor"

    result = registry.execute(engine, "/tools")
    assert result is not None
    assert result.message == "tools"

    result = registry.execute(engine, "/restore")
    assert result is not None
    assert result.message == "restore"

    result = registry.execute(engine, "/trace")
    assert result is not None
    assert result.message == "trace"

    result = registry.execute(engine, "/hooks")
    assert result is not None
    assert result.message == "hooks"


def test_builtin_pending_and_resolution_commands() -> None:
    registry = S4CommandRegistry()
    register_builtin_commands(registry)
    engine = _DummyEngine()

    result = registry.execute(engine, "/pending")
    assert result is not None
    assert result.message == "pending"

    result = registry.execute(engine, "/confirm")
    assert result is not None
    assert result.metadata["engine_action"] == "confirm_pending"

    result = registry.execute(engine, "/deny too risky")
    assert result is not None
    assert result.metadata["engine_action"] == "deny_pending"
    assert result.metadata["answer"] == "too risky"

    result = registry.execute(engine, "/answer choose option A")
    assert result is not None
    assert result.metadata["engine_action"] == "answer_pending"
    assert result.metadata["answer"] == "choose option A"


def test_builtin_session_subcommands_and_copy_command() -> None:
    registry = S4CommandRegistry()
    register_builtin_commands(registry)
    engine = _DummyEngine()

    result = registry.execute(engine, "/session")
    assert result is not None
    assert result.message == "current-session"

    result = registry.execute(engine, "/session list")
    assert result is not None
    assert result.message == "sessions"

    result = registry.execute(engine, "/session load sess-123")
    assert result is not None
    assert result.message == "resumed:sess-123"

    result = registry.execute(engine, "/session rename Bugfix Investigation")
    assert result is not None
    assert result.message == "renamed:Bugfix Investigation"

    result = registry.execute(engine, "/session fork Parallel Review")
    assert result is not None
    assert result.message == "forked:Parallel Review"

    result = registry.execute(engine, "/copy transcript")
    assert result is not None
    assert result.metadata["ui_action"] == "copy_to_clipboard"
    assert result.metadata["copy_target"] == "transcript"
