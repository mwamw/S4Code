import asyncio

import pytest


pytest.importorskip("textual")

from rich.markdown import Markdown
from rich.text import Text
from textual.containers import VerticalScroll

from s4code.query_engine import S4QueryEngine
from s4code.transcript_state import TranscriptCard
from s4code.tui import S4TextualApp


def test_tui_keeps_final_response_top_visible_after_invoke(tmp_path) -> None:
    async def _run() -> None:
        engine = S4QueryEngine(cwd=str(tmp_path))
        app = S4TextualApp(engine)
        try:
            async with app.run_test() as pilot:
                await pilot.pause(0.2)
                events = [
                    {"type": "round_start", "round": 1},
                    {"type": "thinking_delta", "delta": "inspect files"},
                    {"type": "tool_call", "tool_name": "Bash", "tool_id": "tool-1", "tool_args": {"command": "pytest -q"}},
                    {"type": "tool_result", "tool_name": "Bash", "tool_id": "tool-1", "content": "ok\nline2"},
                    {"type": "final", "content": "line\n" * 40},
                ]
                for event in events:
                    app._render_event(event)
                app._append_invoke_separator()
                await pilot.pause(0.4)

                scroll = app.query_one("#transcript", VerticalScroll)
                target_id = app._latest_non_separator_card_id()
                assert target_id is not None
                target_widget = app._card_widgets[target_id]

                assert float(scroll.max_scroll_y) > 0
                assert float(scroll.scroll_y) < float(scroll.max_scroll_y)
                assert int(target_widget.region.y) == 0
        finally:
            engine.close()

    asyncio.run(_run())


def test_tui_skips_sidebar_refresh_when_sidebar_hidden(tmp_path) -> None:
    async def _run() -> None:
        engine = S4QueryEngine(cwd=str(tmp_path))
        engine.sidebar_visible = False
        app = S4TextualApp(engine)
        calls = {"count": 0}
        original = engine.format_sidebar

        def _wrapped(*, force: bool = False) -> str:
            calls["count"] += 1
            return original(force=force)

        engine.format_sidebar = _wrapped  # type: ignore[method-assign]
        try:
            async with app.run_test() as pilot:
                await pilot.pause(0.2)
                app._refresh_sidebar(force=True)
                await pilot.pause(0.1)
                assert calls["count"] == 0

                engine.sidebar_visible = True
                app._apply_sidebar_visibility()
                app._refresh_sidebar(force=True)
                await pilot.pause(0.1)
                assert calls["count"] == 1
        finally:
            engine.close()

    asyncio.run(_run())


def test_tui_compacts_older_cards_for_long_transcripts(tmp_path) -> None:
    async def _run() -> None:
        engine = S4QueryEngine(cwd=str(tmp_path))
        app = S4TextualApp(engine)
        try:
            async with app.run_test() as pilot:
                await pilot.pause(0.2)
                for index in range(75):
                    app._transcript_state.append_card(
                        "assistant",
                        "Model Response",
                        f"Card {index}\n" + ("detail " * 40),
                    )
                app._render_transcript()
                await pilot.pause(0.3)

                assert app._compact_card_ids
                oldest = app._transcript_state.cards[0]
                newest = app._transcript_state.cards[-1]
                assert oldest.card_id in app._compact_card_ids
                assert newest.card_id not in app._compact_card_ids
        finally:
            engine.close()

    asyncio.run(_run())


def test_tui_renders_streaming_assistant_as_markdown(tmp_path) -> None:
    engine = S4QueryEngine(cwd=str(tmp_path))
    app = S4TextualApp(engine)
    try:
        card = TranscriptCard(
            card_id="card-1",
            kind="assistant",
            title="Model Response",
            body="**bold**\n\n- item",
            status="streaming",
        )
        renderable = app._render_body(card)
        assert isinstance(renderable, Markdown)
    finally:
        engine.close()


def test_tui_renders_plain_streaming_assistant_as_text(tmp_path) -> None:
    engine = S4QueryEngine(cwd=str(tmp_path))
    app = S4TextualApp(engine)
    try:
        card = TranscriptCard(
            card_id="card-2",
            kind="assistant",
            title="Model Response",
            body="plain streaming text",
            status="streaming",
        )
        renderable = app._render_body(card)
        assert isinstance(renderable, Text)
    finally:
        engine.close()


def test_tui_handles_card_removal_without_duplicate_widget_ids(tmp_path) -> None:
    async def _run() -> None:
        engine = S4QueryEngine(cwd=str(tmp_path))
        app = S4TextualApp(engine)
        try:
            async with app.run_test() as pilot:
                await pilot.pause(0.2)
                app._render_event({"type": "compaction_start", "content": "Compacting history..."})
                await pilot.pause(0.1)
                app._render_event(
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
                await pilot.pause(0.1)
                app._transcript_state.append_card("system", "System", "Recovered")
                app._render_transcript()
                await pilot.pause(0.2)

                assert len(app._card_widgets) == len(app._transcript_state.cards)
                assert all(card.card_id in app._card_widgets for card in app._transcript_state.cards)
        finally:
            engine.close()

    asyncio.run(_run())


def test_tui_builds_second_level_mcp_palette_entries(tmp_path) -> None:
    engine = S4QueryEngine(cwd=str(tmp_path))
    engine.get_mcp_status_payload = lambda **kwargs: [  # type: ignore[method-assign]
        {
            "server_name": "github",
            "status": "connected",
            "transport_summary": "stdio | node",
            "last_error": "",
        },
        {
            "server_name": "filesystem",
            "status": "unregistered",
            "transport_summary": "stdio | python",
            "last_error": "missing binary",
        },
    ]
    app = S4TextualApp(engine)
    try:
        entries, _ = app._build_palette_entries("/mcp status ")
        labels = [entry.label for entry in entries]
        execute_texts = [entry.execute_text for entry in entries]
        assert "* github" in labels
        assert "filesystem" in labels
        assert "/mcp status github" in execute_texts
        assert "/mcp status filesystem" in execute_texts
    finally:
        engine.close()


def test_tui_builds_secondary_palette_entries_for_finite_option_commands(tmp_path) -> None:
    engine = S4QueryEngine(cwd=str(tmp_path))
    app = S4TextualApp(engine)
    try:
        entries, _ = app._build_palette_entries("/plan ")
        assert {entry.execute_text for entry in entries} == {"/plan on", "/plan off"}

        entries, _ = app._build_palette_entries("/copy ")
        assert {entry.execute_text for entry in entries} == {"/copy transcript", "/copy last"}

        entries, _ = app._build_palette_entries("/sidebar ")
        assert {entry.execute_text for entry in entries} == {"/sidebar show", "/sidebar hide"}

        entries, _ = app._build_palette_entries("/permissions clear ")
        assert {entry.execute_text for entry in entries} == {
            "/permissions clear session",
            "/permissions clear all",
        }
    finally:
        engine.close()


def test_tui_builds_mcp_all_entries_for_global_actions(tmp_path) -> None:
    engine = S4QueryEngine(cwd=str(tmp_path))
    engine.get_mcp_status_payload = lambda **kwargs: [  # type: ignore[method-assign]
        {
            "server_name": "github",
            "status": "connected",
            "transport_summary": "stdio | node",
            "last_error": "",
        }
    ]
    app = S4TextualApp(engine)
    try:
        entries, _ = app._build_palette_entries("/mcp refresh ")
        execute_texts = [entry.execute_text for entry in entries]
        assert "/mcp refresh" in execute_texts
        assert "/mcp refresh github" in execute_texts
    finally:
        engine.close()


def test_tui_command_output_scrolls_to_bottom(tmp_path) -> None:
    async def _run() -> None:
        engine = S4QueryEngine(cwd=str(tmp_path))
        app = S4TextualApp(engine)
        try:
            async with app.run_test() as pilot:
                await pilot.pause(0.2)
                for index in range(40):
                    app._transcript_state.append_card("system", "System", f"Line {index}")
                app._render_transcript()
                await pilot.pause(0.2)

                scroll = app.query_one("#transcript", VerticalScroll)
                scroll.scroll_to(y=0, animate=False, immediate=True)
                await pilot.pause(0.1)

                await app._process_submission("/status")
                await pilot.pause(0.2)

                assert float(scroll.scroll_y) >= float(scroll.max_scroll_y)
        finally:
            engine.close()

    asyncio.run(_run())


def test_tui_copy_command_scrolls_to_bottom(tmp_path) -> None:
    async def _run() -> None:
        engine = S4QueryEngine(cwd=str(tmp_path))
        app = S4TextualApp(engine)
        try:
            async with app.run_test() as pilot:
                await pilot.pause(0.2)
                for index in range(40):
                    app._transcript_state.append_card("system", "System", f"Line {index}")
                app._render_transcript()
                await pilot.pause(0.2)

                scroll = app.query_one("#transcript", VerticalScroll)
                scroll.scroll_to(y=0, animate=False, immediate=True)
                await pilot.pause(0.1)

                await app._process_submission("/copy transcript")
                await pilot.pause(0.2)

                assert float(scroll.scroll_y) >= float(scroll.max_scroll_y)
        finally:
            engine.close()

    asyncio.run(_run())
