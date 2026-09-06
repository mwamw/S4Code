"""In-process Python SDK. CLI and TUI do not depend on this module."""

from __future__ import annotations

from pathlib import Path
from s4code.core.application import S4CodeRuntime
from s4code.core.contracts import SessionInfo
from s4code.core.settings import S4AgentSettings
from .session import AsyncSession, Session


class Sessions:
    def __init__(self, runtime: S4CodeRuntime) -> None:
        self._runtime = runtime

    def create(self) -> Session:
        return Session(self._runtime.open_session(), self)

    def resume(self, session_id: str) -> Session:
        return Session(self._runtime.open_session(session_id), self)

    def list(self, *, limit: int = 30) -> list[SessionInfo]:
        return self._runtime.list_sessions(limit)


class AsyncSessions:
    def __init__(self, runtime: S4CodeRuntime) -> None:
        self._runtime = runtime

    async def create(self) -> AsyncSession:
        return AsyncSession(self._runtime.open_session(), self)

    async def resume(self, session_id: str) -> AsyncSession:
        return AsyncSession(self._runtime.open_session(session_id), self)

    async def list(self, *, limit: int = 30) -> list[SessionInfo]:
        return self._runtime.list_sessions(limit)


class S4Code:
    def __init__(
        self, *, cwd: str | Path | None = None, settings: S4AgentSettings | None = None
    ) -> None:
        self._runtime = S4CodeRuntime(cwd=cwd, settings=settings)
        self.sessions = Sessions(self._runtime)

    def close(self) -> None:
        self._runtime.close()

    def __enter__(self) -> S4Code:
        self._runtime._ensure_open()
        return self

    def __exit__(self, *args) -> None:
        self.close()


class AsyncS4Code:
    def __init__(
        self, *, cwd: str | Path | None = None, settings: S4AgentSettings | None = None
    ) -> None:
        self._runtime = S4CodeRuntime(cwd=cwd, settings=settings)
        self.sessions = AsyncSessions(self._runtime)

    async def close(self) -> None:
        self._runtime.close()

    async def __aenter__(self) -> AsyncS4Code:
        self._runtime._ensure_open()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()
