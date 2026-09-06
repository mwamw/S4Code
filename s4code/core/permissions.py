"""Product permission changes and persistence, independent of command syntax."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from easyagent.permissions import PermissionMode, PermissionRule
from .settings import PermissionRuleSettings

if TYPE_CHECKING:
    from .agent import S4CodeAgent


class S4Permissions:
    def __init__(self, agent: S4CodeAgent):
        self.agent = agent

    def rules(self) -> list[dict[str, Any]]:
        return [
            rule.model_dump(mode="json")
            for rule in self.agent.permission_context.iter_rules()
        ]

    def synchronize(self) -> None:
        """Called inside a product operation after framework state changes."""
        product = self.agent.settings.product
        mode = self.agent.permission_context.mode.value
        # PLAN is temporary: retain the mode to return to on exit.
        if mode != PermissionMode.PLAN.value:
            product.permission_mode = mode
        product.permission_rules = [
            PermissionRuleSettings.model_validate(rule) for rule in self.rules()
        ]
        if self.agent.session is not None:
            overrides = self.agent.session.overrides.setdefault("product", {})
            overrides.update(
                permission_mode=product.permission_mode,
                permission_rules=self.rules(),
                permission_history=product.permission_history,
            )

    def _record(self, action: str, **payload: Any) -> None:
        product = self.agent.settings.product
        product.permission_history = [
            *product.permission_history,
            {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "action": action,
                **payload,
            },
        ][-100:]
        self.synchronize()
        if self.agent.session is not None:
            self.agent.session.dirty = True
            self.agent.session._autosave()

    def set_mode(self, mode: str | PermissionMode) -> None:
        with self.agent.operation():
            self.agent.set_permission_mode(mode)
            self._record("mode", mode=PermissionMode(mode).value)

    def add_rule(self, rule: PermissionRule, *, source: str | None = None) -> None:
        with self.agent.operation():
            self.agent.add_permission_rule(rule, source=source)
            self._record(
                "rule_added",
                tool=rule.tool_name,
                behavior=rule.behavior.value,
                source=source or rule.source,
                matcher=dict(rule.matcher),
            )

    def clear_rules(self, *, source: str | None = "session") -> None:
        with self.agent.operation():
            self.agent.permission_context.clear_rules(source=source)
            self._record("rules_cleared", source=source or "all")
