"""Product operations over the installed EasyAgent runtime."""

from __future__ import annotations


class S4RuntimeOperations:
    def __init__(self, agent):
        self.agent = agent

    @property
    def processes(self):
        for name in ("Bash", "TaskOutput", "TaskStop"):
            tool = self.agent.tool_registry.get_tool(name)
            manager = getattr(tool, "process_manager", None)
            if manager is not None:
                return manager
        return None

    @property
    def worktrees(self):
        return self.agent.worktree_manager

    def execute(self, tool_name, arguments=None, *, confirmed=False):
        with self.agent.operation():
            registry = self.agent.tool_registry
            execute = (
                registry.execute_confirmed_tool_result
                if confirmed
                else registry.execute_tool_result
            )
            result = execute(
                tool_name,
                arguments or {},
                permission_context=self.agent.permission_context,
                permission_engine=self.agent.permission_engine,
            )
            if self.agent.session is not None:
                self.agent.session.dirty = True
                self.agent.session._autosave()
            return result

    def mcp_action(self, action, server_name=None):
        if action not in {"connect", "disconnect", "refresh"}:
            raise ValueError("Unknown MCP action")
        with self.agent.operation():
            managers = self.agent.tool_registry.list_runtime_surfaces("mcp_manager")
            configured = {
                server.name: server for server in self.agent.settings.mcp_servers
            }
            names = (
                [server_name]
                if server_name
                else sorted(set(configured) | set(managers))
            )
            if (
                server_name
                and server_name not in configured
                and server_name not in managers
            ):
                raise ValueError(f"Unknown MCP server: {server_name}")
            result = []
            for name in names:
                manager = managers.get(name)
                if manager is None:
                    status = (
                        "disabled"
                        if name in configured and not configured[name].enabled
                        else "unregistered"
                    )
                    result.append({"name": name, "status": status})
                    continue
                try:
                    if action == "disconnect":
                        manager.close()
                    else:
                        manager.connect()
                        if action == "refresh":
                            manager.snapshot(refresh=True)
                    result.append(
                        {
                            "name": name,
                            "status": {
                                "connect": "connected",
                                "disconnect": "disconnected",
                                "refresh": "refreshed",
                            }[action],
                        }
                    )
                except Exception as exc:
                    result.append({"name": name, "status": "error", "error": str(exc)})
            return result
