from s4code.command_registry import S4CommandRegistry
from s4code.command_types import CommandKind, CommandResult, S4Command, parse_command
from s4code.commands import register_builtin_commands


class _DummyEngine:
    def __init__(self) -> None:
        self.queued_skills: list[str] = []
        self.checkpoints: list[str] = []

    def format_doctor(self) -> str:
        return "doctor"

    def format_help(self) -> str:
        return "help"

    def format_status_overview(self) -> str:
        return "status-overview"

    def format_models(self) -> str:
        return "models"

    def update_model(self, target: str) -> str:
        return f"switch:{target}"

    def format_themes(self) -> str:
        return "themes"

    def update_theme(self, target: str) -> str:
        if target == "missing":
            return "Unknown theme: missing"
        return f"theme:{target}"

    def format_context(self) -> str:
        return "context"

    def format_pending_interaction(self) -> str:
        return "pending"

    def format_permissions(self) -> str:
        return "permissions"

    def format_permission_history(self) -> str:
        return "permission-history"

    def update_permission_mode(self, mode: str) -> str:
        return f"permission-mode:{mode}"

    def add_permission_rule_from_tokens(self, *, behavior: str, tool_name: str, tokens: list[str]) -> str:
        return f"permission-rule:{behavior}:{tool_name}:{','.join(tokens)}"

    def clear_permission_rules(self, *, source: str | None = "session") -> str:
        return f"permission-clear:{source}"

    def format_sessions(self) -> str:
        return "sessions"

    def resume_session(self, session_id: str) -> str:
        return f"resumed:{session_id}"

    def format_current_session(self) -> str:
        return "current-session"

    def format_timeline(self) -> str:
        return "timeline"

    def format_checkpoints(self) -> str:
        return "checkpoints"

    def format_session_tree(self) -> str:
        return "session-tree"

    def create_checkpoint(self, label: str | None = None, *, reason: str = "manual") -> dict[str, object]:
        checkpoint_id = f"cp-{len(self.checkpoints) + 1:03d}"
        self.checkpoints.append(label or "")
        return {
            "checkpoint_id": checkpoint_id,
            "label": label or f"checkpoint {len(self.checkpoints)}",
            "history_messages": 3,
        }

    def rewind_to_checkpoint(self, target: str | None = None) -> str:
        return f"rewound:{target or 'last'}"

    def format_tools(self) -> str:
        return "tools"

    def format_restore_report(self) -> str:
        return "restore"

    def compact_history(self, max_tokens: int | None = None) -> str:
        return f"compact:{max_tokens}"

    def format_trace(self) -> str:
        return "trace"

    def format_hooks(self) -> str:
        return "hooks"

    def format_mcp(self) -> str:
        return "mcp"

    def format_mcp_server_detail(self, server_name: str, *, refresh: bool = False) -> str:
        return f"mcp-status:{server_name}:{refresh}"

    def format_mcp_tools(self, server_name: str) -> str:
        return f"mcp-tools:{server_name}"

    def format_mcp_resources(self, server_name: str) -> str:
        return f"mcp-resources:{server_name}"

    def refresh_mcp(self, server_name: str | None = None) -> str:
        return f"mcp-refresh:{server_name or 'all'}"

    def connect_mcp(self, server_name: str | None = None) -> str:
        return f"mcp-connect:{server_name or 'all'}"

    def disconnect_mcp(self, server_name: str | None = None) -> str:
        return f"mcp-disconnect:{server_name or 'all'}"

    def format_skills(self) -> str:
        return "skills"

    def queue_turn_skill(self, name: str) -> str:
        self.queued_skills.append(name)
        return f"queued:{name}"

    def clear_turn_skills(self) -> str:
        self.queued_skills.clear()
        return "skills-cleared"

    def format_worktree_status(self) -> str:
        return "worktree"

    def enter_worktree(self, name: str | None = None) -> str:
        return f"worktree-enter:{name or 'auto'}"

    def exit_worktree(self, *, action: str = "keep", discard_changes: bool = False) -> str:
        return f"worktree-exit:{action}:{discard_changes}"

    def format_agents(self) -> str:
        return "agents"

    def format_agent_detail(self, agent_id: str) -> str:
        return f"agent:{agent_id}"

    def wait_for_agent(self, agent_id: str, *, timeout_ms: int | None = None) -> str:
        return f"agent-wait:{agent_id}:{timeout_ms}"

    def stop_agent(self, agent_id: str, *, reason: str = "", wait: bool = False, timeout_ms: int | None = None) -> str:
        return f"agent-stop:{agent_id}:{reason}:{wait}:{timeout_ms}"

    def format_tasks(self) -> str:
        return "tasks"

    def format_task_detail(self, task_id: str) -> str:
        return f"task:{task_id}"

    def format_task_output(self, task_id: str, *, block: bool = False, timeout_ms: int | None = None) -> str:
        return f"task-output:{task_id}:{block}:{timeout_ms}"

    def stop_task(self, task_id: str) -> str:
        return f"task-stop:{task_id}"

    def format_runtime_panel(self) -> str:
        return "runtime"

    def rename_session(self, title: str) -> str:
        return f"renamed:{title}"

    def fork_session(self, title: str | None = None) -> str:
        return f"forked:{title or 'default'}"


def test_parse_command() -> None:
    invocation = parse_command("/review src")
    assert invocation is not None
    assert invocation.name == "review"
    assert invocation.args == ["src"]
    assert invocation.arg_text == "src"


def test_registry_alias_resolution() -> None:
    registry = S4CommandRegistry()

    def _handler(engine, invocation):
        return CommandResult.info(f"handled:{invocation.name}")

    registry.register(
        S4Command(
            name="help",
            kind=CommandKind.LOCAL,
            description="help",
            handler=_handler,
            aliases=("h",),
        )
    )
    result = registry.execute(_DummyEngine(), "/h")
    assert result is not None
    assert result.message == "handled:h"


def test_registry_match_commands() -> None:
    registry = S4CommandRegistry()

    def _handler(engine, invocation):
        return CommandResult.info("ok")

    registry.register(S4Command("help", CommandKind.LOCAL, "help", _handler, aliases=("h",)))
    registry.register(S4Command("hooks", CommandKind.LOCAL, "hooks", _handler))
    registry.register(S4Command("review", CommandKind.WORKFLOW, "review", _handler))

    matches = registry.match_commands("ho")
    assert [item.name for item in matches] == ["hooks"]


def test_registry_match_commands_keeps_full_result_set() -> None:
    registry = S4CommandRegistry()

    def _handler(engine, invocation):
        return CommandResult.info("ok")

    for name in ("help", "hooks", "history", "home", "hosts", "hover", "hold", "howto", "hotfix", "hostsfile"):
        registry.register(S4Command(name, CommandKind.LOCAL, name, _handler))

    matches = registry.match_commands("ho")
    assert len(matches) == 8
    assert matches[0].name == "hold"


def test_builtin_model_and_context_commands() -> None:
    registry = S4CommandRegistry()
    register_builtin_commands(registry)
    engine = _DummyEngine()

    result = registry.execute(engine, "/model")
    assert result is not None
    assert result.message == "models"

    result = registry.execute(engine, "/model local-qwen")
    assert result is not None
    assert result.message == "switch:local-qwen"

    result = registry.execute(engine, "/theme")
    assert result is not None
    assert result.message == "themes"


def test_builtin_help_and_status_commands_use_user_facing_output() -> None:
    registry = S4CommandRegistry()
    register_builtin_commands(registry)
    engine = _DummyEngine()

    result = registry.execute(engine, "/help")
    assert result is not None
    assert result.message == "help"

    result = registry.execute(engine, "/status")
    assert result is not None
    assert result.message == "status-overview"

    result = registry.execute(engine, "/theme list")
    assert result is not None
    assert result.message == "themes"

    result = registry.execute(engine, "/theme ember")
    assert result is not None
    assert result.message == "theme:ember"
    assert result.metadata["ui_action"] == "reload_theme"

    result = registry.execute(engine, "/theme missing")
    assert result is not None
    assert result.message == "Unknown theme: missing"
    assert result.metadata == {}

    result = registry.execute(engine, "/context")
    assert result is not None
    assert result.message == "context"

    result = registry.execute(engine, "/permissions")
    assert result is not None
    assert result.message == "permissions"

    result = registry.execute(engine, "/permissions mode bypass")
    assert result is not None
    assert result.message == "permission-mode:bypass"

    result = registry.execute(engine, "/permissions dont_ask")
    assert result is not None
    assert result.message == "permission-mode:dont_ask"

    result = registry.execute(engine, "/permissions allow FileEdit path=src source=session")
    assert result is not None
    assert result.message == "permission-rule:allow:FileEdit:path=src,source=session"

    result = registry.execute(engine, "/permissions deny WebFetch host=example.com")
    assert result is not None
    assert result.message == "permission-rule:deny:WebFetch:host=example.com"

    result = registry.execute(engine, "/permissions history")
    assert result is not None
    assert result.message == "permission-history"

    result = registry.execute(engine, "/permissions clear all")
    assert result is not None
    assert result.message == "permission-clear:all"

    result = registry.execute(engine, "/doctor")
    assert result is not None
    assert result.message == "doctor"

    result = registry.execute(engine, "/tools")
    assert result is not None
    assert result.message == "tools"

    result = registry.execute(engine, "/restore")
    assert result is not None
    assert result.message == "restore"

    result = registry.execute(engine, "/trace")
    assert result is not None
    assert result.message == "trace"

    result = registry.execute(engine, "/hooks")
    assert result is not None
    assert result.message == "hooks"


def test_builtin_pending_and_resolution_commands() -> None:
    registry = S4CommandRegistry()
    register_builtin_commands(registry)
    engine = _DummyEngine()

    result = registry.execute(engine, "/pending")
    assert result is not None
    assert result.message == "pending"

    result = registry.execute(engine, "/confirm")
    assert result is not None
    assert result.metadata["engine_action"] == "confirm_pending"

    result = registry.execute(engine, "/deny too risky")
    assert result is not None
    assert result.metadata["engine_action"] == "deny_pending"
    assert result.metadata["answer"] == "too risky"

    result = registry.execute(engine, "/answer choose option A")
    assert result is not None
    assert result.metadata["engine_action"] == "answer_pending"
    assert result.metadata["answer"] == "choose option A"


def test_builtin_skill_worktree_agent_and_task_commands() -> None:
    registry = S4CommandRegistry()
    register_builtin_commands(registry)
    engine = _DummyEngine()

    result = registry.execute(engine, "/skills")
    assert result is not None
    assert result.message == "skills"

    result = registry.execute(engine, "/skills use reviewer")
    assert result is not None
    assert result.message == "queued:reviewer"
    assert engine.queued_skills == ["reviewer"]

    result = registry.execute(engine, "/skills clear")
    assert result is not None
    assert result.message == "skills-cleared"
    assert engine.queued_skills == []

    result = registry.execute(engine, "/worktree")
    assert result is not None
    assert result.message == "worktree"

    result = registry.execute(engine, "/worktree enter feature-123")
    assert result is not None
    assert result.message == "worktree-enter:feature-123"

    result = registry.execute(engine, "/worktree exit remove discard")
    assert result is not None
    assert result.message == "worktree-exit:remove:True"

    result = registry.execute(engine, "/mcp")
    assert result is not None
    assert result.message == "mcp"

    result = registry.execute(engine, "/mcp status filesystem")
    assert result is not None
    assert result.message == "mcp-status:filesystem:False"

    result = registry.execute(engine, "/mcp tools filesystem")
    assert result is not None
    assert result.message == "mcp-tools:filesystem"

    result = registry.execute(engine, "/mcp resources filesystem")
    assert result is not None
    assert result.message == "mcp-resources:filesystem"

    result = registry.execute(engine, "/mcp refresh")
    assert result is not None
    assert result.message == "mcp-refresh:all"

    result = registry.execute(engine, "/mcp connect filesystem")
    assert result is not None
    assert result.message == "mcp-connect:filesystem"

    result = registry.execute(engine, "/mcp disconnect")
    assert result is not None
    assert result.message == "mcp-disconnect:all"

    result = registry.execute(engine, "/agent")
    assert result is not None
    assert result.message == "agents"

    result = registry.execute(engine, "/agent show agent-1")
    assert result is not None
    assert result.message == "agent:agent-1"

    result = registry.execute(engine, "/agent wait agent-1 500")
    assert result is not None
    assert result.message == "agent-wait:agent-1:500"

    result = registry.execute(engine, "/agent stop agent-1 too noisy")
    assert result is not None
    assert result.message == "agent-stop:agent-1:too noisy:False:None"

    result = registry.execute(engine, "/task show task-1")
    assert result is not None
    assert result.message == "task:task-1"

    result = registry.execute(engine, "/task output task-1 250")
    assert result is not None
    assert result.message == "task-output:task-1:True:250"

    result = registry.execute(engine, "/task stop task-1")
    assert result is not None
    assert result.message == "task-stop:task-1"

    result = registry.execute(engine, "/runtime")
    assert result is not None
    assert result.message == "runtime"

    result = registry.execute(engine, "/rt")
    assert result is not None
    assert result.message == "runtime"

    result = registry.execute(engine, "/task output task-1 nope")
    assert result is not None
    assert result.message == "Usage: /task output <task_id> [timeout_ms]"


def test_builtin_session_subcommands_and_copy_command() -> None:
    registry = S4CommandRegistry()
    register_builtin_commands(registry)
    engine = _DummyEngine()

    result = registry.execute(engine, "/session")
    assert result is not None
    assert result.message == "current-session"

    result = registry.execute(engine, "/session list")
    assert result is not None
    assert result.message == "sessions"

    result = registry.execute(engine, "/session load sess-123")
    assert result is not None
    assert result.message == "resumed:sess-123"

    result = registry.execute(engine, "/session rename Bugfix Investigation")
    assert result is not None
    assert result.message == "renamed:Bugfix Investigation"

    result = registry.execute(engine, "/session fork Parallel Review")
    assert result is not None
    assert result.message == "forked:Parallel Review"

    result = registry.execute(engine, "/session timeline")
    assert result is not None
    assert result.message == "timeline"

    result = registry.execute(engine, "/session checkpoints")
    assert result is not None
    assert result.message == "checkpoints"

    result = registry.execute(engine, "/session tree")
    assert result is not None
    assert result.message == "session-tree"

    result = registry.execute(engine, "/session rewind cp-001")
    assert result is not None
    assert result.message == "rewound:cp-001"

    result = registry.execute(engine, "/copy transcript")
    assert result is not None
    assert result.metadata["ui_action"] == "copy_to_clipboard"
    assert result.metadata["copy_target"] == "transcript"


def test_builtin_checkpoint_rewind_timeline_and_compact_commands() -> None:
    registry = S4CommandRegistry()
    register_builtin_commands(registry)
    engine = _DummyEngine()

    result = registry.execute(engine, "/checkpoint manual save")
    assert result is not None
    assert "Checkpoint created: cp-001" in result.message

    result = registry.execute(engine, "/checkpoint list")
    assert result is not None
    assert result.message == "checkpoints"

    result = registry.execute(engine, "/checkpoints")
    assert result is not None
    assert result.message == "checkpoints"

    result = registry.execute(engine, "/rewind cp-001")
    assert result is not None
    assert result.message == "rewound:cp-001"

    result = registry.execute(engine, "/timeline")
    assert result is not None
    assert result.message == "timeline"

    result = registry.execute(engine, "/compact")
    assert result is not None
    assert result.message == "compact:None"

    result = registry.execute(engine, "/compact partial 12000")
    assert result is not None
    assert result.message == "compact:12000"

    result = registry.execute(engine, "/compact nope")
    assert result is not None
    assert result.message == "Usage: /compact [partial <max_tokens>|<max_tokens>]"
