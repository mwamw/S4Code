from s4code.command_registry import S4CommandRegistry
from s4code.command_types import CommandKind, CommandResult, S4Command, parse_command
from s4code.commands import register_builtin_commands


class _DummyEngine:
    def format_models(self) -> str:
        return "models"

    def update_model(self, target: str) -> str:
        return f"switch:{target}"

    def format_context(self) -> str:
        return "context"

    def format_pending_interaction(self) -> str:
        return "pending"


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
