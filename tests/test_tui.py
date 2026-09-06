import asyncio

import pytest


pytest.importorskip("textual")

from rich.console import Group
from rich.markdown import Markdown
from rich.text import Text
from textual.containers import VerticalScroll

from s4code.interfaces.terminal.controller import TerminalController
from s4code.interfaces.terminal.transcript import TranscriptCard
from s4code.interfaces.textual.app import S4TextualApp
from s4code.interfaces.textual.diff_renderer import DiffRenderer


def test_tui_keeps_final_response_top_visible_after_invoke(tmp_path) -> None:
    async def _run() -> None:
        engine = TerminalController(cwd=str(tmp_path))
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
                target_card = app._transcript_state.find_card(target_id)

                assert float(scroll.max_scroll_y) > 0
                assert float(scroll.scroll_y) < float(scroll.max_scroll_y)
                assert target_card is not None
                assert target_card.title == "Model Response"
                assert int(target_widget.region.y) == 0
        finally:
            engine.close()

    asyncio.run(_run())


def test_tui_shows_welcome_card_with_project_context(tmp_path) -> None:
    async def _run() -> None:
        engine = TerminalController(cwd=str(tmp_path))
        app = S4TextualApp(engine)
        try:
            async with app.run_test() as pilot:
                await pilot.pause(0.2)
                first = app._transcript_state.cards[0]
                assert first.title == "Welcome"
                assert f"Project: `{engine.project.project_name}`" in first.body
                assert "/help" in first.body
                assert "/status" in first.body
        finally:
            engine.close()

    asyncio.run(_run())


def test_tui_skips_sidebar_refresh_when_sidebar_hidden(tmp_path) -> None:
    async def _run() -> None:
        engine = TerminalController(cwd=str(tmp_path))
        engine.sidebar_visible = False
        app = S4TextualApp(engine)
        calls = {"count": 0}
        original = engine.status.get_sidebar_payload

        def _wrapped(*, force: bool = False):
            calls["count"] += 1
            return original(force=force)

        engine.status.get_sidebar_payload = _wrapped  # type: ignore[method-assign]
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
        engine = TerminalController(cwd=str(tmp_path))
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
    engine = TerminalController(cwd=str(tmp_path))
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
    engine = TerminalController(cwd=str(tmp_path))
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


def test_tui_renders_assistant_metrics_in_panel_footer(tmp_path) -> None:
    engine = TerminalController(cwd=str(tmp_path))
    app = S4TextualApp(engine)
    try:
        card = TranscriptCard(
            card_id="card-3",
            kind="assistant",
            title="Model Response",
            body="Done.",
            metadata={"footer_left": "Ctx 1,200/24,000  ·  In 210  ·  Out 111  ·  Total 321"},
        )
        panel = app._build_panel(card)
        assert isinstance(panel.renderable, Group)
        footer = panel.renderable.renderables[-1]
        assert isinstance(footer, Text)
        assert "Ctx 1,200/24,000" in footer.plain
        assert "Total 321" in footer.plain
    finally:
        engine.close()


def test_tui_handles_card_removal_without_duplicate_widget_ids(tmp_path) -> None:
    async def _run() -> None:
        engine = TerminalController(cwd=str(tmp_path))
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
    engine = TerminalController(cwd=str(tmp_path))
    engine.mcp.get_mcp_status_payload = lambda **kwargs: [  # type: ignore[method-assign]
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
    engine = TerminalController(cwd=str(tmp_path))
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
    engine = TerminalController(cwd=str(tmp_path))
    engine.mcp.get_mcp_status_payload = lambda **kwargs: [  # type: ignore[method-assign]
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
        engine = TerminalController(cwd=str(tmp_path))
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
        engine = TerminalController(cwd=str(tmp_path))
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


def test_tui_streaming_render_respects_user_scroll_after_snapshot(tmp_path) -> None:
    async def _run() -> None:
        engine = TerminalController(cwd=str(tmp_path))
        app = S4TextualApp(engine)
        try:
            async with app.run_test() as pilot:
                await pilot.pause(0.2)
                for index in range(60):
                    app._transcript_state.append_card("system", "System", f"Line {index}")
                app._render_transcript()
                await pilot.pause(0.2)

                scroll = app.query_one("#transcript", VerticalScroll)
                scroll.scroll_to(y=12, animate=False, immediate=True)
                await pilot.pause(0.1)

                captured: dict[str, object] = {}

                def _defer(callback, *args) -> None:
                    captured["callback"] = callback
                    captured["args"] = args

                app.call_after_refresh = _defer  # type: ignore[method-assign]
                card = app._transcript_state.append_card("assistant", "Model Response", "streaming")
                app._render_transcript()
                await pilot.pause(0.1)
                card.body = "streaming update"
                app._transcript_state._touch(card)
                app._flush_transcript_render()

                scroll.scroll_to(y=3, animate=False, immediate=True)
                await pilot.pause(0.1)

                callback = captured.get("callback")
                args = captured.get("args")
                assert callback is not None
                assert args is not None

                callback(*args)
                await pilot.pause(0.1)

                assert float(scroll.scroll_y) <= 4.0
        finally:
            engine.close()

    asyncio.run(_run())


def test_tui_obsolete_scroll_callback_does_not_touch_new_layout() -> None:
    from types import SimpleNamespace

    def unexpected_query(*args):
        raise AssertionError("An obsolete callback must not inspect the new layout")

    app = SimpleNamespace(_transcript_render_revision=2, query_one=unexpected_query)
    S4TextualApp._restore_transcript_scroll(app, True, True, 0, revision=1)


def test_tui_waits_for_refresh_after_mount_before_reading_layout() -> None:
    from types import SimpleNamespace

    queued, restored = [], []
    app = SimpleNamespace(
        call_after_refresh=lambda callback, *args: queued.append((callback, args)),
        _restore_transcript_scroll=lambda *args: restored.append(args),
    )

    async def check():
        await S4TextualApp._restore_transcript_scroll_after_mount(
            app, asyncio.sleep(0), should_follow=True, forced_follow=False,
            previous_scroll_y=0, target_card_id="final", target_card_top=True, revision=2,
        )
        assert not restored
        assert len(queued) == 1
        callback, args = queued.pop()
        callback(*args)
        assert restored == [(True, False, 0, "final", True, 2)]

    asyncio.run(check())
