"""Slash command registry."""

from __future__ import annotations

from typing import Optional

from .command_types import CommandInvocation, CommandResult, S4Command, parse_command


class S4CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, S4Command] = {}
        self._aliases: dict[str, str] = {}

    def register(self, command: S4Command) -> S4Command:
        key = command.name.lower()
        self._commands[key] = command
        for alias in command.aliases:
            self._aliases[alias.lower()] = key
        return command

    def get(self, name: str) -> Optional[S4Command]:
        key = self._aliases.get(name.lower(), name.lower())
        return self._commands.get(key)

    def parse(self, text: str) -> CommandInvocation | None:
        return parse_command(text)

    def execute(self, engine: object, text: str) -> CommandResult | None:
        invocation = self.parse(text)
        if invocation is None:
            return None
        command = self.get(invocation.name)
        if command is None:
            return CommandResult.info(f"Unknown command: /{invocation.name}")
        return command.handler(engine, invocation)

    def list_commands(self) -> list[S4Command]:
        return sorted(self._commands.values(), key=lambda item: item.name)

    def match_commands(self, prefix: str) -> list[S4Command]:
        normalized = str(prefix or "").strip().lower()
        commands = self.list_commands()
        if not normalized:
            return commands
        return [
            command
            for command in commands
            if command.name.startswith(normalized)
            or any(alias.startswith(normalized) for alias in command.aliases)
        ]
