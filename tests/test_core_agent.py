from pathlib import Path
import pytest
from easyagent import BasicAgent
from s4code.core.agent import S4CodeAgent
from s4code.core.settings import S4AgentSettings, LLMSettings
from s4code.core.paths import S4Paths


@pytest.fixture
def core_agent(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    data = tmp_path / "data"
    paths = S4Paths(
        config_dir=tmp_path / "config",
        data_dir=data,
        cache_dir=tmp_path / "cache",
        global_config_path=tmp_path / "config/config.yaml",
        session_db_path=data / "sessions.db",
        task_db_path=data / "tasks.db",
        agent_storage_dir=data / "agents",
        logs_dir=data / "logs",
    )
    profile = LLMSettings(
        provider="openai",
        model="test-model",
        api_key="test",
        base_url="http://127.0.0.1:1/v1",
        temperature=0.2,
        max_tokens=None,
        timeout=1,
    )
    settings = S4AgentSettings(
        llm=profile,
        model_profiles={"default": profile},
        context={"enabled": False},
        product={
            "enable_codeintel": False,
            "enable_mcp": False,
            "enable_worktree": False,
            "session_auto_save": False,
        },
    )
    agent = S4CodeAgent.create(workspace=root, settings=settings, paths=paths)
    yield agent
    agent.close()


def test_core_is_product_agent(core_agent):
    assert isinstance(core_agent, BasicAgent)
    assert core_agent.tool_registry.has_tool("Bash")
    assert not hasattr(core_agent.settings, "ui")
    assert not hasattr(core_agent, "bundle")


def test_product_prompt_and_builtin_schemas_are_english(core_agent):
    import json
    import re

    prompt = core_agent.get_enhanced_prompt()
    assert prompt.startswith("You are S4Code")
    assert not re.search(r"[\u4e00-\u9fff]", prompt)
    assert core_agent.prompt_composer.include_defaults is False
    for name in core_agent.tool_registry.get_tool_names():
        schema = core_agent.tool_registry.get_tool_spec(name).to_openai_schema()
        assert not re.search(r"[\u4e00-\u9fff]", json.dumps(schema, ensure_ascii=False)), name


def test_legacy_prompt_flag_stays_disabled_after_session_restore(core_agent):
    core_agent.prompt_composer.include_defaults = True
    core_agent.add_user_message("continue the project")
    record = core_agent.session.save(title="legacy prompt flag")
    core_agent.session.restore(record["session_id"])
    assert core_agent.prompt_composer.include_defaults is False
    assert core_agent.get_enhanced_prompt().startswith("You are S4Code")


def test_product_uses_english_history_compaction(core_agent):
    settings = core_agent.settings.model_copy(deep=True)
    settings.context.enabled = True
    settings.context.history_compactor = "llm"
    agent = S4CodeAgent.create(
        workspace=core_agent.project.project_root, settings=settings,
        paths=core_agent.paths, llm=core_agent.llm,
    )
    try:
        assert agent.context_manager.history_compactor.language == "en"
        assert "compaction" in {block.name for block in agent.get_system_prompt_blocks()}
    finally:
        agent.close()


def test_session_roundtrip_and_independent_fork(core_agent):
    agent = core_agent
    agent.add_user_message("original")
    saved = agent.session.save(title="original session")
    branch = agent.session.fork(title="alternative")
    assert branch["session_id"] != saved["session_id"]
    assert agent.session.session_id == saved["session_id"]
    other = S4CodeAgent.from_session(
        branch["session_id"],
        workspace=agent.project.project_root,
        settings=agent.settings,
        paths=agent.paths,
    )
    try:
        assert other.get_history_length() == agent.get_history_length()
        other.add_user_message("branch only")
        assert other.get_history_length() == agent.get_history_length() + 1
        assert other.session.forked_from_session_id == saved["session_id"]
    finally:
        other.close()


def test_conversation_restore(core_agent):
    core_agent.add_user_message("before")
    state = core_agent.export_conversation()
    core_agent.add_user_message("after")
    core_agent.restore_conversation(state)
    assert core_agent.get_history_length() == 1


def test_busy_agent_rejects_mutating_operations(core_agent):
    with core_agent.operation():
        with pytest.raises(RuntimeError, match="busy"):
            core_agent.select_model("default")
        with pytest.raises(RuntimeError, match="busy"):
            core_agent.restore_conversation({"history": {}})
        for operation in (
            core_agent.session.save,
            core_agent.session.autosave,
            core_agent.export_conversation,
            core_agent.clear_history,
        ):
            with pytest.raises(RuntimeError, match="busy"):
                operation()


def test_model_switch_uses_same_product_headers(core_agent):
    previous = core_agent.llm
    core_agent.select_model("default")
    assert core_agent.llm is not previous
    assert core_agent.llm.provider.default_headers["User-Agent"].startswith("S4Code/")


def test_model_switch_updates_runtime_config(core_agent):
    core_agent.settings.model_profiles["alternate"] = (
        core_agent.settings.llm.model_copy(
            update={"model": "other-model", "temperature": 0.8, "max_tokens": 512}
        )
    )
    core_agent.select_model("alternate")
    assert core_agent.config.default_model == "other-model"
    assert core_agent.config.temperature == 0.8
    assert core_agent.config.max_tokens == 512


def test_real_executor_sync_and_async_without_network(core_agent, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    requests = []

    def respond(request):
        requests.append(request)
        return SimpleNamespace(
            content="executor response",
            reasoning_content=None,
            tool_calls=[],
            usage=SimpleNamespace(
                prompt_tokens=8, completion_tokens=2, total_tokens=10
            ),
        )

    async def arespond(request):
        return respond(request)

    monkeypatch.setattr(core_agent.llm.provider, "invoke_raw", respond)
    monkeypatch.setattr(core_agent.llm.provider, "async_invoke_raw", arespond)
    assert core_agent.invoke("sync request") == "executor response"
    assert asyncio.run(core_agent.ainvoke("async request")) == "executor response"
    assert len(requests) == 2
    assert core_agent.get_history_length() == 4
    assert not core_agent.busy


def test_idle_new_agent_does_not_create_session(core_agent):
    session_id, store = core_agent.session.session_id, core_agent.session.store
    core_agent.settings.product.session_auto_save = True
    core_agent.close()
    assert store.get_session(session_id, touch=False) is None


def test_invalid_conversation_is_not_partially_applied(core_agent):
    core_agent.add_user_message("keep me")
    with pytest.raises(ValueError, match="history object"):
        core_agent.restore_conversation({})
    assert core_agent.get_history_length() == 1


def test_permission_operations_persist_and_restore(core_agent):
    from easyagent.permissions import PermissionRule

    core_agent.permissions.set_mode("default")
    core_agent.permissions.add_rule(
        PermissionRule(
            tool_name="Bash",
            behavior="deny",
            matcher={"command_prefixes": ["unsafe-command"]},
        )
    )
    record = core_agent.session.save()
    core_agent.permissions.clear_rules()
    core_agent.permissions.set_mode("accept_edits")
    core_agent.session.restore(record["session_id"])
    assert core_agent.settings.product.permission_mode == "default"
    assert core_agent.permissions.rules()[0]["behavior"] == "deny"


def test_interaction_denial_never_executes_and_cannot_repeat(core_agent, monkeypatch):
    def execute(*args, **kwargs):
        pytest.fail("Denied tool must not execute")

    monkeypatch.setattr(
        core_agent.tool_registry, "execute_confirmed_tool_result", execute
    )
    core_agent.interrupt_controller.restore_state(
        {
            "last_tool_interrupt": {
                "tool_name": "Bash",
                "tool_id": "call-1",
                "tool_args": {"command": "example"},
                "metadata": {},
            }
        }
    )
    with pytest.raises(ValueError, match="approve or deny"):
        core_agent.interactions.respond(action="answer", answer="yes")
    result = core_agent.interactions.respond(action="deny", remember=True)
    assert result["status"] == "resolved"
    assert core_agent.interactions.pending() is None
    assert core_agent.permissions.rules()[0]["matcher"] == {
        "param_equals": {"command": "example"}
    }
    with pytest.raises(ValueError, match="No pending"):
        core_agent.interactions.respond(action="approve")


def test_session_cannot_restore_across_projects(core_agent, tmp_path):
    record = core_agent.session.save()
    other_root = tmp_path / "other"
    other_root.mkdir()
    with pytest.raises(ValueError, match="another project"):
        S4CodeAgent.from_session(
            record["session_id"],
            workspace=other_root,
            settings=core_agent.settings,
            paths=core_agent.paths,
        )


def test_fork_omits_active_runtime_handles_and_terminal_state(core_agent):
    core_agent.session.extensions["terminal"] = {"checkpoints": [{"history": []}]}
    core_agent.current_task_id = "running-task"
    branch = core_agent.session.fork()
    snapshot = branch["snapshot"]
    assert snapshot["currentTaskId"] is None
    assert snapshot["modules"]["executionContext"]["currentTaskId"] is None
    for module in ("multiAgent", "runtimeEvents", "worktree", "interruptions"):
        assert module not in snapshot["modules"]
    assert branch["metadata"]["extensions"] == {}


def test_manual_compaction_respects_framework_hooks(core_agent, monkeypatch):
    from types import SimpleNamespace
    from easyagent import ContextManager
    from easyagent.context import RuleBasedHistoryCompactor

    manager = ContextManager(max_tokens=24000)
    manager.set_history_compactor(
        RuleBasedHistoryCompactor(token_counter=manager.counter, recent_turns=1)
    )
    core_agent.with_context(manager)
    for index in range(4):
        core_agent.add_user_message(f"question {index}")
        core_agent.add_assistant_message("answer " * 100)
    result = core_agent.compact_history()
    assert isinstance(result["was_compacted"], bool)
    assert not core_agent.busy
    previous = core_agent.export_conversation()
    monkeypatch.setattr(
        core_agent.hook_manager,
        "before_compaction",
        lambda payload: SimpleNamespace(blocked=True, payload=payload, audit=[]),
    )
    with pytest.raises(ValueError, match="blocked by a hook"):
        core_agent.compact_history()
    assert core_agent.export_conversation() == previous
