"""Behavioral contract for terminal commands."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from .types import CommandInvocation, CommandResult

if TYPE_CHECKING:
    from ..controller import TerminalController


class TerminalCommand(ABC):
    @abstractmethod
    def execute(
        self, controller: TerminalController, invocation: CommandInvocation
    ) -> CommandResult:
        """Interpret terminal arguments and call the appropriate product operation."""
