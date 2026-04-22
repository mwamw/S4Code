from s4code.command_registry import S4CommandRegistry
from s4code.command_types import CommandKind, CommandResult, S4Command, parse_command


class _DummyEngine:
    pass


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
