"""Slash command types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class CommandKind(str, Enum):
    LOCAL = "local"
    WORKFLOW = "workflow"
    PROMPT = "prompt"


@dataclass(slots=True)
class CommandInvocation:
    raw_text: str
    name: str
    args: list[str]
    arg_text: str


@dataclass(slots=True)
class CommandResult:
    message: Optional[str] = None
    should_query: bool = False
    query: Optional[str] = None
    exit_requested: bool = False
    refresh_requested: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def info(cls, message: str) -> "CommandResult":
        return cls(message=message)

    @classmethod
    def workflow(cls, query: str, *, message: Optional[str] = None) -> "CommandResult":
        return cls(message=message, should_query=True, query=query)


CommandHandler = Callable[[Any, CommandInvocation], CommandResult]


@dataclass(slots=True)
class S4Command:
    name: str
    kind: CommandKind
    description: str
    handler: CommandHandler
    aliases: tuple[str, ...] = ()
    usage: str = ""


def parse_command(raw_text: str) -> CommandInvocation | None:
    text = str(raw_text or "").strip()
    if not text.startswith("/"):
        return None
    body = text[1:].strip()
    if not body:
        return None
    parts = body.split()
    name = parts[0].lower()
    args = parts[1:]
    arg_text = body[len(parts[0]) :].strip()
    return CommandInvocation(
        raw_text=text,
        name=name,
        args=args,
        arg_text=arg_text,
    )

