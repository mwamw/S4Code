"""An open product session; the Agent remains an internal component."""

from copy import deepcopy
from contextlib import contextmanager
from uuid import uuid4

from ..contracts import ConversationSnapshot, InteractionRequest, SessionInfo
from ..errors import BusyError, ClosedError, InvalidRequestError, product_operation
from ..runs import RunService
from ..inspection import SessionInspector
from .snapshots import ConversationSnapshotStore


class CoreSession:
    def __init__(self, agent):
        self._agent = agent
        self._closed = False
        self._pending_key = None
        self._pending_id = None
        self._context_cache = None
        self.runs = RunService(self)
        self.inspector = SessionInspector(self)
        self.snapshots = ConversationSnapshotStore(agent.paths.data_dir / "conversation-snapshots.db")

    @property
    def id(self):
        return self._agent.session.session_id

    def _ensure_open(self):
        if self._closed or self._agent._closed:
            raise ClosedError("Session is closed")

    @contextmanager
    def _operation(self):
        self._ensure_open()
        if self.runs.active_run_id or self._agent.busy:
            raise BusyError("Session already has an active operation")
        with product_operation():
            try:
                yield
            finally:
                self.invalidate_context()

    def invalidate_context(self):
        self._context_cache = None

    def context_usage(self):
        self._ensure_open()
        if self._context_cache is None:
            self._context_cache = {
                **self._agent.get_context_usage(),
                "maxTokens": self._agent.context_manager.budget.max_tokens
                if self._agent.context_manager else None,
            }
        return deepcopy(self._context_cache)

    def info(self):
        self._ensure_open()
        agent = self._agent
        return SessionInfo(
            session_id=self.id,
            title=agent.session.title,
            project_root=str(agent.project.project_root),
            model=agent.llm.model,
            provider=agent.llm.provider_name,
            forked_from_session_id=agent.session.forked_from_session_id,
        )

    def configuration(self):
        self._ensure_open()
        return self._agent.settings.model_copy(deep=True)

    def session_overrides(self):
        self._ensure_open()
        return deepcopy(self._agent.session.overrides)

    def update_metadata(self, *, title=None, overrides=None, autosave=None):
        with self._operation():
            with self._agent.operation():
                if title is not None:
                    if not isinstance(title, str) or not title.strip():
                        raise InvalidRequestError("Session title must be non-empty")
                    self._agent.session.title = title.strip()
                if overrides is not None:
                    if not isinstance(overrides, dict):
                        raise InvalidRequestError("Session overrides must be an object")
                    self._agent.session.overrides = deepcopy(overrides)
                if autosave is not None:
                    self._agent.settings.product.session_auto_save = bool(autosave)
                self._agent.session.dirty = True

    def autosave(self):
        with self._operation():
            self._agent.session.autosave()
            return {"dirty": self._agent.session.dirty}

    def close_report(self):
        return deepcopy(self._agent.get_last_close_report() or {})

    def state(self):
        self._ensure_open()
        agent = self._agent
        pending = self.pending()
        return {
            **self.info().model_dump(),
            "busy": agent.busy or self.runs.active_run_id is not None,
            "run_id": self.runs.active_run_id,
            "context": self.context_usage(),
            "pending": pending.model_dump() if pending else None,
            "project_name": agent.project.project_name,
            "branch": agent.project.branch,
            "permission_mode": agent.settings.product.permission_mode,
            "profile": agent.settings.active_model_profile,
            "permission_rules": len(agent.permissions.rules()),
            "skills": {"active": list(agent.skill_manager.active_skill_names) if agent.skill_manager else []},
            "mcp": {
                "enabled": agent.settings.product.enable_mcp,
                "servers": self.inspector.read("mcp_status"),
            },
            "deferred_tools": self._tool_counts(),
            "processes": self._process_states(),
            "startup_issues": list(agent.startup_issues),
        }

    def _tool_counts(self):
        registry = self._agent.tool_registry
        specs = registry.list_tool_specs()
        deferred = {spec.name for spec in specs if spec.expose_in_deferred}
        loaded = deferred.intersection(registry.get_deferred_expanded_tool_names())
        return {"total": len(specs), "loaded": len(loaded),
                "pending_schema": len(deferred - loaded), "immediate": len(specs) - len(deferred)}

    def _process_states(self):
        manager = self._agent.runtime.processes
        return [{"task_id": item.task_id, "status": item.status, "return_code": item.return_code}
                for item in manager.list_tasks(include_output=False)] if manager else []

    def pending(self):
        self._ensure_open()
        raw = self._agent.interactions.pending()
        if raw is None:
            self._pending_key = self._pending_id = None
            return None
        if raw != self._pending_key:
            self._pending_key, self._pending_id = deepcopy(raw), uuid4().hex
        details = deepcopy(raw.get("metadata") or {})
        return InteractionRequest(
            interaction_id=self._pending_id,
            session_id=self.id,
            kind=details.get("interaction_type") or "tool_approval",
            tool_name=raw.get("tool_name") or "",
            arguments=deepcopy(raw.get("tool_args") or {}),
            details=details,
        )

    def respond(self, interaction_id, *, action, answer="", remember=False):
        with self._operation():
            pending = self.pending()
            if pending is None or pending.interaction_id != interaction_id:
                raise InvalidRequestError("Interaction is missing or stale")
            result = self._agent.interactions.respond(
                action=action, answer=answer, remember=remember
            )
            self._pending_key = self._pending_id = None
            return deepcopy(result)

    def run(self, prompt, options=None):
        return self.runs.run(prompt, options)

    async def arun(self, prompt, options=None):
        return await self.runs.arun(prompt, options)

    def stream(self, prompt, options=None):
        return self.runs.stream(prompt, options)

    def save(self, title=None):
        with self._operation():
            self._agent.session.save(title=title)
            return self.info()

    def fork(self, title=None):
        with self._operation():
            record = self._agent.session.fork(title=title)
            metadata = record["metadata"]
            return SessionInfo(
                session_id=record["session_id"],
                title=metadata["title"],
                project_root=metadata["project_root"],
                model=metadata.get("model"),
                provider=metadata.get("provider"),
                forked_from_session_id=self.id,
            )

    def export_conversation(self):
        with self._operation():
            return ConversationSnapshot(
                session_id=self.id, state=self._agent.export_conversation()
            )

    def restore_conversation(self, snapshot):
        with self._operation():
            snapshot = ConversationSnapshot.model_validate(snapshot)
            if snapshot.session_id != self.id:
                raise InvalidRequestError("Snapshot belongs to another session")
            self._agent.restore_conversation(deepcopy(snapshot.state))
            self._pending_key = self._pending_id = None

    def capture_conversation(self, source=None):
        with self._operation():
            if source is None:
                snapshot = self.export_conversation()
            else:
                # Generic JSON-path import avoids round-tripping large legacy extension values.
                value = self._agent.session.extensions.get(source["namespace"], {})
                try:
                    for key in source["path"]:
                        value = value[key]
                except (KeyError, IndexError, TypeError) as exc:
                    raise InvalidRequestError("Extension snapshot source not found") from exc
                if source["format"] == "history":
                    value = {"history": {"canonical": value}}
                if source["format"] != "snapshot":
                    value = {"session_id": self.id, "state": value}
                snapshot = ConversationSnapshot.model_validate(value)
            if snapshot.session_id != self.id:
                raise InvalidRequestError("Snapshot belongs to another session")
            return self.snapshots.put(snapshot)

    def restore_snapshot(self, snapshot_id):
        with self._operation():
            self.restore_conversation(self.snapshots.get(self.id, snapshot_id))

    def delete_snapshots(self, snapshot_ids):
        with self._operation():
            self.snapshots.delete(self.id, snapshot_ids)

    def read_extension(self, namespace, *, exclude_fields=()):
        self._ensure_open()
        def project(value):
            if isinstance(value, dict):
                return {key: None if key in exclude_fields else project(item) for key, item in value.items()}
            if isinstance(value, list):
                return [project(item) for item in value]
            return deepcopy(value)
        return project(self._agent.session.extensions.get(namespace, {}))

    def write_extension(self, namespace, value):
        with self._operation():
            if (
                not isinstance(namespace, str)
                or not namespace.strip()
                or not isinstance(value, dict)
            ):
                raise InvalidRequestError(
                    "Extension requires a namespace and an object"
                )
            import json

            json.dumps(value, allow_nan=False)
            with self._agent.operation():
                self._agent.session.extensions[namespace] = deepcopy(value)
                self._agent.session.dirty = True
                self._agent.session._autosave()
                return {"saved": True, "persisted": not self._agent.session.dirty}

    def select_model(self, target):
        with self._operation():
            return self._agent.select_model(target)

    def compact(self, max_tokens=None):
        with self._operation():
            return self._agent.compact_history(max_tokens)

    def clear_history(self):
        with self._operation():
            self._agent.clear_history()

    def mcp_action(self, action, server_name=None):
        with self._operation():
            return self._agent.runtime.mcp_action(action, server_name)

    def set_permission_mode(self, mode):
        with self._operation():
            self._agent.permissions.set_mode(mode)

    def add_permission_rule(self, rule):
        from easyagent.permissions import PermissionRule

        with self._operation():
            self._agent.permissions.add_rule(PermissionRule.model_validate(rule))

    def clear_permission_rules(self, source="session"):
        with self._operation():
            self._agent.permissions.clear_rules(source=source)

    def activate_skill(self, name):
        with self._operation():
            manager = self._agent.skill_manager
            if manager is None or not manager.has_skill(name):
                raise InvalidRequestError(f"Unknown skill: {name}")
            with self._agent.operation():
                return manager.invoke(name, model_initiated=False)

    def runtime_action(self, action, arguments):
        tools = {
            "task.stop": "TaskStop",
            "task.output": "TaskOutput",
            "worktree.enter": "EnterWorktree",
            "worktree.exit": "ExitWorktree",
            "agent.stop": "AgentStop",
            "agent.wait": "AgentWait",
        }
        with self._operation():
            if action not in tools:
                raise InvalidRequestError(f"Unknown runtime action: {action}")
            result = self._agent.runtime.execute(
                tools[action], arguments, confirmed=False
            )
            return {"text": result.to_display_string(), "data": result.structured_data}

    def set_plan_mode(self, enabled):
        with self._operation():
            with self._agent.operation():
                if enabled:
                    self._agent.enter_plan_mode()
                else:
                    self._agent.exit_plan_mode(
                        permission_mode=self._agent.settings.product.permission_mode
                    )
                self._agent.session.dirty = True
                self._agent.session._autosave()

    def diagnostics(self):
        self._ensure_open()
        return {
            "project": str(self._agent.project.project_root),
            "model": self._agent.llm.model,
            "startupIssues": list(self._agent.startup_issues),
            "tools": self._agent.tool_registry.get_tool_names(),
        }

    def close(self):
        if self._agent._closed:
            self._closed = True
        if not self._closed:
            with self._operation():
                self._agent.close()
                self._closed = True

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, *args):
        self.close()
