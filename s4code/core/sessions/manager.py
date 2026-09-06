"""S4Code session persistence and branching; no UI state policy."""

from __future__ import annotations
from copy import deepcopy
from pathlib import Path
from .catalog import SessionCatalog


class S4SessionManager:
    def __init__(self, agent, paths, *, store=None):
        self.catalog = SessionCatalog(paths, store=store)
        self.store = self.catalog.store
        self.agent = agent
        self.session_id = self.catalog.new_session_id(agent.project)
        self.title = f"{agent.project.project_name} session"
        self.forked_from_session_id = None
        self.overrides: dict = {}
        self.extensions: dict = {}
        self.dirty = False

    def metadata(self):
        data = self.catalog.build_metadata(
            project=self.agent.project,
            title=self.title,
            settings_payload=self.agent.settings.model_dump(),
            session_overrides=self.overrides,
            forked_from_session_id=self.forked_from_session_id,
        )
        data["extensions"] = deepcopy(self.extensions)
        return data

    def save(self, *, title=None):
        with self.agent.operation():
            return self._save(title=title)

    def _save(self, *, title=None):
        if title is not None:
            if not title.strip():
                raise ValueError("Session title must be non-empty")
            self.title = title.strip()
        self.agent.save_session(
            self.session_id, store=self.store, metadata=self.metadata()
        )
        self.dirty = False
        return self.store.get_session(self.session_id, touch=False)

    def autosave(self):
        with self.agent.operation():
            self._autosave()

    def _autosave(self):
        """Best-effort persistence while the owning Agent operation is held."""
        if not self.dirty or not self.agent.settings.product.session_auto_save:
            return
        try:
            self._save()
        except Exception as exc:
            message = f"Session persistence unavailable: {type(exc).__name__}: {exc}"
            if message not in self.agent.startup_issues:
                self.agent.startup_issues.append(message)

    def restore(self, session_id):
        with self.agent.operation():
            record = self.store.get_session(session_id, touch=False)
            if record is None:
                raise ValueError(f"Session not found: {session_id}")
            metadata = dict(record.get("metadata") or {})
            root = metadata.get("project_root")
            if not root or metadata.get("product") != "s4code":
                raise ValueError("Session is not associated with an S4Code project")
            if (
                root
                and Path(root).resolve() != self.agent.project.project_root.resolve()
            ):
                raise ValueError("Cannot resume a session belonging to another project")
            self.agent.restore_session(session_id, store=self.store)
            self.agent._apply_reasoning()
            self.session_id = session_id
            self.title = metadata.get("title") or session_id
            self.forked_from_session_id = metadata.get("forked_from_session_id")
            self.overrides = deepcopy(metadata.get("session_overrides") or {})
            self.extensions = deepcopy(metadata.get("extensions") or {})
            self.agent.settings.product.permission_history = list(
                self.overrides.get("product", {}).get("permission_history", [])
            )
            self.agent.permissions.synchronize()
            self.dirty = False
            return self.agent.get_last_restore_report()

    def fork(self, *, title=None):
        with self.agent.operation():
            if self.agent.get_pending_interruption() is not None:
                raise RuntimeError(
                    "Resolve the pending interaction before forking a session"
                )
            self._save()
            metadata = deepcopy(self.metadata())
            metadata["title"] = title or f"{self.title} (fork)"
            metadata["forked_from_session_id"] = self.session_id
            metadata["extensions"] = {}
            metadata["session_overrides"].pop("_s4code", None)
            session_id = self.catalog.new_session_id(self.agent.project)
            self.agent.fork_session(session_id, store=self.store, metadata=metadata)
            return self.store.get_session(session_id, touch=False)

    def rename(self, title):
        with self.agent.operation():
            return self._save(title=title)
