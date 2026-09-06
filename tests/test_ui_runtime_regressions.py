import asyncio
import json
from unittest.mock import Mock

import pytest
from test_core_agent import core_agent  # noqa: F401
from s4code.core.sessions.session import CoreSession
from s4code.core.sessions.snapshots import ConversationSnapshotStore
from s4code.core.observations import RuntimeObservationHook
from s4code.core.errors import InvalidRequestError
from s4code.interfaces.bridge.core_handlers import CoreRequestHandler


def test_observations_only_compute_usage_when_pending():
    hook = RuntimeObservationHook()
    usage = Mock(return_value={})
    emit = Mock()
    hook.bind(emit)
    for _ in range(100):
        hook.flush(usage)
    usage.assert_not_called()
    hook.before_compaction({"max_tokens": 100})
    hook.flush(usage)
    hook.flush(usage)
    usage.assert_called_once()
    assert emit.call_count == 2


def test_stream_deltas_do_not_count_entire_request(core_agent, monkeypatch):
    from easyagent.runtime import AgentStreamEvent, AgentStreamEventType
    session = CoreSession(core_agent)
    count = Mock(side_effect=AssertionError("Per-delta token counting"))
    monkeypatch.setattr(core_agent, "get_context_usage", count)

    async def source(*args, **kwargs):
        for index in range(50):
            yield AgentStreamEvent(AgentStreamEventType.TEXT_DELTA, "test", index, "hello")

    monkeypatch.setattr(core_agent, "astream", source)

    async def consume():
        return [event async for event in session.stream("test")]

    assert len(asyncio.run(consume())) >= 50
    count.assert_not_called()


def test_context_is_cached_between_polls_and_invalidated_by_mutation(core_agent, monkeypatch):
    session = CoreSession(core_agent)
    count = Mock(return_value={"estimatedRequestTokens": 123})
    monkeypatch.setattr(core_agent, "get_context_usage", count)
    assert session.state()["context"]["estimatedRequestTokens"] == 123
    session.state()
    count.assert_called_once()
    session.clear_history()
    session.state()
    assert count.call_count == 2


def test_large_snapshots_are_stored_by_reference_and_survive_reopening(core_agent):
    session = CoreSession(core_agent)
    handler = CoreRequestHandler(session)
    core_agent.add_user_message("large history " + "x" * 600_000)
    ref = handler.handle("core.conversation.capture", {})
    assert len(json.dumps(ref)) < 200
    core_agent.add_user_message("after checkpoint")
    store = ConversationSnapshotStore(core_agent.paths.data_dir / "conversation-snapshots.db")
    assert store.get(session.id, ref["snapshot_id"]).session_id == session.id
    handler.handle("core.conversation.restore_ref", {"snapshot_id": ref["snapshot_id"]})
    assert core_agent.get_history_length() == 1
    with pytest.raises(InvalidRequestError):
        store.get("another-session", ref["snapshot_id"])
    store.delete("another-session", [ref["snapshot_id"]])
    assert store.get(session.id, ref["snapshot_id"])
    handler.handle("core.conversation.delete_snapshots", {"snapshot_ids": [ref["snapshot_id"]]})
    with pytest.raises(InvalidRequestError):
        store.get(session.id, ref["snapshot_id"])


def test_legacy_extension_projection_and_server_side_import(core_agent):
    session = CoreSession(core_agent)
    handler = CoreRequestHandler(session)
    core_agent.add_user_message("legacy " + "x" * 600_000)
    snapshot = session.export_conversation().model_dump()
    session.write_extension("ink", {"checkpoints": [{"checkpoint_id": "old", "snapshot": snapshot}]})
    projected = handler.handle("core.extension.read", {"namespace": "ink", "exclude_fields": ["snapshot"]})
    assert projected == {"checkpoints": [{"checkpoint_id": "old", "snapshot": None}]}
    ref = handler.handle("core.conversation.capture", {"source": {"namespace": "ink", "path": ["checkpoints", 0, "snapshot"], "format": "snapshot"}})
    session.clear_history()
    session.restore_snapshot(ref["snapshot_id"])
    assert core_agent.get_history_length() == 1
    assert session.read_extension("ink")["checkpoints"][0]["snapshot"] == snapshot
