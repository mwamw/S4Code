from s4code.runtime_hooks import S4RuntimeNoticeHook


class _DummyAgent:
    def __init__(self, compaction: dict):
        self._compaction = compaction

    def get_context_usage(self):
        return {"last_history_compaction": dict(self._compaction)}


def test_compaction_result_is_emitted_when_nothing_changed() -> None:
    hook = S4RuntimeNoticeHook()
    events = []
    hook.bind_emitter(events.append)

    hook.before_compaction({"operation": "compact_persistent_history_if_needed", "max_tokens": 24000, "force": False})
    hook.flush_compaction_result(
        _DummyAgent(
            {
                "was_compacted": False,
                "compaction_possible": False,
                "tokens_before": 1200,
                "tokens_after": 1200,
                "budget": 24000,
            }
        )
    )

    assert [item["type"] for item in events] == ["compaction_start", "compaction_result"]
    assert events[0]["operation"] == "compact_persistent_history_if_needed"
    assert "not needed" in events[-1]["content"]
    assert hook.has_pending_compactions is False


def test_compaction_result_is_emitted_when_history_changed() -> None:
    hook = S4RuntimeNoticeHook()
    events = []
    hook.bind_emitter(events.append)

    hook.before_compaction({"operation": "compact_persistent_history_if_needed", "max_tokens": 24000, "force": False})
    hook.flush_compaction_result(
        _DummyAgent(
            {
                "was_compacted": True,
                "tokens_before": 25000,
                "tokens_after": 9000,
                "max_tokens": 24000,
            }
        )
    )

    assert [item["type"] for item in events] == ["compaction_start", "compaction_result"]
    assert "25000 -> 9000" in events[-1]["content"]


def test_compaction_result_reports_hook_block() -> None:
    hook = S4RuntimeNoticeHook()
    events = []
    hook.bind_emitter(events.append)

    hook.before_compaction({"operation": "compact_persistent_history_if_needed", "max_tokens": 24000, "force": False})
    hook.flush_compaction_result(
        _DummyAgent(
            {
                "was_compacted": False,
                "compaction_possible": True,
                "budget": 24000,
                "hook_blocked": True,
                "hook_message": "Denied by policy",
            }
        )
    )

    assert [item["type"] for item in events] == ["compaction_start", "compaction_result"]
    assert "blocked" in events[-1]["content"]
    assert "Denied by policy" in events[-1]["content"]
