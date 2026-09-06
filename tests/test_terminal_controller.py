import asyncio
import pytest
from test_core_agent import core_agent
from s4code.interfaces.terminal.controller import TerminalController
from s4code.core.application import S4CodeRuntime
from s4code.core.sessions.session import CoreSession
from s4code.interfaces.terminal.settings import S4Settings
from s4code.interfaces.terminal.commands import register_builtin_commands
from easyagent.runtime import AgentStreamEvent, AgentStreamEventType


@pytest.fixture
def terminal(core_agent):
    controller = TerminalController(
        application=S4CodeRuntime(
            cwd=core_agent.project.project_root,
            paths=core_agent.paths,
            settings=core_agent.settings,
            session_store=core_agent.session.store,
        ),
        core=CoreSession(core_agent),
        settings=S4Settings.model_validate(core_agent.settings.model_dump()),
    )
    register_builtin_commands(controller.command_registry)
    return controller


@pytest.mark.parametrize(
    "command",
    [
        "/help",
        "/status",
        "/context",
        "/cost",
        "/trace",
        "/tools",
        "/models",
        "/model",
        "/theme",
        "/session",
        "/sessions",
        "/permissions",
        "/pending",
        "/restore",
        "/skills",
        "/tasks",
        "/agents",
        "/mcp",
        "/worktree",
        "/hooks",
        "/config",
    ],
)
def test_terminal_command_views(terminal, command):
    result = terminal.command_registry.execute(terminal, command)
    assert result is not None
    assert isinstance(result.message, str)


def test_terminal_checkpoint_roundtrip_and_storage(terminal):
    terminal.core._agent.add_user_message("before")
    cp = terminal.checkpoints.create_checkpoint("safe")
    terminal.core._agent.add_user_message("after")
    terminal.checkpoints.rewind_to_checkpoint(cp["checkpoint_id"])
    assert terminal.core._agent.get_history_length() == 1
    terminal.save_session()
    record = terminal.session_manager.get_record(terminal.session_id)
    assert (
        record["metadata"]["extensions"]["terminal"]["checkpoints"][0]["label"]
        == "safe"
    )
    assert "_s4code" not in record["metadata"]["session_overrides"]


def test_checkpoint_ids_remain_unique_after_retention(terminal):
    ids = [terminal.checkpoints.create_checkpoint()["checkpoint_id"] for _ in range(35)]
    assert len(set(ids)) == 35
    assert len(terminal.checkpoints.get_checkpoint_choices()) == 30


def test_legacy_checkpoints_are_migrated(terminal):
    terminal.session_overrides["_s4code"] = {
        "checkpoints": [{"checkpoint_id": "cp-001", "label": "legacy", "history": []}]
    }
    terminal.core._agent.session.extensions.clear()
    terminal.checkpoints._restore_checkpoints_from_overrides()
    assert terminal.checkpoints.get_checkpoint_choices()[0]["label"] == "legacy"
    assert "_s4code" not in terminal.session_overrides


def test_fork_and_resume_replace_agent(terminal):
    terminal.core._agent.add_user_message("original")
    terminal.save_session()
    original, original_id = terminal.core._agent, terminal.session_id
    try:
        terminal.fork_session("branch")
        assert terminal.core._agent is not original
        assert terminal.session_id != original_id
        assert original._closed
        terminal.resume_session(original_id)
        assert terminal.core._agent.get_history_length() == 1
    finally:
        terminal.close()


def test_theme_and_thinking_are_terminal_only(terminal):
    terminal.theme.update_theme("nord")
    terminal.settings.ui.show_thinking = False
    assert not terminal._should_emit_stream_event("thinking_delta")
    assert not hasattr(terminal.core._agent.settings, "ui")


def test_provider_error_details_survive_presentation(terminal):
    event = AgentStreamEvent(
        AgentStreamEventType.ERROR,
        "invoke-test",
        1,
        "request failed",
        {
            "error_type": "RateLimitError",
            "status_code": 429,
            "request_id": "req-test",
            "edge_trace_id": "edge-test",
        },
    )
    result = terminal._translate_core_stream_event(event)
    assert result["status_code"] == 429
    assert result["request_id"] == "req-test"
    assert result["edge_trace_id"] == "edge-test"


def test_stream_uses_core_and_creates_terminal_checkpoints(terminal, monkeypatch):
    async def stream(*args, **kwargs):
        with terminal.core._agent.operation():
            yield AgentStreamEvent(AgentStreamEventType.TEXT_DELTA, "test", 1, "hello")
            yield AgentStreamEvent(AgentStreamEventType.FINAL, "test", 2, "hello")

    monkeypatch.setattr(terminal.core._agent, "astream", stream)

    async def collect():
        return [event async for event in terminal.stream_prompt("hello")]

    events = asyncio.run(collect())
    assert [event["type"] for event in events].count("checkpoint") == 2
    assert any(event["type"] == "final" for event in events)


def test_context_sidebar_and_background_views(terminal):
    assert isinstance(terminal.status.get_sidebar_payload(force=True), dict)
    assert isinstance(terminal.usage.get_context_panel_payload(), dict)
    assert isinstance(terminal.runtime.get_runtime_snapshot_payload(), dict)


def test_status_uses_checkpoint_managers_single_source_of_truth(terminal):
    import json

    terminal.checkpoints.create_checkpoint("first")
    assert json.loads(terminal.status.format_status())["checkpoints"] == 1
    assert (
        terminal.runtime.get_runtime_snapshot_payload()["session"]["checkpoints"] == 1
    )


def test_terminal_approval_uses_displayed_interaction_id(terminal):
    from s4code.sdk import InvalidRequestError

    agent = terminal.core._agent

    def pending(command):
        agent.interrupt_controller.restore_state(
            {
                "last_tool_interrupt": {
                    "tool_name": "Bash",
                    "tool_id": command,
                    "tool_args": {"command": command},
                    "metadata": {},
                }
            }
        )

    pending("first")
    displayed = terminal.permissions.get_pending_interaction()
    pending("second")

    async def check():
        with pytest.raises(InvalidRequestError, match="stale"):
            async for _ in terminal.permissions.stream_resolve_pending_interaction(
                action="approve"
            ):
                pass

    asyncio.run(check())
    assert terminal.core.pending().interaction_id != displayed["interaction_id"]


def test_autosave_failure_is_reported_without_losing_state(terminal, monkeypatch):
    terminal.settings.product.session_auto_save = True

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(
        terminal.core._agent.session.store, "create_or_update_session", fail
    )
    terminal.save_session(tolerate_failure=True)
    assert terminal.core._agent.session.dirty
    assert any("disk full" in issue for issue in terminal.core._agent.startup_issues)


def test_permission_commands_delegate_to_core(terminal):
    terminal.permissions.update_permission_mode("default")
    terminal.permissions.add_permission_rule_from_tokens(
        behavior="deny", tool_name="Bash", tokens=["command=unsafe-command"]
    )
    assert terminal.core._agent.settings.product.permission_mode == "default"
    assert terminal.core._agent.permissions.rules()[0]["behavior"] == "deny"
    terminal.permissions.clear_permission_rules()
    assert terminal.core._agent.permissions.rules() == []
    terminal.permissions.enter_plan_mode()
    assert terminal.core._agent.permission_context.mode.value == "plan"
    terminal.permissions.exit_plan_mode()
    assert terminal.core._agent.permission_context.mode.value == "default"


def test_resume_restores_terminal_theme(terminal):
    terminal.theme.update_theme("nord")
    terminal.save_session()
    session_id = terminal.session_id
    branch = terminal.core._agent.session.fork()
    try:
        terminal.resume_session(branch["session_id"])
        terminal.theme.update_theme("s4")
        terminal.resume_session(session_id)
        assert terminal.settings.ui.theme == "nord"
        assert terminal.settings.product == terminal.core._agent.settings.product
        assert terminal.settings.product is not terminal.core._agent.settings.product
    finally:
        terminal.close()
