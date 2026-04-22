from s4code.transcript_state import S4TranscriptState


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
        ("thinking", "Model Thinking"),
        ("assistant", "Model Response"),
        ("tool", "Tool · FileRead"),
        ("round", "Cycle 2"),
        ("thinking", "Model Thinking"),
        ("assistant", "Model Response"),
    ]
    assert state.cards[1].body == "I will read the parser."
    assert state.cards[-1].body == "The bug is in empty input handling."


def test_transcript_state_summarizes_tool_result() -> None:
    state = S4TranscriptState()
    state.consume_event({"type": "tool_call", "tool_name": "Bash", "tool_id": "tool-1", "tool_args": {"command": "pytest -q"}})
    state.consume_event({"type": "tool_result", "tool_name": "Bash", "tool_id": "tool-1", "content": "tests passed\nline2\nline3"})

    tool_card = state.cards[0]
    assert tool_card.status == "done"
    assert "... 2 more line(s) hidden" in tool_card.body


def test_transcript_state_tracks_compaction_stage() -> None:
    state = S4TranscriptState()
    state.consume_event({"type": "compaction_start", "content": "Compacting history..."})
    assert state.cards[0].title == "Context Compaction"
    assert state.cards[0].status == "running"

    state.consume_event({"type": "compaction_result", "content": "History compaction finished: 100 -> 40."})
    assert len(state.cards) == 1
    assert state.cards[0].status == "done"
    assert "100 -> 40" in state.cards[0].body


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
    assert "Use /answer <text>" in state.cards[0].body
    assert "Python: Use Python tooling" in state.cards[0].body

    state.consume_event(
        {
            "type": "interaction_resolved",
            "content": "User answered the pending interaction. Resuming execution.",
        }
    )
    assert state.cards[1].title == "Interaction Resolved"
