"""Configuration for the S4Code Agent, independent of terminal preferences."""

from typing import Optional, Any
from pydantic import BaseModel, Field


class LLMSettings(BaseModel):
    provider: str
    model: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    timeout: Optional[int] = None
    reasoning_effort: Optional[str] = "medium"
    reasoning_summary: Optional[str] = None
    user_agent: Optional[str] = None


class MCPServerSettings(BaseModel):
    name: str
    server_source: str
    server_args: list[str] = Field(default_factory=list)
    transport_type: Optional[str] = None
    tool_prefix: str = ""
    enabled: bool = True
    persist_connection: bool = True
    max_retries: Optional[int] = None
    include_resources: bool = True
    env: dict[str, str] = Field(default_factory=dict)
    auth: Optional[dict[str, Any]] = None
    policy: Optional[dict[str, Any]] = None
    transport_kwargs: dict[str, Any] = Field(default_factory=dict)


class PermissionRuleSettings(BaseModel):
    tool_name: str = "*"
    behavior: str = "ask"
    matcher: dict[str, Any] = Field(default_factory=dict)
    source: str = "session"
    description: Optional[str] = None


class ProductSettings(BaseModel):
    permission_mode: str = "accept_edits"
    permission_rules: list[PermissionRuleSettings] = Field(default_factory=list)
    permission_history: list[dict[str, Any]] = Field(default_factory=list)
    enable_codeintel: bool = True
    enable_mcp: bool = True
    enable_worktree: bool = True
    git_binary: str = "git"
    shell: str = "bash"
    command_timeout_ms: int = 120000
    max_background_tasks: int = 4
    session_auto_save: bool = True
    default_review_depth: str = "full"
    enable_verifier: bool = True


class ContextSettings(BaseModel):
    enabled: bool = True
    max_tokens: int = 24000
    history_compactor: str = "llm"
    recent_turns: int = 4


class S4AgentSettings(BaseModel):
    active_model_profile: str = "default"
    model_profiles: dict[str, LLMSettings] = Field(default_factory=dict)
    llm: LLMSettings
    context: ContextSettings = Field(default_factory=ContextSettings)
    product: ProductSettings = Field(default_factory=ProductSettings)
    mcp_servers: list[MCPServerSettings] = Field(default_factory=list)
