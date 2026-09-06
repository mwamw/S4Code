"""Product interaction decisions, usable without a terminal."""

from __future__ import annotations
from easyagent.permissions import PermissionRule


class S4Interactions:
    def __init__(self, agent):
        self.agent = agent

    def pending(self):
        return self.agent.get_pending_interruption()

    def respond(self, *, action: str, answer: str = "", remember: bool = False):
        if action not in {"approve", "deny", "answer"}:
            raise ValueError("Action must be approve, deny, or answer")
        agent = self.agent
        with agent.operation():
            payload = self.pending()
            if payload is None:
                raise ValueError("No pending interaction")
            tool = str(payload.get("tool_name") or "")
            arguments = dict(payload.get("tool_args") or {})
            metadata = dict(payload.get("metadata") or {})
            kind = metadata.get("interaction_type")
            if action == "answer" and kind != "ask_user_question":
                raise ValueError("This interaction requires approve or deny")
            ephemeral = None
            if action == "deny":
                content = f"User declined {tool}: {answer or 'No reason provided.'}"
            elif kind == "ask_user_question":
                if not answer.strip():
                    raise ValueError("A non-empty answer is required")
                content = f"User answered: {answer.strip()}"
            elif kind == "enter_plan_mode":
                agent.enter_plan_mode(
                    allowed_actions=list(metadata.get("allowedActions") or [])
                )
                content = "User approved entering plan mode."
            elif kind == "exit_plan_mode":
                agent.exit_plan_mode(
                    permission_mode=agent.settings.product.permission_mode
                )
                content = "User approved exiting plan mode."
            else:
                if action != "approve":
                    raise ValueError("Tool execution requires approve or deny")
                result = agent.tool_registry.execute_confirmed_tool_result(
                    tool,
                    arguments,
                    permission_context=agent.permission_context,
                    permission_engine=agent.permission_engine,
                )
                content, ephemeral = (
                    result.to_display_string(),
                    result.ephemeral_context,
                )
            if remember and kind not in {
                "ask_user_question",
                "enter_plan_mode",
                "exit_plan_mode",
            }:
                agent.add_permission_rule(
                    PermissionRule(
                        tool_name=tool,
                        behavior="allow" if action == "approve" else "deny",
                        matcher={"param_equals": arguments},
                        source="session",
                    ),
                    source="session",
                )
            result = agent.resolve_pending_interruption(
                content=content, ephemeral_context=ephemeral
            )
            agent.permissions.synchronize()
            if agent.session is not None:
                agent.session.dirty = True
                agent.session._autosave()
            return result
