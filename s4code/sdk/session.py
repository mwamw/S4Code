"""External session handles. No framework objects are part of the public API."""

from __future__ import annotations

from contextlib import aclosing
from typing import Any, AsyncIterator, Literal, TYPE_CHECKING

from s4code.core.contracts import (
    InteractionRequest,
    RunEvent,
    RunOptions,
    RunResult,
    SessionInfo,
)
from s4code.core.sessions.session import CoreSession

if TYPE_CHECKING:
    from .client import AsyncSessions, Sessions


class Session:
    def __init__(self, core_session: CoreSession, owner: Sessions):
        self._session = core_session
        self._owner = owner

    @property
    def id(self) -> str:
        return self._session.id

    def info(self) -> SessionInfo:
        return self._session.info()

    def run(
        self, prompt: str, *, options: RunOptions | dict[str, Any] | None = None
    ) -> RunResult:
        return self._session.run(prompt, options)

    def save(self, *, title: str | None = None) -> SessionInfo:
        return self._session.save(title)

    def fork(self, *, title: str | None = None) -> Session:
        info = self._session.fork(title)
        return self._owner.resume(info.session_id)

    def pending(self) -> InteractionRequest | None:
        return self._session.pending()

    def respond(
        self,
        interaction_id: str,
        *,
        action: Literal["approve", "deny", "answer"],
        answer: str = "",
        remember: bool = False,
    ) -> dict[str, Any]:
        return self._session.respond(
            interaction_id, action=action, answer=answer, remember=remember
        )

    def cancel(self, reason: str = "") -> bool:
        return self._session.runs.cancel(reason)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> Session:
        self._session._ensure_open()
        return self

    def __exit__(self, *args) -> None:
        self.close()


class AsyncSession:
    def __init__(self, core_session: CoreSession, owner: AsyncSessions):
        self._session = core_session
        self._owner = owner

    @property
    def id(self) -> str:
        return self._session.id

    async def info(self) -> SessionInfo:
        return self._session.info()

    async def run(
        self, prompt: str, *, options: RunOptions | dict[str, Any] | None = None
    ) -> RunResult:
        return await self._session.arun(prompt, options)

    async def stream(
        self, prompt: str, *, options: RunOptions | dict[str, Any] | None = None
    ) -> AsyncIterator[RunEvent]:
        async with aclosing(self._session.stream(prompt, options)) as events:
            async for event in events:
                yield event

    async def save(self, *, title: str | None = None) -> SessionInfo:
        return self._session.save(title)

    async def fork(self, *, title: str | None = None) -> AsyncSession:
        info = self._session.fork(title)
        return await self._owner.resume(info.session_id)

    async def pending(self) -> InteractionRequest | None:
        return self._session.pending()

    async def respond(
        self,
        interaction_id: str,
        *,
        action: Literal["approve", "deny", "answer"],
        answer: str = "",
        remember: bool = False,
    ) -> dict[str, Any]:
        return self._session.respond(
            interaction_id, action=action, answer=answer, remember=remember
        )

    async def cancel(self, reason: str = "") -> bool:
        return self._session.runs.cancel(reason)

    async def close(self) -> None:
        self._session.close()

    async def __aenter__(self) -> AsyncSession:
        self._session._ensure_open()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()
