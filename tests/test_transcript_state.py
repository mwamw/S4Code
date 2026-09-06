from s4code.interfaces.terminal.transcript import S4TranscriptState


def _find_card(state: S4TranscriptState, kind: str, title: str | None = None):
    for card in state.cards:
        if card.kind != kind:
            continue
        if title is not None and card.title != title:
            continue
        return card
    raise AssertionError(f"card not found: kind={kind!r} title={title!r}")


def test_transcript_state_keeps_round_order() -> None:
    state = S4TranscriptState()

    events = [
        {"type": "round_start", "round": 1},
        {"type": "thinking_delta", "delta": "inspect files"},
        {"type": "text_delta", "delta": "I will read the parser."},
        {"type": "tool_call", "tool_name": "FileRead", "tool_id": "tool-1", "tool_args": {"file_path": "parser.py"}},
        {"type": "tool_result", "tool_name": "FileRead", "tool_id": "tool-1", "content": "Read parser.py successfully\nline 2"},
        {"type": "round_start", "round": 2},
        {"type": "thinking_delta", "delta": "apply fix"},
        {"type": "text_delta", "delta": "The bug is in empty input handling."},
        {"type": "final", "content": "The bug is in empty input handling."},
    ]

    for event in events:
        state.consume_event(event)

    pairs = [(card.kind, card.title) for card in state.cards]
    assert pairs == [
        ("round", "Cycle 1"),
        ("thinking", "Model Thinking"),
        ("assistant", "Model Response"),
        ("tool", "Tool · FileRead"),
        ("round", "Cycle 2"),
        ("thinking", "Model Thinking"),
        ("assistant", "Model Response"),
        ("system", "Round Outcome"),
    ]
    assert state.cards[2].body == "I will read the parser."
    assert state.cards[6].body == "The bug is in empty input handling."
    assert state.cards[7].body.startswith("Round 2 finished.")
    assert state.cards[0].body.startswith("Completed in ")
    assert state.cards[4].body.startswith("Completed in ")


def test_transcript_state_tracks_dirty_cards_and_index_lookups() -> None:
    state = S4TranscriptState()
    system = state.append_card("system", "System", "Ready")
    user = state.append_card("user", "You", "Fix the bug")

    assert state.find_card(system.card_id) is system
    assert state.find_card(user.card_id) is user
    assert state.consume_dirty_card_ids() == {system.card_id, user.card_id}
    assert state.consume_dirty_card_ids() == set()

    state.consume_event({"type": "round_start", "round": 1})
    round_card = _find_card(state, "round", "Cycle 1")
    assert state.find_card(round_card.card_id) is round_card
    assert state.consume_dirty_card_ids() == {round_card.card_id}

    state.consume_event({"type": "text_delta", "delta": "Working..."})
    assistant = _find_card(state, "assistant", "Model Response")
    assert state.consume_dirty_card_ids() == {assistant.card_id}

    state.clear()
    assert state.find_card(system.card_id) is None
    assert state.consume_dirty_card_ids() == set()


def test_transcript_state_updates_round_elapsed_until_completion() -> None:
    current_time = 100.0

    def _clock() -> float:
        return current_time

    state = S4TranscriptState(clock=_clock)
    state.consume_event({"type": "round_start", "round": 1})

    assert state.cards[0].body == "Elapsed: 0.0s"
    assert state.has_live_round() is True

    current_time = 101.4
    assert state.refresh_round_timers() is True
    assert state.cards[0].body == "Elapsed: 1.4s"

    current_time = 103.0
    state.consume_event({"type": "round_start", "round": 2})

    assert state.cards[0].body == "Completed in 3.0s"
    assert state.cards[1].title == "Cycle 2"
    assert state.cards[1].body == "Elapsed: 0.0s"


def test_transcript_state_summarizes_tool_result() -> None:
    state = S4TranscriptState()
    state.consume_event({"type": "tool_call", "tool_name": "Bash", "tool_id": "tool-1", "tool_args": {"command": "pytest -q"}})
    state.consume_event({"type": "tool_result", "tool_name": "Bash", "tool_id": "tool-1", "content": "tests passed\nline2\nline3"})

    tool_card = _find_card(state, "tool", "Tool · Bash")
    assert tool_card.status == "done"
    assert "... 2 more line(s) hidden" in tool_card.body


def test_transcript_state_formats_background_task_result_with_next_steps() -> None:
    state = S4TranscriptState()
    state.consume_event(
        {
            "type": "tool_call",
            "tool_name": "Bash",
            "tool_id": "tool-1",
            "tool_args": {"command": "pytest -q", "run_in_background": True},
        }
    )
    state.consume_event(
        {
            "type": "tool_result",
            "tool_name": "Bash",
            "tool_id": "tool-1",
            "content": "任务 ID: task-1",
            "structured_data": {
                "task_id": "task-1",
                "status": "running",
                "command": "pytest -q",
            },
        }
    )

    tool_card = _find_card(state, "tool", "Tool · Bash")
    assert "Started background task `task-1`." in tool_card.body
    assert "/task output task-1" in tool_card.body
    assert "/task stop task-1" in tool_card.body


def test_transcript_state_preserves_file_diff_metadata() -> None:
    state = S4TranscriptState()
    state.consume_event(
        {
            "type": "tool_call",
            "tool_name": "FileEdit",
            "tool_id": "tool-1",
            "tool_args": {"file_path": "src/app.py"},
        }
    )
    state.consume_event(
        {
            "type": "tool_result",
            "tool_name": "FileEdit",
            "tool_id": "tool-1",
            "content": "已更新文件: /tmp/src/app.py (替换 1 处匹配)",
            "status": "success",
            "structured_data": {
                "file_path": "/tmp/src/app.py",
                "diff": {
                    "file_path": "/tmp/src/app.py",
                    "relative_path": "src/app.py",
                    "created": False,
                    "unified": (
                        "diff --git a/src/app.py b/src/app.py\n"
                        "--- a/src/app.py\n"
                        "+++ b/src/app.py\n"
                        "@@ -1 +1 @@\n"
                        "-print('old')\n"
                        "+print('new')"
                    ),
                },
            },
        }
    )

    tool_card = _find_card(state, "tool", "Tool · FileEdit")
    assert tool_card.status == "done"
    assert tool_card.metadata["diff"]["relative_path"] == "src/app.py"
    assert "+print('new')" in tool_card.metadata["diff"]["unified"]


def test_transcript_state_updates_runtime_snapshot_card_in_place() -> None:
    state = S4TranscriptState()

    state.consume_event(
        {
            "type": "runtime_snapshot",
            "snapshot": {
                "generated_at": "2026-04-23T10:00:00",
                "session": {"session_id": "sess-1", "checkpoints": 1},
                "worktree": {"active": None},
                "agents": [],
                "tasks": [],
                "background_tasks": [
                    {
                        "task_id": "task-1",
                        "status": "running",
                        "return_code": None,
                        "command": "pytest -q",
                        "duration_seconds": 1.2,
                        "stdout_tail": "collecting",
                    }
                ],
                "context": {"used_tokens": 10, "remaining_tokens": 90, "max_tokens": 100},
            },
        }
    )
    state.consume_event(
        {
            "type": "runtime_snapshot",
            "snapshot": {
                "generated_at": "2026-04-23T10:00:02",
                "session": {"session_id": "sess-1", "checkpoints": 2},
                "worktree": {"active": {"branch": "feature", "path": "/tmp/repo"}},
                "agents": [{"agent_id": "agent-1", "status": "running", "name": "worker"}],
                "tasks": [],
                "background_tasks": [],
                "context": {"used_tokens": 20, "remaining_tokens": 80, "max_tokens": 100},
            },
        }
    )

    runtime_cards = [card for card in state.cards if card.kind == "runtime"]
    assert len(runtime_cards) == 1
    assert "2026-04-23T10:00:02" in runtime_cards[0].body
    assert "agent-1" in runtime_cards[0].body
    assert "checkpoints=2" in runtime_cards[0].body


def test_transcript_state_attaches_checkpoints_to_message_cards() -> None:
    state = S4TranscriptState()
    user = state.append_card("user", "You", "Fix the bug")

    state.consume_event(
        {
            "type": "checkpoint",
            "checkpoint": {
                "checkpoint_id": "cp-001",
                "label": "before turn",
                "reason": "before_prompt",
                "history_messages": 3,
                "created_at": "2026-04-23T10:00:00",
            },
        }
    )

    assert len(state.cards) == 1
    assert user.metadata["checkpoints"][0]["checkpoint_id"] == "cp-001"
    assert user.metadata["checkpoints"][0]["history_messages"] == 3

    state.consume_event({"type": "round_start", "round": 1})
    state.consume_event({"type": "final", "content": "Done"})
    state.consume_event(
        {
            "type": "checkpoint",
            "checkpoint": {
                "checkpoint_id": "cp-002",
                "label": "after turn",
                "reason": "after_prompt",
                "history_messages": 5,
                "created_at": "2026-04-23T10:00:05",
            },
        }
    )

    assistant = _find_card(state, "assistant", "Model Response")
    assert assistant.metadata["checkpoints"][0]["checkpoint_id"] == "cp-002"


def test_transcript_state_marks_cancelled_round_as_interrupted() -> None:
    state = S4TranscriptState()
    state.consume_event({"type": "round_start", "round": 1})

    state.consume_event({"type": "cancelled", "content": "Agent execution interrupted by Esc."})

    round_card = _find_card(state, "round", "Cycle 1")
    warning = _find_card(state, "warning", "Interrupted")
    assert round_card.body.startswith("Interrupted in ")
    assert warning.body == "Agent execution interrupted by Esc."
    assert state.has_live_round() is False


def test_transcript_state_tracks_compaction_stage() -> None:
    state = S4TranscriptState()
    state.consume_event({"type": "compaction_start", "content": "Compacting history..."})
    assert state.cards[0].title == "Context Compaction"
    assert state.cards[0].status == "running"

    state.consume_event(
        {
            "type": "compaction_result",
            "content": "History compaction finished: 100 -> 40.",
            "compaction": {
                "was_compacted": True,
                "tokens_before": 100,
                "tokens_after": 40,
                "budget": 24000,
            },
        }
    )
    assert len(state.cards) == 1
    assert state.cards[0].status == "done"
    assert "100 -> 40" in state.cards[0].body


def test_transcript_state_hides_noop_compaction_card() -> None:
    state = S4TranscriptState()
    state.consume_event({"type": "compaction_start", "content": "Compacting history..."})

    state.consume_event(
        {
            "type": "compaction_result",
            "content": "History compaction not needed.",
            "compaction": {
                "was_compacted": False,
                "compaction_possible": False,
                "tokens_before": 1200,
                "tokens_after": 1200,
                "budget": 24000,
            },
        }
    )

    assert state.cards == []


def test_transcript_state_clears_streaming_status_on_round_finalize() -> None:
    state = S4TranscriptState()
    state.consume_event({"type": "round_start", "round": 1})
    state.consume_event({"type": "thinking_delta", "delta": "inspect"})
    state.consume_event({"type": "text_delta", "delta": "partial reply"})

    state.consume_event({"type": "round_start", "round": 2})

    thinking_cards = [card for card in state.cards if card.kind == "thinking"]
    assistant_cards = [card for card in state.cards if card.kind == "assistant"]
    assert len(thinking_cards) == 1
    assert len(assistant_cards) == 1
    assert thinking_cards[0].status is None
    assert assistant_cards[0].status is None


def test_transcript_state_compaction_before_final_does_not_create_extra_response_card() -> None:
    state = S4TranscriptState()
    state.consume_event({"type": "round_start", "round": 1})
    state.consume_event({"type": "text_delta", "delta": "**partial"})
    state.consume_event({"type": "compaction_start", "content": "Compacting history..."})
    state.consume_event(
        {
            "type": "compaction_result",
            "content": "History compaction finished: 300 -> 120.",
            "compaction": {
                "was_compacted": True,
                "tokens_before": 300,
                "tokens_after": 120,
                "budget": 24000,
            },
        }
    )
    state.consume_event({"type": "final", "content": "**partial**"})

    round_cards = [card for card in state.cards if card.kind == "round"]
    assistant_cards = [card for card in state.cards if card.kind == "assistant"]
    assert len(round_cards) == 1
    assert len(assistant_cards) == 1
    assert assistant_cards[0].body == "**partial**"


def test_transcript_state_formats_pending_interaction_and_resolution() -> None:
    state = S4TranscriptState()
    state.consume_event(
        {
            "type": "interruption",
            "content": "需要用户回答 1 个结构化问题后才能继续执行。",
            "payload": {
                "message": "需要用户回答 1 个结构化问题后才能继续执行。",
                "metadata": {
                    "interaction_type": "ask_user_question",
                    "questions": [
                        {
                            "header": "Language",
                            "question": "Choose one",
                            "options": [
                                {"label": "Python", "description": "Use Python tooling"},
                                {"label": "Go", "description": "Use Go tooling"},
                            ],
                        }
                    ],
                },
            },
        }
    )
    assert state.cards[0].title == "Ask User Question"
    assert state.cards[0].status == "pending"
    assert "1. Language" in state.cards[0].body
    assert "The agent needs your answer before it can continue." in state.cards[0].body
    assert "Use `/answer <text>` to continue." in state.cards[0].body
    assert "Python: Use Python tooling" in state.cards[0].body

    state.consume_event(
        {
            "type": "interaction_resolved",
            "content": "User answered the pending interaction. Resuming execution.",
        }
    )
    assert state.cards[1].title == "Interaction Resolved"


def test_transcript_state_merges_round_metrics_while_running_and_after_completion() -> None:
    current_time = 50.0

    def _clock() -> float:
        return current_time

    state = S4TranscriptState(clock=_clock)
    state.consume_event({"type": "round_start", "round": 1})
    state.consume_event({"type": "text_delta", "delta": "working"})
    state.consume_event({"type": "tool_call", "tool_name": "FileEdit", "tool_id": "tool-1", "tool_args": {"file_path": "src/app.py"}})
    state.consume_event(
        {
            "type": "tool_result",
            "tool_name": "FileEdit",
            "tool_id": "tool-1",
            "content": "updated",
            "structured_data": {
                "diff": {
                    "relative_path": "src/app.py",
                    "unified": "@@ -1 +1 @@\n-old\n+new",
                }
            },
        }
    )
    state.consume_event(
        {
            "type": "round_metrics",
            "round": 1,
            "metrics": {
                "tool_calls": 1,
                "llm_duration_ms": 1200,
                "tool_duration_ms": 450,
                "input_tokens": 210,
                "output_tokens": 111,
                "total_tokens": 321,
                "estimated_cost_usd": 0.0123,
                "context_used_tokens": 1200,
                "context_max_tokens": 24000,
                "prompt_tokens_total": 180,
                "prompt_tokens_cached": 72,
                "files_changed": ["src/app.py"],
            },
        }
    )

    round_card = _find_card(state, "round", "Cycle 1")
    assistant_card = _find_card(state, "assistant", "Model Response")
    assert "Elapsed: 0.0s" in round_card.body
    assert "Tools 1" in round_card.body
    assert "Model 1.2s" in round_card.body
    assert "Tool 0.5s" in round_card.body
    assert "Files 1" in round_card.body
    assert "Used: FileEdit" in round_card.body
    assert "Changed: src/app.py" in round_card.body
    assert "Tokens 321" not in round_card.body
    assert "Cost $0.0123" not in round_card.body
    assert "Context:" not in round_card.body
    assert "Cache:" not in round_card.body
    assert assistant_card.metadata["footer_left"] == (
        "Ctx 1,200/24,000  ·  In 210  ·  Out 111  ·  Total 321  ·  Cache 72/180  ·  Cost $0.0123"
    )

    current_time = 52.0
    state.consume_event({"type": "final", "content": "done"})

    round_card = _find_card(state, "round", "Cycle 1")
    assistant_card = _find_card(state, "assistant", "Model Response")
    assert round_card.body.startswith("Completed in 2.0s")
    assert "Model 1.2s" in round_card.body
    assert "Tool 0.5s" in round_card.body
    assert "Changed: src/app.py" in round_card.body
    assert assistant_card.metadata["footer_left"].endswith("Cost $0.0123")


def test_transcript_state_formats_structured_provider_error() -> None:
    state = S4TranscriptState()
    state.consume_event({"type": "round_start", "round": 1})
    state.consume_event(
        {
            "type": "error",
            "error": "Your request was blocked.",
            "error_type": "PermissionDeniedError",
            "status_code": 403,
            "provider": "openai",
            "model": "deepseek-v4-flash-0731",
            "endpoint": "https://example.com/v1",
            "edge_trace_id": "edge-456",
        }
    )

    card = _find_card(state, "error", "Error · PermissionDeniedError")
    assert card.status == "error"
    assert "Your request was blocked." in card.body
    assert "HTTP status: 403" in card.body
    assert "Provider: openai" in card.body
    assert "Model: deepseek-v4-flash-0731" in card.body
    assert "Endpoint: https://example.com/v1" in card.body
    assert "Edge trace: edge-456" in card.body
    assert card.metadata["status_code"] == 403


def test_transcript_state_does_not_create_cards_for_whitespace_only_deltas() -> None:
    state = S4TranscriptState()
    state.consume_event({"type": "round_start", "round": 1})

    state.consume_event({"type": "thinking_delta", "delta": "\n\n"})
    state.consume_event({"type": "text_delta", "delta": "\n\n"})
    state.consume_event(
        {"type": "tool_call", "tool_name": "List", "tool_id": "tool-1", "tool_args": {"path": "."}}
    )

    assert [card.kind for card in state.cards] == ["round", "tool"]


def test_transcript_state_keeps_whitespace_after_visible_text_starts() -> None:
    state = S4TranscriptState()
    state.consume_event({"type": "round_start", "round": 1})

    state.consume_event({"type": "text_delta", "delta": "Answer"})
    state.consume_event({"type": "text_delta", "delta": "\n\n"})
    state.consume_event({"type": "text_delta", "delta": "Details"})

    assistant = _find_card(state, "assistant", "Model Response")
    assert assistant.body == "Answer\n\nDetails"


def test_transcript_state_empty_final_still_finishes_round() -> None:
    state = S4TranscriptState()
    state.consume_event({"type": "round_start", "round": 1})

    state.consume_event({"type": "final", "content": "\n\n"})

    assert state.has_live_round() is False
    assert [card.kind for card in state.cards] == ["round"]
