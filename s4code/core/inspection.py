"""Read-only product inspection; presentation belongs to clients."""

from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from datetime import datetime

from .errors import InvalidRequestError, product_operation


def serialize(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (Path, datetime)):
        return str(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return serialize(asdict(value))
    if isinstance(value, dict):
        return {str(k): serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    raise TypeError(f"Not product data: {type(value).__name__}")


class SessionInspector:
    def __init__(self, session):
        self._session = session

    def read(self, topic, *, target=None, limit=30):
        self._session._ensure_open()
        if not isinstance(limit, int) or limit <= 0:
            raise InvalidRequestError("limit must be positive")
        with product_operation():
            return serialize(self._read(topic, target, limit))

    def _read(self, topic, target, limit):
        agent = self._session._agent
        if topic == "state":
            return self._session.state()
        if topic == "history":
            return [
                {"role": message.role, "text": message.text_content()}
                for message in agent.get_canonical_history()
            ]
        if topic == "tools":
            return agent.tool_registry.get_tool_names()
        if topic == "tool_specs":
            fields = (
                "name",
                "description",
                "visibility_scope",
                "expose_in_deferred",
                "read_only",
                "requires_confirmation",
                "destructive",
                "side_effect_level",
            )
            return [
                {field: getattr(spec, field) for field in fields}
                for spec in agent.tool_registry.list_tool_specs()
            ]
        if topic == "mode":
            return agent.get_execution_mode().value
        if topic == "models":
            return [
                {
                    "name": name,
                    "model": profile.model,
                    "provider": profile.provider,
                    "active": name == agent.settings.active_model_profile,
                }
                for name, profile in agent.settings.model_profiles.items()
            ]
        if topic == "configuration":
            return self._public_configuration(agent.settings.model_dump(mode="json"))
        if topic == "permissions":
            return {
                "mode": agent.permission_context.mode.value,
                "rules": agent.permissions.rules(),
                "history": agent.settings.product.permission_history,
            }
        if topic == "context":
            return self._session.context_usage()
        if topic == "trace":
            return agent.get_trace_history()[-limit:]
        if topic in {"metrics", "cost"}:
            return [
                {
                    "invoke_id": record.invoke_id,
                    "query": record.query,
                    "stats": record.stats.model_dump(mode="json"),
                    "llm_invokes": [
                        {
                            "invoke_id": item.invoke_id,
                            "stats": item.stats.model_dump(mode="json"),
                        }
                        for item in record.llm_invokes
                    ],
                }
                for record in agent.observability.list()[-limit:]
            ]
        if topic == "restore":
            return agent.get_last_restore_report() or {}
        if topic == "skills":
            manager = agent.skill_manager
            if manager is None:
                return []
            return [
                {
                    "name": manifest.name,
                    "description": manifest.description,
                    "when_to_use": manifest.when_to_use,
                    "context": manifest.context,
                    "file_path": manifest.file_path,
                    "allowed_tools": list(manifest.allowed_tools),
                    "visible": manager.is_visible(manifest.name),
                }
                for manifest in (
                    manager.get_skill(name) for name in manager.skill_names
                )
            ]
        if topic == "skill_sources":
            return list(agent.skill_sources)
        if topic == "tasks":
            return agent.task_service.list_tasks(limit=limit)
        if topic == "task":
            return agent.task_service.get_task(target)
        if topic == "processes":
            manager = agent.runtime.processes
            return manager.list_tasks()[:limit] if manager else []
        if topic == "process":
            manager = agent.runtime.processes
            if manager is None:
                raise InvalidRequestError("Background processes are unavailable")
            return manager.get_task(target)
        if topic == "agents":
            runtime = agent.agent_runtime
            return (
                [
                    {
                        "agent_id": item.agent_id,
                        "status": item.status,
                        "name": item.name,
                        "output_file": item.output_file,
                        "task_id": item.execution_context.current_task_id,
                        "description": item.description,
                    }
                    for item in runtime.list_handles(limit=limit)
                ]
                if runtime
                else []
            )
        if topic == "agent":
            if agent.agent_runtime is None:
                raise InvalidRequestError("Agent runtime is unavailable")
            return agent.agent_runtime.get_handle(target).to_dict()
        if topic == "worktree":
            manager = agent.runtime.worktrees
            if manager is None:
                return {"enabled": False, "active": None, "managed": []}
            active = manager.get_active_session()
            return {
                "enabled": True,
                "active": {
                    "path": str(active.worktree.path),
                    "branch": active.worktree.branch,
                    "original_cwd": active.original_cwd,
                    "created_at": active.created_at,
                }
                if active
                else None,
                "managed": [
                    {"path": str(w.path), "branch": w.branch, "head": w.head}
                    for w in manager.list_managed_worktrees()
                ],
            }
        if topic in {"mcp", "mcp_status"}:
            managers = agent.tool_registry.list_runtime_surfaces("mcp_manager")
            configs = {config.name: config for config in agent.settings.mcp_servers}
            items = []
            for name in dict.fromkeys([*configs, *managers]):
                if target and name != target:
                    continue
                config, manager = configs.get(name), managers.get(name)
                capabilities, error = None, None
                if manager and topic == "mcp":
                    try:
                        capabilities = serialize(manager.snapshot(refresh=False))
                    except Exception as exc:
                        error = str(exc)
                items.append(
                    {
                        "name": name,
                        "enabled": config.enabled if config else True,
                        "registered": manager is not None,
                        "source_identifier": manager.source_identifier
                        if manager
                        else getattr(config, "server_source", ""),
                        "persist_connection": manager.connection_manager.persist_connection
                        if manager
                        else bool(config and config.persist_connection),
                        "include_resources": manager.include_resources
                        if manager
                        else bool(config and config.include_resources),
                        "connection": self._public_configuration(
                            manager.connection_state()
                        )
                        if manager
                        else None,
                        "capabilities": capabilities,
                        "error": error,
                    }
                )
            if target and not items:
                raise InvalidRequestError(f"Unknown MCP server: {target}")
            return items
        if topic == "hooks":
            return [hook.name for hook in agent.hook_manager.hooks]
        if topic == "files":
            return agent.project.list_files(target or ".", limit=limit)
        if topic == "diff":
            return agent.project.get_diff(target=target)
        if topic == "diagnostics":
            return self._session.diagnostics()
        raise InvalidRequestError(f"Unknown inspection topic: {topic}")

    @staticmethod
    def _public_configuration(value):
        if isinstance(value, dict):
            return {
                key: (
                    "[redacted]"
                    if key.lower()
                    in {
                        "api_key",
                        "token",
                        "access_token",
                        "refresh_token",
                        "secret",
                        "password",
                        "default_headers",
                        "headers",
                        "env",
                        "auth",
                    }
                    else SessionInspector._public_configuration(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [SessionInspector._public_configuration(item) for item in value]
        if isinstance(value, str) and "://" in value:
            from urllib.parse import urlsplit, urlunsplit

            parts = urlsplit(value)
            if not parts.netloc:
                return value
            # Remove credentials and query parameters, but preserve ports/IPv6.
            authority = parts.netloc.rsplit("@", 1)[-1]
            return urlunsplit((parts.scheme, authority, parts.path, "", ""))
        return value
