"""Product application boundary shared by CLI, TUI, SDK and Bridge."""

from copy import deepcopy
from pathlib import Path

from .agent import S4CodeAgent
from .configuration import S4ConfigLoader
from .contracts import SessionInfo
from .errors import (
    BusyError,
    ClosedError,
    InvalidRequestError,
    SessionNotFoundError,
    product_operation,
)
from .paths import get_s4_paths
from .project import ProjectContext
from .sessions.catalog import SessionCatalog
from .sessions.session import CoreSession
from .settings import S4AgentSettings


def merge_settings(base, overrides):
    result = deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_settings(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


class S4CodeRuntime:
    def __init__(self, *, cwd=None, settings=None, paths=None, session_store=None):
        self.paths = paths or get_s4_paths()
        self.project = ProjectContext.detect(cwd)
        self._settings = (
            settings.model_copy(deep=True) if settings is not None else None
        )
        self.catalog = SessionCatalog(self.paths, store=session_store)
        self._sessions: dict[str, CoreSession] = {}
        self._closed = False

    def _ensure_open(self):
        if self._closed:
            raise ClosedError("Runtime is closed")

    def attach_session(self, session):
        """Take ownership of a preconstructed Core session (embedding/testing)."""
        self._ensure_open()
        session._ensure_open()
        if session.info().project_root != str(self.project.project_root):
            raise InvalidRequestError("Session belongs to another project")
        if session.id in self._sessions and self._sessions[session.id] is not session:
            raise InvalidRequestError("Session is already open")
        self._sessions[session.id] = session
        return session

    def replace_session(self, current, session_id, **options):
        """Prepare the replacement first; failed loading must preserve current."""
        self._ensure_open()
        if current.id == session_id:
            return current
        if current.state()["busy"]:
            raise BusyError("Stop the current run before replacing its session")
        existing = self._sessions.get(session_id)
        replacement = self.open_session(session_id, **options)
        try:
            current.close()
        except BaseException:
            if replacement is not existing:
                replacement.close()
            raise
        return replacement

    def open_session(
        self, session_id=None, *, overrides=None, ignore_saved_model=False
    ):
        self._ensure_open()
        if session_id in self._sessions:
            existing = self._sessions[session_id]
            if not existing._closed:
                if overrides or ignore_saved_model:
                    raise InvalidRequestError(
                        "Session is already open; configure it explicitly"
                    )
                return existing
        with product_operation():
            stored = {}
            if session_id:
                record = self.catalog.store.get_session(session_id, touch=False)
                if record is None:
                    raise SessionNotFoundError(f"Session not found: {session_id}")
                metadata = record.get("metadata") or {}
                if metadata.get("product") != "s4code" or not metadata.get(
                    "project_root"
                ):
                    raise InvalidRequestError("Not an S4Code project session")
                if (
                    Path(metadata["project_root"]).resolve()
                    != self.project.project_root.resolve()
                ):
                    raise InvalidRequestError(
                        "Cannot resume a session belonging to another project"
                    )
                stored = deepcopy(metadata.get("session_overrides") or {})
                if ignore_saved_model:
                    stored.pop("llm", None)
                    stored.pop("active_model_profile", None)
                elif (
                    overrides
                    and "active_model_profile" in overrides
                    and "llm" not in overrides
                ):
                    stored.pop("llm", None)
            effective = merge_settings(stored, overrides or {})
            if self._settings is None:
                settings = S4ConfigLoader(self.paths).load_agent_settings(
                    self.project.project_root, overrides=effective
                )
            else:
                configured = merge_settings(self._settings.model_dump(), effective)
                if "active_model_profile" in effective:
                    name = configured["active_model_profile"]
                    profile = configured["model_profiles"].get(name)
                    if profile is None:
                        raise InvalidRequestError(f"Unknown model profile: {name}")
                    configured["llm"] = merge_settings(
                        profile, effective.get("llm") or {}
                    )
                settings = S4AgentSettings.model_validate(configured)
            agent = S4CodeAgent.create(
                workspace=self.project.project_root,
                settings=settings,
                paths=self.paths,
                session_store=self.catalog.store,
            )
            try:
                if session_id:
                    # EasyAgent restores into the configured instance and keeps
                    # its LLM/config. Re-selecting a profile here would discard
                    # explicit literal-model overrides already applied above.
                    agent.session.restore(session_id)
                agent.session.overrides = effective
                session = CoreSession(agent)
                self._sessions[session.id] = session
                return session
            except BaseException:
                agent.close()
                raise

    def list_sessions(self, limit=30):
        self._ensure_open()
        if not isinstance(limit, int) or limit <= 0:
            raise InvalidRequestError("limit must be positive")
        with product_operation():
            return [
                SessionInfo(
                    session_id=item.session_id,
                    title=item.title,
                    project_root=item.project_root,
                    model=item.model,
                    provider=item.provider,
                    forked_from_session_id=item.forked_from_session_id,
                )
                for item in self.catalog.list_sessions(
                    limit=limit, project_root=self.project.project_root
                )
            ]

    def close(self):
        if self._closed:
            return
        if any(
            s.runs.active_run_id or s._agent.busy
            for s in self._sessions.values()
            if not s._closed
        ):
            raise BusyError("Stop active runs before closing the runtime")
        failures = []
        for session in self._sessions.values():
            try:
                session.close()
            except Exception as exc:
                failures.append(exc)
        if failures:
            raise failures[0]
        self._closed = True

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, *args):
        self.close()
