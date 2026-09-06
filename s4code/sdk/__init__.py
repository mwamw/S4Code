"""Stable Python product interface. Agent implementation lives in s4code.core."""

from .client import AsyncS4Code, S4Code
from .session import AsyncSession, Session
from s4code.core.contracts import (
    InteractionRequest,
    RunEvent,
    RunOptions,
    RunResult,
    SessionInfo,
)
from s4code.core.errors import (
    BusyError,
    ClosedError,
    InvalidRequestError,
    S4CodeError,
    SessionNotFoundError,
)
from s4code.core.settings import S4AgentSettings, LLMSettings

__all__ = [
    "S4Code",
    "AsyncS4Code",
    "Session",
    "AsyncSession",
    "RunOptions",
    "RunResult",
    "RunEvent",
    "SessionInfo",
    "InteractionRequest",
    "S4CodeError",
    "BusyError",
    "ClosedError",
    "InvalidRequestError",
    "SessionNotFoundError",
    "S4AgentSettings",
    "LLMSettings",
]
