"""PermissionCommands: terminal interaction responsibilities."""

from __future__ import annotations

import json
from typing import Any, Optional


from s4code.core.settings import PermissionRuleSettings


class PermissionCommands:
    def __init__(self, controller):
        self.controller = controller
        self._displayed_interaction: Optional[dict[str, Any]] = None

    def update_permission_mode(self, mode: str) -> str:
        normalized_mode = str(mode or "").strip()
        if not normalized_mode:
            return self.format_permissions()
        self.controller.core.set_permission_mode(normalized_mode)
        self._persist_permission_state()
        return f"Permission mode set to {normalized_mode}"

    def _permission_rules_payload(self) -> list[dict[str, Any]]:
        return self.controller.core.inspector.read("permissions")["rules"]

    def _permission_history(self) -> list[dict[str, Any]]:
        return self.controller.core.inspector.read("permissions")["history"]

    def _persist_permission_state(self) -> None:
        self.controller._sync_from_core()

    @staticmethod
    def _split_csv_values(value: str) -> list[str]:
        result = []
        for item in str(value or "").split(","):
            stripped = item.strip()
            if stripped:
                result.append(stripped)
        return result

    def _build_permission_matcher_from_options(
        self, options: dict[str, str]
    ) -> dict[str, Any]:
        matcher: dict[str, Any] = {}
        if options.get("path"):
            matcher["path_prefixes"] = self._split_csv_values(options["path"])
        if options.get("paths"):
            matcher["path_prefixes"] = self._split_csv_values(options["paths"])
        if options.get("command"):
            matcher["command_prefixes"] = self._split_csv_values(options["command"])
        if options.get("cmd"):
            matcher["command_prefixes"] = self._split_csv_values(options["cmd"])
        if options.get("host"):
            matcher["hosts"] = self._split_csv_values(options["host"])
        if options.get("hosts"):
            matcher["hosts"] = self._split_csv_values(options["hosts"])
        if options.get("mcp"):
            matcher["mcp_servers"] = self._split_csv_values(options["mcp"])
        if options.get("server"):
            matcher["mcp_servers"] = self._split_csv_values(options["server"])
        if options.get("risk"):
            matcher["risk_categories"] = self._split_csv_values(options["risk"])
        if options.get("risks"):
            matcher["risk_categories"] = self._split_csv_values(options["risks"])

        param_equals: dict[str, str] = {}
        param_contains: dict[str, str] = {}
        for key, value in options.items():
            if key.startswith("equals:"):
                param_key = key.split(":", 1)[1].strip()
                if param_key:
                    param_equals[param_key] = value
            elif key.startswith("contains:"):
                param_key = key.split(":", 1)[1].strip()
                if param_key:
                    param_contains[param_key] = value
        if param_equals:
            matcher["param_equals"] = param_equals
        if param_contains:
            matcher["param_contains"] = param_contains
        return matcher

    def add_permission_rule_from_tokens(
        self,
        *,
        behavior: str,
        tool_name: str,
        tokens: list[str],
    ) -> str:
        normalized_tool = str(tool_name or "").strip()
        if not normalized_tool:
            return "Usage: /permissions [allow|deny|ask] <tool|*> [path=...] [host=...] [command=...] [mcp=...] [risk=...] [source=session] [desc=...]"
        normalized_behavior = str(behavior or "").strip()
        options: dict[str, str] = {}
        free_parts: list[str] = []
        for token in list(tokens or []):
            if "=" in token:
                key, value = token.split("=", 1)
                options[key.strip().lower()] = value.strip()
            elif token:
                free_parts.append(str(token))
        source = options.pop("source", "session").strip() or "session"
        description = (
            options.pop("desc", None)
            or options.pop("description", None)
            or " ".join(free_parts).strip()
            or None
        )
        matcher = self._build_permission_matcher_from_options(options)
        rule = PermissionRuleSettings(
            tool_name=normalized_tool,
            behavior=normalized_behavior,
            matcher=matcher,
            source=source,
            description=description,
        )
        self.controller.core.add_permission_rule(rule.model_dump())
        self._persist_permission_state()
        self.controller.ensure_autosave()
        scope = (
            json.dumps(matcher, ensure_ascii=False, sort_keys=True)
            if matcher
            else "all matching calls"
        )
        return (
            f"Permission rule added: {normalized_behavior} {normalized_tool} ({scope})"
        )

    def clear_permission_rules(self, *, source: Optional[str] = "session") -> str:
        normalized = str(source or "session").strip() or "session"
        target = None if normalized in {"all", "*"} else normalized
        self.controller.core.clear_permission_rules(source=target)
        self._persist_permission_state()
        return f"Permission rules cleared: {target or 'all'}"

    def get_permission_status_payload(self) -> dict[str, Any]:
        mode = self.controller.core.inspector.read("permissions")["mode"]
        rules = self._permission_rules_payload()
        source_counts: dict[str, int] = {}
        behavior_counts: dict[str, int] = {}
        for rule in rules:
            source = str(rule.get("source") or "session")
            behavior = str(rule.get("behavior") or "")
            source_counts[source] = source_counts.get(source, 0) + 1
            behavior_counts[behavior] = behavior_counts.get(behavior, 0) + 1
        return {
            "mode": mode,
            "ruleCount": len(rules),
            "sourceCounts": source_counts,
            "behaviorCounts": behavior_counts,
            "rules": rules,
            "history": self._permission_history()[-20:],
        }

    def format_permissions(self) -> str:
        payload = self.get_permission_status_payload()
        lines = [
            f"Permission mode: {payload.get('mode') or '-'}",
            f"Rules: {payload.get('ruleCount', 0)}",
        ]
        source_counts = dict(payload.get("sourceCounts") or {})
        if source_counts:
            lines.append(
                "Sources: "
                + ", ".join(
                    f"{source}={count}"
                    for source, count in sorted(source_counts.items())
                )
            )
        rules = list(payload.get("rules") or [])
        if rules:
            lines.append("")
            lines.append("Rules:")
            for index, rule in enumerate(rules, start=1):
                matcher = rule.get("matcher") or {}
                matcher_text = (
                    json.dumps(matcher, ensure_ascii=False, sort_keys=True)
                    if matcher
                    else "{}"
                )
                description = str(rule.get("description") or "").strip()
                suffix = f" | {description}" if description else ""
                lines.append(
                    f"{index}. {rule.get('behavior')} {rule.get('tool_name')} "
                    f"source={rule.get('source') or '-'} matcher={matcher_text}{suffix}"
                )
        else:
            lines.append("No permission rules.")
        lines.append("")
        lines.append("Usage:")
        lines.append("/permissions mode <default|accept_edits|dont_ask|bypass|plan>")
        lines.append(
            "/permissions allow <tool|*> [path=prefix] [host=domain] [command=prefix] [mcp=server] [risk=category]"
        )
        lines.append(
            "/permissions deny <tool|*> [path=prefix] [host=domain] [command=prefix] [mcp=server] [risk=category]"
        )
        lines.append(
            "/permissions ask <tool|*> [path=prefix] [host=domain] [command=prefix] [mcp=server] [risk=category]"
        )
        lines.append("/permissions clear [session|source|all]")
        return "\n".join(lines)

    def format_permission_history(self) -> str:
        history = self._permission_history()
        if not history:
            return "No permission history."
        lines = []
        for item in history[-20:]:
            action = str(item.get("action") or "-")
            ts = str(item.get("ts") or "-")
            details = {
                key: value for key, value in item.items() if key not in {"action", "ts"}
            }
            lines.append(
                f"{ts} | {action} | {json.dumps(details, ensure_ascii=False, sort_keys=True)}"
            )
        return "\n".join(lines)

    def enter_plan_mode(self) -> str:
        self.controller.core.set_plan_mode(True)
        return "Entered plan mode."

    def exit_plan_mode(self) -> str:
        target_mode = self.controller.core.configuration().product.permission_mode
        self.controller.core.set_plan_mode(False)
        return f"Exited plan mode. Permission mode restored to {target_mode}."

    def get_pending_interaction(self) -> Optional[dict[str, Any]]:
        request = self.controller.core.pending()
        if request is None:
            self._displayed_interaction = None
            return None
        self._displayed_interaction = {
            "interaction_id": request.interaction_id,
            "tool_name": request.tool_name,
            "tool_id": request.interaction_id,
            "tool_args": request.arguments,
            "metadata": {**request.details, "interaction_type": request.kind},
        }
        return self._displayed_interaction

    def get_pending_risk_payload(self) -> dict[str, Any]:
        payload = self.get_pending_interaction()
        if payload is None:
            return {"active": False}
        metadata = dict(payload.get("metadata") or {})
        interaction_type = str(metadata.get("interaction_type") or "confirmation")
        tool_name = str(payload.get("tool_name") or "").strip()
        tool_args = dict(payload.get("tool_args") or {})
        command = str(tool_args.get("command") or "").strip().lower()
        title = "Approval required"
        risk_level = "low"
        reversible = True
        affects_shared_state = False
        overwrites_local_changes = False
        if interaction_type == "ask_user_question":
            title = "Answer needed"
        elif interaction_type in {"enter_plan_mode", "exit_plan_mode"}:
            title = "Mode change pending"
            risk_level = "medium"
        if tool_name == "Bash" and "git push" in command:
            title = "Git push approval"
            risk_level = "high"
            reversible = False
            affects_shared_state = True
        elif tool_name == "ExitWorktree" and bool(tool_args.get("discard_changes")):
            title = "Discard worktree changes"
            risk_level = "high"
            reversible = False
            overwrites_local_changes = True
        elif tool_name in {"TaskStop", "AgentStop"}:
            title = "Stop background work"
            risk_level = "medium"
            reversible = False
        elif tool_name == "Rewind" or "rewind" in command:
            title = "Session rewind"
            risk_level = "high"
            reversible = False
            overwrites_local_changes = True
        elif tool_name and (
            "edit" in tool_name.lower() or "write" in tool_name.lower()
        ):
            risk_level = "medium"
        return {
            "active": True,
            "interaction_type": interaction_type,
            "title": title,
            "tool_name": tool_name or None,
            "reason": str(metadata.get("reason") or "").strip() or None,
            "risk_level": risk_level,
            "reversible": reversible,
            "affects_shared_state": affects_shared_state,
            "overwrites_local_changes": overwrites_local_changes,
            "remember_supported": interaction_type not in {"ask_user_question"},
        }

    def format_pending_interaction(self) -> str:
        payload = self.get_pending_interaction()
        if payload is None:
            return "No pending interaction."
        return self._format_pending_payload(payload)

    def _format_pending_payload(self, payload: dict[str, Any]) -> str:
        metadata = dict(payload.get("metadata") or {})
        interaction_type = str(metadata.get("interaction_type") or "confirmation")
        lines: list[str] = []
        tool_name = str(payload.get("tool_name") or "").strip()
        message = str(payload.get("message") or "").strip()
        risk_payload = self.get_pending_risk_payload()

        if interaction_type == "ask_user_question":
            lines.append("The agent needs your answer before it can continue.")
            if message:
                lines.extend(["", message])
            questions = list(metadata.get("questions") or [])
            if questions:
                lines.append("")
                lines.append("Questions:")
                for index, item in enumerate(questions, start=1):
                    header = str(item.get("header") or f"Question {index}").strip()
                    question = str(item.get("question") or "").strip()
                    lines.append(f"{index}. {header}")
                    if question:
                        lines.append(f"   {question}")
                    for option in list(item.get("options") or []):
                        label = str(option.get("label") or "").strip()
                        description = str(option.get("description") or "").strip()
                        bullet = f"   - {label}" if label else "   - option"
                        if description:
                            bullet += f": {description}"
                        lines.append(bullet)
            lines.append("")
            lines.append("Next step:")
            lines.append("- Reply with `/answer <text>`.")
            lines.append("- Use `/deny [reason]` to cancel.")
            return "\n".join(lines)

        if interaction_type == "enter_plan_mode":
            lines.append(
                "The agent wants to switch into planning mode before making changes."
            )
        elif interaction_type == "exit_plan_mode":
            lines.append(
                "The agent is ready to leave planning mode and continue execution."
            )
        else:
            lines.append("The agent is waiting for your approval before it continues.")
        if message:
            lines.extend(["", message])
        if tool_name:
            lines.append(f"Tool: {tool_name}")
        reason = str(metadata.get("reason") or "").strip()
        if reason:
            lines.append(f"Why this needs approval: {reason}")
        if risk_payload.get("active"):
            lines.append(
                "Risk: "
                f"{risk_payload.get('risk_level', 'unknown')} | "
                f"reversible={risk_payload.get('reversible')} | "
                f"shared_state={risk_payload.get('affects_shared_state')} | "
                f"overwrites_local_changes={risk_payload.get('overwrites_local_changes')}"
            )
        allowed_actions = list(metadata.get("allowedActions") or [])
        if allowed_actions:
            lines.append("What it wants to do:")
            lines.extend(f"- {item}" for item in allowed_actions)
        allowed_prompts = list(metadata.get("allowedPrompts") or [])
        if allowed_prompts:
            lines.append("Requested permission categories:")
            for item in allowed_prompts:
                tool = str(item.get("tool") or "tool").strip()
                prompt = str(item.get("prompt") or "").strip()
                if prompt:
                    lines.append(f"- {tool}: {prompt}")
                else:
                    lines.append(f"- {tool}")
        tool_args = payload.get("tool_args") or {}
        if isinstance(tool_args, dict) and tool_args:
            lines.append("Requested arguments:")
            lines.append(json.dumps(tool_args, ensure_ascii=False, indent=2))
        lines.append("")
        lines.append("Next step:")
        lines.append("- Approve with `/confirm [note]`.")
        lines.append("- Approve and remember a session rule with `/confirm remember`.")
        lines.append("- Deny with `/deny [reason]`.")
        lines.append("- Deny and remember a session rule with `/deny remember`.")
        return "\n".join(lines)

    @staticmethod
    def _answer_requests_permission_remember(answer: str) -> bool:
        normalized = str(answer or "").strip().lower()
        if not normalized:
            return False
        tokens = {token.strip(" ,.;:") for token in normalized.split()}
        return bool(
            tokens & {"remember", "remember-session", "allow-session", "deny-session"}
        )

    async def stream_resolve_pending_interaction(
        self, *, action: str, answer: str = "", max_iter: int = 50
    ):
        payload = self._displayed_interaction or self.get_pending_interaction()
        if payload is None:
            yield {"type": "system_notice", "content": "No pending interaction."}
            return
        self.controller.core.respond(
            payload["interaction_id"],
            action=action,
            answer=answer,
            remember=self._answer_requests_permission_remember(answer),
        )
        self._displayed_interaction = None
        yield {
            "type": "interaction_resolved",
            "content": "Interaction resolved. Resuming execution.",
            "payload": payload,
        }
        async for event in self.controller.stream_prompt(
            "Continue from the resolved tool interaction using the result already present in history.",
            max_iter=max_iter,
        ):
            yield event
