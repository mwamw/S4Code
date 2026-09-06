"""Validated protocol handlers calling product Core, never a terminal."""

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from s4code.core.errors import InvalidRequestError
from s4code.core.contracts import ConversationSnapshot
from s4code.core.workflows import ReviewWorkflow, CommitWorkflow


class CoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1)
    method: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class EmptyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str | None = Field(default=None, min_length=1)


class ModelParams(EmptyParams):
    target: str = Field(min_length=1)


class CompactParams(EmptyParams):
    max_tokens: int | None = Field(default=None, gt=0)


class SaveParams(EmptyParams):
    title: str | None = None


class RespondParams(EmptyParams):
    interaction_id: str = Field(min_length=1)
    action: Literal["approve", "deny", "answer"]
    answer: str = ""
    remember: bool = False


class RestoreConversationParams(EmptyParams):
    snapshot: ConversationSnapshot


class SnapshotSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    namespace: str = Field(min_length=1)
    path: list[str | int] = Field(min_length=1)
    format: Literal["snapshot", "state", "history"] = "snapshot"


class CaptureConversationParams(EmptyParams):
    source: SnapshotSource | None = None


class SnapshotReferenceParams(EmptyParams):
    snapshot_id: str = Field(min_length=1)


class DeleteSnapshotsParams(EmptyParams):
    snapshot_ids: list[str] = Field(max_length=1000)


class MCPParams(EmptyParams):
    action: Literal["connect", "disconnect", "refresh"]
    server_name: str | None = None


class StopParams(EmptyParams):
    reason: str = ""
    run_id: str | None = None


class StreamParams(EmptyParams):
    prompt: str = Field(min_length=1)
    max_iter: int = Field(default=50, gt=0)


class InspectParams(EmptyParams):
    topic: Literal[
        "state",
        "history",
        "tools",
        "tool_specs",
        "mode",
        "metrics",
        "skill_sources",
        "process",
        "agent",
        "mcp_status",
        "models",
        "permissions",
        "context",
        "trace",
        "cost",
        "restore",
        "skills",
        "tasks",
        "task",
        "processes",
        "agents",
        "worktree",
        "mcp",
        "hooks",
        "files",
        "diff",
        "diagnostics",
        "configuration",
    ]
    target: str | None = None
    limit: int = Field(default=30, gt=0, le=1000)


class ExtensionParams(EmptyParams):
    namespace: str = Field(min_length=1)


class WriteExtensionParams(ExtensionParams):
    value: dict[str, Any]


class ReadExtensionParams(ExtensionParams):
    exclude_fields: list[str] = Field(default_factory=list)


class ModeParams(EmptyParams):
    mode: str = Field(min_length=1)


class RuleParams(EmptyParams):
    rule: dict[str, Any]


class ClearRulesParams(EmptyParams):
    source: str = "session"


class SkillParams(EmptyParams):
    name: str = Field(min_length=1)


class PlanParams(EmptyParams):
    enabled: bool


class RuntimeActionParams(EmptyParams):
    action: Literal[
        "task.stop",
        "task.output",
        "worktree.enter",
        "worktree.exit",
        "agent.stop",
        "agent.wait",
    ]
    arguments: dict[str, Any] = Field(default_factory=dict)


class WorkflowParams(EmptyParams):
    kind: Literal["review", "commit"]
    target: str | None = None


class CoreRequestHandler:
    PARAMS = {
        "core.model.select": ModelParams,
        "core.context.compact": CompactParams,
        "core.session.save": SaveParams,
        "core.session.fork": SaveParams,
        "core.session.list": EmptyParams,
        "core.session.create": EmptyParams,
        "core.session.open": EmptyParams,
        "core.session.close": EmptyParams,
        "core.interaction.pending": EmptyParams,
        "core.interaction.respond": RespondParams,
        "core.conversation.export": EmptyParams,
        "core.conversation.restore": RestoreConversationParams,
        "core.conversation.capture": CaptureConversationParams,
        "core.conversation.restore_ref": SnapshotReferenceParams,
        "core.conversation.delete_snapshots": DeleteSnapshotsParams,
        "core.conversation.clear": EmptyParams,
        "core.mcp.action": MCPParams,
        "core.stop": StopParams,
        "core.state": EmptyParams,
        "core.inspect": InspectParams,
        "core.extension.read": ReadExtensionParams,
        "core.extension.write": WriteExtensionParams,
        "core.permissions.mode": ModeParams,
        "core.permissions.add": RuleParams,
        "core.permissions.clear": ClearRulesParams,
        "core.skill.activate": SkillParams,
        "core.plan.set": PlanParams,
        "core.runtime.action": RuntimeActionParams,
        "core.workflow": WorkflowParams,
    }

    def __init__(self, session, runtime=None):
        self.session, self.runtime = session, runtime

    def handle(self, method, params):
        schema = self.PARAMS.get(method)
        if schema is None:
            raise InvalidRequestError(f"Unknown Core method: {method}")
        p = schema.model_validate(params).model_dump()
        if method in {"core.session.create", "core.session.open", "core.session.list"}:
            if self.runtime is None:
                raise InvalidRequestError("Runtime is required for session operations")
            if method == "core.session.list":
                return [
                    item.model_dump(mode="json")
                    for item in self.runtime.list_sessions()
                ]
            if method == "core.session.open" and not p["session_id"]:
                raise InvalidRequestError("session_id is required")
            if method == "core.session.create" and p["session_id"]:
                raise InvalidRequestError(
                    "Creating a session does not accept session_id"
                )
            return (
                self.runtime.open_session(p["session_id"])
                .info()
                .model_dump(mode="json")
            )
        s = self.session
        if p["session_id"] and p["session_id"] != s.id:
            if self.runtime is None:
                raise InvalidRequestError("Unknown session")
            s = self.runtime.open_session(p["session_id"])
        if method == "core.state":
            return s.state()
        if method == "core.inspect":
            return s.inspector.read(p["topic"], target=p["target"], limit=p["limit"])
        if method == "core.model.select":
            return s.select_model(p["target"])
        if method == "core.context.compact":
            return s.compact(p["max_tokens"])
        if method == "core.session.save":
            return s.save(p["title"]).model_dump(mode="json")
        if method == "core.session.fork":
            return s.fork(p["title"]).model_dump(mode="json")
        if method == "core.session.close":
            s.close()
            return {"closed": True}
        if method == "core.interaction.pending":
            pending = s.pending()
            return pending.model_dump(mode="json") if pending else None
        if method == "core.interaction.respond":
            return s.respond(
                p["interaction_id"],
                action=p["action"],
                answer=p["answer"],
                remember=p["remember"],
            )
        if method == "core.conversation.export":
            return s.export_conversation().model_dump(mode="json")
        if method == "core.conversation.restore":
            s.restore_conversation(p["snapshot"])
            return {"restored": True}
        if method == "core.conversation.capture":
            return s.capture_conversation(p["source"])
        if method == "core.conversation.restore_ref":
            s.restore_snapshot(p["snapshot_id"])
            return {"restored": True}
        if method == "core.conversation.delete_snapshots":
            s.delete_snapshots(p["snapshot_ids"])
            return {"deleted": True}
        if method == "core.conversation.clear":
            s.clear_history()
            return {"cleared": True}
        if method == "core.mcp.action":
            return s.mcp_action(p["action"], p["server_name"])
        if method == "core.stop":
            if p["run_id"] and p["run_id"] != s.runs.active_run_id:
                raise InvalidRequestError("Run is no longer active")
            return {"stop_requested": s.runs.cancel(p["reason"])}
        if method == "core.extension.read":
            return s.read_extension(p["namespace"], exclude_fields=p["exclude_fields"])
        if method == "core.extension.write":
            return s.write_extension(p["namespace"], p["value"])
        if method == "core.permissions.mode":
            s.set_permission_mode(p["mode"])
        elif method == "core.permissions.add":
            s.add_permission_rule(p["rule"])
        elif method == "core.permissions.clear":
            s.clear_permission_rules(p["source"])
        elif method == "core.skill.activate":
            return s.activate_skill(p["name"])
        elif method == "core.plan.set":
            s.set_plan_mode(p["enabled"])
        elif method == "core.runtime.action":
            return s.runtime_action(p["action"], p["arguments"])
        elif method == "core.workflow":
            return {
                "prompt": ReviewWorkflow().prompt(p["target"])
                if p["kind"] == "review"
                else CommitWorkflow().prompt()
            }
        else:
            raise InvalidRequestError(f"Unknown Core method: {method}")
        return {"updated": True}
