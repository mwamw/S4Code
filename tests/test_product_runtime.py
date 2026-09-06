import asyncio
from contextlib import aclosing
from types import SimpleNamespace

import pytest

from test_core_agent import core_agent  # noqa: F401
from s4code.core.application import S4CodeRuntime
from s4code.core.sessions.session import CoreSession
from s4code.sdk import (
    BusyError,
    ClosedError,
    InvalidRequestError,
    S4CodeError,
    RunOptions,
)
from s4code.sdk.client import Sessions


@pytest.fixture
def runtime(core_agent):
    with S4CodeRuntime(
        cwd=core_agent.project.project_root,
        settings=core_agent.settings,
        paths=core_agent.paths,
        session_store=core_agent.session.store,
    ) as value:
        yield value


def test_sdk_session_handles_and_independent_fork(runtime):
    sessions = Sessions(runtime)
    session = sessions.create()
    assert not hasattr(session, "agent")
    session.save(title="source")
    branch = session.fork(title="branch")
    assert branch.id != session.id
    assert session.info().title == "source"
    assert branch.info().forked_from_session_id == session.id
    assert len(sessions.list()) == 2
    branch.close()
    with pytest.raises(ClosedError):
        branch.run("closed")
    assert sessions.resume(branch.id).info().title == "branch"


def test_missing_resume_keeps_live_session(runtime):
    current = runtime.open_session()
    with pytest.raises(InvalidRequestError, match="Session not found"):
        runtime.open_session("missing")
    assert current.info().session_id == current.id


def test_snapshot_validates_owner_version_and_copies(core_agent):
    session = CoreSession(core_agent)
    core_agent.add_user_message("before")
    snapshot = session.export_conversation()
    core_agent.add_user_message("after")
    session.restore_conversation(snapshot)
    assert core_agent.get_history_length() == 1
    bad = snapshot.model_dump()
    bad["session_id"] = "other"
    with pytest.raises(InvalidRequestError):
        session.restore_conversation(bad)
    bad["version"] = 99
    with pytest.raises(InvalidRequestError):
        session.restore_conversation(bad)


def test_extensions_are_copy_isolated(core_agent):
    session = CoreSession(core_agent)
    source = {"items": [1]}
    session.write_extension("ink", source)
    source["items"].append(2)
    saved = session.read_extension("ink")
    saved["items"].append(3)
    assert session.read_extension("ink") == {"items": [1]}


def test_run_results_hide_framework_errors(core_agent, monkeypatch):
    session = CoreSession(core_agent)
    monkeypatch.setattr(core_agent, "invoke", lambda *a, **kw: "hello")
    result = session.run("request", RunOptions(max_iter=2))
    assert result.status == "completed"
    assert result.text == "hello"
    with pytest.raises(InvalidRequestError):
        session.run(" ")

    def fail(*args, **kwargs):
        raise LookupError("provider unavailable")

    monkeypatch.setattr(core_agent, "invoke", fail)
    with pytest.raises(S4CodeError, match="provider unavailable"):
        session.run("request")
    assert session.runs.active_run_id is None


def test_interaction_ids_reject_stale_decisions(core_agent):
    session = CoreSession(core_agent)
    core_agent.interrupt_controller.restore_state(
        {
            "last_tool_interrupt": {
                "tool_name": "Bash",
                "tool_id": "call-1",
                "tool_args": {"command": "echo x"},
                "metadata": {},
            }
        }
    )
    pending = session.pending()
    assert session.pending().interaction_id == pending.interaction_id
    with pytest.raises(InvalidRequestError, match="stale"):
        session.respond("old", action="approve")
    session.respond(pending.interaction_id, action="deny")
    assert session.pending() is None
    with pytest.raises(InvalidRequestError):
        session.respond(pending.interaction_id, action="deny")


def test_stream_closure_releases_runtime(core_agent, monkeypatch):
    from easyagent.runtime import AgentStreamEvent, AgentStreamEventType

    session = CoreSession(core_agent)

    async def source(*args, **kwargs):
        with core_agent.operation():
            yield AgentStreamEvent(AgentStreamEventType.TEXT_DELTA, "a", 1, "hello")
            await asyncio.Event().wait()

    monkeypatch.setattr(core_agent, "astream", source)

    async def check():
        events = session.stream("request")
        event = await anext(events)
        assert event.session_id == session.id
        with pytest.raises(BusyError):
            session.save()
        await events.aclose()
        assert not core_agent.busy
        assert session.runs.active_run_id is None
        assert session.runs.last_result.status == "cancelled"

    asyncio.run(check())


def test_async_sdk_real_executor(core_agent, monkeypatch):
    async def response(request):
        return SimpleNamespace(
            content="SDK response", reasoning_content=None, tool_calls=[], usage=None
        )

    monkeypatch.setattr(core_agent.llm.provider, "async_invoke_raw", response)
    from s4code.sdk.session import AsyncSession

    async def check():
        session = AsyncSession(CoreSession(core_agent), None)
        result = await session.run("hello")
        assert result.text == "SDK response"
        assert result.status == "completed"

    asyncio.run(check())


def test_round_notice_arrives_before_first_token_and_close_cleans_up(
    core_agent, monkeypatch
):
    from easyagent.runtime import RuntimeEvent, RuntimeEventType

    session = CoreSession(core_agent)

    async def source(*args, **kwargs):
        with core_agent.operation():
            core_agent.event_bus.emit(
                RuntimeEvent(RuntimeEventType.LLM_INVOKE_STARTED, "a", "invoke")
            )
            await asyncio.Event().wait()
            yield  # Makes this a stream without ever emitting a token.

    monkeypatch.setattr(core_agent, "astream", source)

    async def check():
        async with aclosing(session.stream("hello")) as events:
            event = await asyncio.wait_for(anext(events), timeout=2)
            assert event.type == "round_start"
            assert event.data == {"round": 1}
        assert not core_agent.busy
        assert session.runs.active_run_id is None
        assert session.runs.last_result.status == "cancelled"
        session.save()

    asyncio.run(check())


def test_invalid_run_options_are_product_errors(core_agent):
    session = CoreSession(core_agent)
    with pytest.raises(InvalidRequestError):
        session.run("hello", {"max_iter": 0})


@pytest.mark.parametrize(
    "topic", ["tool_specs", "mode", "metrics", "skill_sources", "mcp_status"]
)
def test_inspection_is_serializable_and_copy_isolated(core_agent, topic):
    import json

    session = CoreSession(core_agent)
    first = session.inspector.read(topic)
    json.dumps(first, allow_nan=False)
    if isinstance(first, list):
        first.append({"local": "only"})
        assert first != session.inspector.read(topic)


def test_configuration_inspection_redacts_secrets_and_preserves_endpoint(core_agent):
    session = CoreSession(core_agent)
    core_agent.settings.llm.api_key = "do-not-expose"
    core_agent.settings.llm.base_url = (
        "https://user:password@localhost:8443/v1?api_key=secret"
    )
    public = session.inspector.read("configuration")
    assert public["llm"]["api_key"] == "[redacted]"
    assert public["llm"]["base_url"] == "https://localhost:8443/v1"


def test_resume_literal_model_override_is_not_replaced_by_profile(runtime):
    original = runtime.open_session()
    original.save()
    session_id = original.id
    original.close()
    restored = runtime.open_session(
        session_id, overrides={"llm": {"model": "literal-override"}}
    )
    assert restored.info().model == "literal-override"
    assert restored.configuration().llm.model == "literal-override"


def test_resume_profile_selection_supersedes_saved_literal(runtime):
    original = runtime.open_session()
    original.select_model("saved-literal")
    original.save()
    session_id = original.id
    original.close()
    restored = runtime.open_session(
        session_id, overrides={"active_model_profile": "default"}
    )
    assert restored.info().model == "test-model"


def test_open_session_rejects_ignored_options(runtime):
    session = runtime.open_session()
    with pytest.raises(InvalidRequestError, match="already open"):
        runtime.open_session(session.id, overrides={"llm": {"model": "other"}})
