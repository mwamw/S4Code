"""Serializable product data. No presentation or transport dependencies."""

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class ProductData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunOptions(ProductData):
    max_iter: int = Field(default=50, gt=0)


class SessionInfo(ProductData):
    session_id: str
    title: str
    project_root: str
    model: str | None = None
    provider: str | None = None
    forked_from_session_id: str | None = None


class InteractionRequest(ProductData):
    interaction_id: str
    session_id: str
    kind: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)


class RunResult(ProductData):
    run_id: str
    session_id: str
    status: Literal["completed", "interaction_required", "cancelled", "failed"]
    text: str = ""
    interaction: InteractionRequest | None = None
    error: str | None = None


class RunEvent(ProductData):
    run_id: str
    session_id: str
    sequence: int
    type: str
    content: str = ""
    data: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self):
        return self.model_dump(mode="json")


class ConversationSnapshot(ProductData):
    version: Literal[1] = 1
    session_id: str
    state: dict[str, Any]
