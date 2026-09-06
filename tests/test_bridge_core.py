import asyncio
import pytest
from test_core_agent import core_agent
from test_product_runtime import runtime
from s4code.core.sessions.session import CoreSession
from s4code.interfaces.bridge.core_handlers import CoreRequest, CoreRequestHandler
from s4code.interfaces.bridge.server import BridgeServer


def test_structured_core_operations_without_terminal(core_agent):
    handler = CoreRequestHandler(CoreSession(core_agent))
    state = handler.handle("core.state", {})
    assert state["session_id"] == core_agent.session.session_id
    assert (
        handler.handle("core.model.select", {"target": "default"})["model"]
        == "test-model"
    )
    saved = handler.handle("core.session.save", {"title": "bridge"})
    branch = handler.handle("core.session.fork", {"title": "branch"})
    assert saved["session_id"] != branch["session_id"]
    assert handler.handle("core.state", {})["session_id"] == saved["session_id"]


def test_bridge_rejects_unknown_request(core_agent):
    with pytest.raises(ValueError, match="Unknown Core"):
        CoreRequestHandler(CoreSession(core_agent)).handle("core.unknown", {})
    with pytest.raises(ValueError):
        CoreRequest.model_validate({"request_id": "", "method": "core.state"})


@pytest.mark.parametrize(
    "method,params",
    [
        ("core.model.select", {}),
        ("core.context.compact", {"max_tokens": -1}),
        ("core.state", {"extra": True}),
        ("core.interaction.respond", {"action": "execute"}),
        ("core.inspect", {"topic": "sidebar"}),
    ],
)
def test_core_params_are_validated(core_agent, method, params):
    with pytest.raises(ValueError):
        CoreRequestHandler(CoreSession(core_agent)).handle(method, params)


def test_bridge_stream_no_terminal_checkpoints(runtime, monkeypatch):
    from easyagent.runtime import AgentStreamEvent, AgentStreamEventType

    server = BridgeServer(runtime=runtime, background_streams=False)
    envelopes = []
    monkeypatch.setattr(server, "emit", lambda rid, payload: envelopes.append(payload))

    async def source(*args, **kwargs):
        yield AgentStreamEvent(AgentStreamEventType.FINAL, "native", 1, "hello")

    monkeypatch.setattr(server.session._agent, "astream", source)
    asyncio.run(
        server.dispatch(
            {"request_id": "r", "method": "core.stream", "params": {"prompt": "hello"}}
        )
    )
    assert envelopes[0]["event"]["type"] == "final"
    assert envelopes[-1]["result"]["status"] == "completed"
    assert envelopes[-1]["result"]["text"] == "hello"
    assert server.session.read_extension("terminal") == {}
    assert not hasattr(server, "engine")


def test_bridge_multi_session_and_failed_resume(runtime, monkeypatch):
    server = BridgeServer(runtime=runtime)
    output = []
    monkeypatch.setattr(server, "emit", lambda rid, payload: output.append(payload))

    async def check():
        await server.dispatch(
            {
                "request_id": "init",
                "method": "initialize",
                "params": {"protocol_version": 1},
            }
        )
        assert output[-1]["result"]["protocol_version"] == 1
        await server.dispatch({"request_id": "create", "method": "core.session.create"})
        other = output[-1]["result"]["session_id"]
        assert other != server.session.id
        await server.dispatch(
            {
                "request_id": "mode",
                "method": "core.permissions.mode",
                "params": {"session_id": other, "mode": "default"},
            }
        )
        assert runtime.open_session(other).state()["permission_mode"] == "default"
        with pytest.raises(ValueError, match="Session not found"):
            await server.dispatch(
                {
                    "request_id": "bad",
                    "method": "core.session.open",
                    "params": {"session_id": "missing"},
                }
            )
        assert server.session.info()
        for method in ("execute_command", "render_view", "command_palette"):
            with pytest.raises(ValueError):
                await server.dispatch({"request_id": "legacy", "method": method})

    asyncio.run(check())


def test_bridge_cancel_releases_operation(runtime, monkeypatch):
    from easyagent.runtime import AgentStreamEvent, AgentStreamEventType

    server = BridgeServer(runtime=runtime)
    output = []
    monkeypatch.setattr(
        server, "emit", lambda rid, payload: output.append((rid, payload))
    )

    async def source(*args, **kwargs):
        with server.session._agent.operation():
            yield AgentStreamEvent(AgentStreamEventType.TEXT_DELTA, "a", 1, "hello")
            await asyncio.Event().wait()

    monkeypatch.setattr(server.session._agent, "astream", source)

    async def check():
        await server.dispatch(
            {
                "request_id": "run",
                "method": "core.stream",
                "params": {"prompt": "hello"},
            }
        )
        await asyncio.sleep(0)
        await server.dispatch({"request_id": "stop", "method": "core.stop"})
        assert not server.active_streams
        assert not server.session.state()["busy"]
        assert any(
            rid == "run" and p.get("result", {}).get("status") == "cancelled"
            for rid, p in output
        )
        await server.shutdown()

    asyncio.run(check())


@pytest.mark.parametrize(
    "topic",
    [
        "history",
        "tools",
        "models",
        "permissions",
        "context",
        "trace",
        "cost",
        "restore",
        "skills",
        "tasks",
        "processes",
        "agents",
        "worktree",
        "mcp",
        "hooks",
        "files",
        "diagnostics",
    ],
)
def test_inspection_is_json_serializable(core_agent, topic):
    import json

    core_agent.add_user_message("history text")
    data = CoreSession(core_agent).inspector.read(topic)
    json.dumps(data)
    if topic == "history":
        assert data[0]["text"] == "history text"
