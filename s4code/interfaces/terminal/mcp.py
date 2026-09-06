"""MCP views and commands over structured Core data."""

from __future__ import annotations

from typing import Any, Optional


class MCPPresenter:
    def __init__(self, controller):
        self.controller = controller

    def _resolve_mcp_server_name(self, server_name: str) -> str:
        names = [
            item["name"] for item in self.controller.core.inspector.read("mcp_status")
        ]
        for name in names:
            if name.lower() == server_name.strip().lower():
                return name
        raise ValueError(
            f"Unknown MCP server: {server_name}. Available: {', '.join(names)}"
        )

    @staticmethod
    def _mcp_transport_summary(state: dict[str, Any]) -> str:
        transport = state.get("transport")
        if isinstance(transport, dict):
            parts = []
            transport_type = str(
                transport.get("transport_type") or transport.get("transportType") or ""
            ).strip()
            if transport_type:
                parts.append(transport_type)
            command = str(transport.get("command") or "").strip()
            if command:
                parts.append(command)
            url = str(transport.get("url") or transport.get("endpoint") or "").strip()
            if url:
                parts.append(url)
            if parts:
                return " | ".join(parts)
        return "-"

    def get_mcp_status_payload(
        self,
        *,
        refresh: bool = False,
        include_capabilities: bool = True,
    ) -> list[dict[str, Any]]:
        if refresh:
            self.controller.core.mcp_action("refresh")
        topic = "mcp" if include_capabilities else "mcp_status"
        payloads = []
        for item in self.controller.core.inspector.read(topic):
            state = item["connection"] or {}
            snapshot = item["capabilities"] or {}
            tool_names = [
                tool["name"] for tool in snapshot.get("tools", []) if tool.get("name")
            ]
            resource_names = [
                resource.get("uri") or resource.get("name")
                for resource in snapshot.get("resources", [])
            ]
            prompt_names = [
                prompt["name"]
                for prompt in snapshot.get("prompts", [])
                if prompt.get("name")
            ]
            status = state.get("status") or (
                "disabled"
                if not item["enabled"]
                else "unregistered"
                if not item["registered"]
                else "unknown"
            )
            payloads.append(
                {
                    "server_name": item["name"],
                    "registry_server_name": item["name"],
                    "source_identifier": item["source_identifier"],
                    "status": status,
                    "enabled": item["enabled"],
                    "persist_connection": item["persist_connection"],
                    "include_resources": item["include_resources"],
                    "retry_count": state.get("retryCount", 0),
                    "last_operation": state.get("lastOperation", ""),
                    "last_error": state.get("lastError") or item["error"] or "",
                    "last_error_type": state.get("lastErrorType", ""),
                    "last_connected_at": state.get("lastConnectedAt"),
                    "last_disconnected_at": state.get("lastDisconnectedAt"),
                    "transport": state.get("transport") or {},
                    "transport_summary": self._mcp_transport_summary(state),
                    "tool_names": tool_names,
                    "resource_names": resource_names,
                    "prompt_names": prompt_names,
                    "tool_count": len(tool_names),
                    "resource_count": len(resource_names),
                    "prompt_count": len(prompt_names),
                }
            )
        return payloads

    def get_mcp_summary_payload(self) -> dict[str, Any]:
        if not bool(self.controller.settings.product.enable_mcp):
            return {
                "enabled": False,
                "configured": 0,
                "connected": 0,
                "disabled": 0,
                "unavailable": 0,
                "issues": [],
            }
        payload = self.get_mcp_status_payload(include_capabilities=False)
        connected = 0
        disabled = 0
        unavailable = 0
        issues: list[dict[str, str]] = []
        for item in payload:
            status = str(item.get("status") or "unknown").strip() or "unknown"
            if status == "connected":
                connected += 1
                continue
            if status == "disabled":
                disabled += 1
                continue
            unavailable += 1
            issues.append(
                {
                    "server_name": str(item.get("server_name") or "").strip(),
                    "status": status,
                    "last_error": str(item.get("last_error") or "").strip(),
                }
            )
        return {
            "enabled": True,
            "configured": len(payload),
            "connected": connected,
            "disabled": disabled,
            "unavailable": unavailable,
            "issues": issues,
        }

    def _action(self, action: str, server_name: Optional[str]) -> str:
        if not self.controller.settings.product.enable_mcp:
            return "MCP is disabled."
        name = self._resolve_mcp_server_name(server_name) if server_name else None
        result = self.controller.core.mcp_action(action, name)
        self.controller._invalidate_runtime_cache()
        return (
            "\n".join(
                f"{item['name']} | {item['status']}"
                + (f" | {item['error']}" if item.get("error") else "")
                for item in result
            )
            or "No MCP servers configured."
        )

    def connect_mcp(self, server_name: Optional[str] = None) -> str:
        return self._action("connect", server_name)

    def disconnect_mcp(self, server_name: Optional[str] = None) -> str:
        return self._action("disconnect", server_name)

    def refresh_mcp(self, server_name: Optional[str] = None) -> str:
        return self._action("refresh", server_name)

    def _detail(self, server_name: str, *, refresh: bool = False) -> dict[str, Any]:
        name = self._resolve_mcp_server_name(server_name)
        if refresh:
            self.controller.core.mcp_action("refresh", name)
        return next(
            item
            for item in self.get_mcp_status_payload()
            if item["server_name"] == name
        )

    def format_mcp_server_detail(
        self, server_name: str, *, refresh: bool = False
    ) -> str:
        item = self._detail(server_name, refresh=refresh)
        lines = [
            f"Server: {item['server_name']}",
            f"Source: {item['source_identifier'] or '-'}",
            f"Enabled: {item['enabled']}",
            f"Status: {item['status']}",
            f"Persist Connection: {item['persist_connection']}",
            f"Transport: {item['transport_summary']}",
            f"Last Operation: {item['last_operation'] or '-'}",
            f"Last Error: {item['last_error'] or '-'}",
            f"Tools: {item['tool_count']} | Resources: {item['resource_count']} | Prompts: {item['prompt_count']}",
        ]
        for label, key in (
            ("Tools", "tool_names"),
            ("Resources", "resource_names"),
            ("Prompts", "prompt_names"),
        ):
            if item[key]:
                lines.extend(
                    ["", label + ":", *[f"- {value}" for value in item[key][:20]]]
                )
        return "\n".join(lines)

    def _format_capabilities(self, server_name: str, kind: str) -> str:
        item = self._detail(server_name)
        if item["status"] in {"disabled", "unregistered"}:
            return f"MCP server '{item['server_name']}' is configured but {item['status']}."
        return (
            "\n".join(item[kind + "_names"])
            or f"No MCP {kind}s found for {item['server_name']}."
        )

    def format_mcp_tools(self, server_name: str) -> str:
        return self._format_capabilities(server_name, "tool")

    def format_mcp_resources(self, server_name: str) -> str:
        return self._format_capabilities(server_name, "resource")

    def format_mcp(self) -> str:
        payload = self.get_mcp_status_payload()
        if not payload:
            return "No MCP servers configured."
        lines: list[str] = []
        for item in payload:
            line = (
                f"{item.get('server_name')} | {item.get('status')} | "
                f"tools={item.get('tool_count', 0)} "
                f"resources={item.get('resource_count', 0)} "
                f"prompts={item.get('prompt_count', 0)} | "
                f"persist={item.get('persist_connection')} | "
                f"{item.get('transport_summary') or '-'}"
            )
            last_error = str(item.get("last_error") or "").strip()
            if last_error:
                line += f" | error={last_error}"
            lines.append(line)
        lines.append("")
        lines.append(
            "Usage: /mcp [list|status <server>|tools <server>|resources <server>|refresh [server]|connect [server]|disconnect [server]]"
        )
        return "\n".join(lines)
