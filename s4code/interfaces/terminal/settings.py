"""Terminal preferences and backward-compatible on-disk configuration layout."""

from pydantic import BaseModel, Field
from s4code.core.settings import (
    S4AgentSettings,
    LLMSettings,
    ProductSettings,
    ContextSettings,
    MCPServerSettings,
    PermissionRuleSettings,
)
from s4code.core.configuration import (
    load_settings_payload,
    dump_settings_yaml,
    save_settings,
)

__all__ = [
    "S4Settings",
    "UISettings",
    "resolve_settings",
    "LLMSettings",
    "ProductSettings",
    "ContextSettings",
    "MCPServerSettings",
    "PermissionRuleSettings",
    "dump_settings_yaml",
    "save_settings",
]


class UISettings(BaseModel):
    theme: str = "s4"
    show_thinking: bool = True
    right_panel_open: bool = False


class S4Settings(S4AgentSettings):
    ui: UISettings = Field(default_factory=UISettings)


def resolve_settings(paths, *, project_root=None, session_overrides=None) -> S4Settings:
    return S4Settings.model_validate(
        load_settings_payload(
            paths,
            project_root=project_root,
            session_overrides=session_overrides,
        )
    )
