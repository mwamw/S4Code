"""Textual UI for S4Code."""

from __future__ import annotations

import asyncio
from typing import Any

from rich.box import ROUNDED
from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Input, Static

from .commands import register_builtin_commands
from .query_engine import S4QueryEngine
from .transcript_state import S4TranscriptState, TranscriptCard


class S4TextualApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
        background: transparent;
    }

    VerticalScroll, Vertical, Horizontal, Static, Input {
        background: transparent;
    }

    Header {
        background: transparent;
        color: #e2e8f0;
        text-style: bold;
    }

    Footer {
        background: transparent;
        color: #94a3b8;
    }

    #body {
        height: 1fr;
        background: transparent;
    }

    #main-column {
        width: 1fr;
        background: transparent;
    }

    #transcript {
        height: 1fr;
        border: round #38bdf8;
        background: transparent;
        padding: 0 1;
    }

    #transcript-content {
        background: transparent;
        padding: 1 0;
    }

    #sidebar {
        width: 2fr;
        border: round #475569;
        background: transparent;
        color: #cbd5e1;
        padding: 1 2;
    }

    #command-palette {
        border: round #334155;
        background: transparent;
        min-height: 3;
        max-height: 9;
        padding: 0 1;
    }

    #prompt-input {
        background: transparent;
        border: round #22d3ee;
        color: #e2e8f0;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+l", "clear_log", "Clear Transcript"),
        Binding("down", "command_palette_next", show=False),
        Binding("up", "command_palette_prev", show=False),
        Binding("tab", "command_palette_complete", show=False),
    ]

    def __init__(self, engine: S4QueryEngine):
        super().__init__()
        self.engine = engine
        register_builtin_commands(self.engine.command_registry)
        self._busy = False
        self._transcript_state = S4TranscriptState()
        self._command_matches = []
        self._command_selection_index = 0
        self._query_task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="main-column"):
                with VerticalScroll(id="transcript"):
                    yield Static(id="transcript-content")
                yield Static(id="command-palette")
            yield Static(id="sidebar")
        yield Input(placeholder="Ask S4Code or type /help", id="prompt-input")
        yield Footer()

    def on_mount(self) -> None:
        self._transcript_state.append_card("system", "System", "S4Code ready. Type /help for commands.")
        self._render_transcript()
        self._refresh_command_palette("")
        self._apply_sidebar_visibility()
        self._refresh_sidebar()

    def action_clear_log(self) -> None:
        self._transcript_state.clear()
        self._render_transcript()

    def action_command_palette_next(self) -> None:
        input_widget = self.query_one("#prompt-input", Input)
        if not input_widget.has_focus or not input_widget.value.startswith("/") or not self._command_matches:
            return
        self._command_selection_index = (self._command_selection_index + 1) % len(self._command_matches)
        self._refresh_command_palette(input_widget.value)

    def action_command_palette_prev(self) -> None:
        input_widget = self.query_one("#prompt-input", Input)
        if not input_widget.has_focus or not input_widget.value.startswith("/") or not self._command_matches:
            return
        self._command_selection_index = (self._command_selection_index - 1) % len(self._command_matches)
        self._refresh_command_palette(input_widget.value)

    def action_command_palette_complete(self) -> None:
        input_widget = self.query_one("#prompt-input", Input)
        if not input_widget.has_focus or not input_widget.value.startswith("/") or not self._command_matches:
            return
        selected = self._command_matches[self._command_selection_index]
        current = input_widget.value
        suffix = ""
        if " " in current:
            _, rest = current.split(" ", 1)
            suffix = " " + rest
        input_widget.value = f"/{selected.name}{suffix}"
        try:
            input_widget.cursor_position = len(input_widget.value)
        except Exception:
            pass
        self._refresh_command_palette(input_widget.value)

    @on(Input.Changed, "#prompt-input")
    def handle_input_changed(self, event: Input.Changed) -> None:
        self._refresh_command_palette(event.value)

    @on(Input.Submitted, "#prompt-input")
    async def handle_input(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text or self._busy:
            event.input.value = ""
            return
        event.input.value = ""
        self._refresh_command_palette("")
        self._busy = True
        self._transcript_state.append_card("user", "You", text)
        self._render_transcript()
        self._query_task = asyncio.create_task(self._process_submission(text))

    async def _process_submission(self, text: str) -> None:
        try:
            result = self.engine.command_registry.execute(self.engine, text)
            if result is None:
                await self._run_query(text)
            else:
                if result.message:
                    self._transcript_state.append_card("system", "System", result.message)
                    self._render_transcript()
                    self._apply_sidebar_visibility()
                if result.should_query and result.query:
                    await self._run_query(result.query)
                if result.exit_requested:
                    self.exit()
            self._refresh_sidebar()
        except Exception as exc:
            self._transcript_state.append_card("error", "Error", f"{type(exc).__name__}: {exc}")
            self._render_transcript()
        finally:
            self._busy = False
            self._query_task = None

    async def _run_query(self, prompt: str) -> None:
        async for event in self.engine.stream_prompt(prompt):
            self._render_event(event)

    def _render_event(self, event: dict[str, object]) -> None:
        self._transcript_state.consume_event(dict(event))
        if str(event.get("type") or "") == "final":
            self._refresh_sidebar()
        self._render_transcript()

    def _render_transcript(self) -> None:
        panels = [self._build_panel(card) for card in self._transcript_state.cards]
        content = self.query_one("#transcript-content", Static)
        if panels:
            content.update(Group(*panels))
        else:
            content.update(Text(""))
        try:
            self.query_one("#transcript", VerticalScroll).scroll_end(animate=False)
        except Exception:
            pass

    def _build_panel(self, card: TranscriptCard) -> Panel:
        palette = {
            "system": ("#38bdf8", "#e0f2fe"),
            "user": ("#10b981", "#dcfce7"),
            "assistant": ("#60a5fa", "#dbeafe"),
            "thinking": ("#a78bfa", "#ede9fe"),
            "tool": ("#f59e0b", "#fef3c7"),
            "warning": ("#facc15", "#fef9c3"),
            "error": ("#f87171", "#fee2e2"),
            "round": ("#475569", "#94a3b8"),
        }
        border_style, title_style = palette.get(card.kind, ("#64748b", "#e2e8f0"))
        title = card.title
        if card.status:
            title = f"{title} [{card.status.upper()}]"
        if card.kind == "round":
            return Panel(
                Text(card.title, style="#94a3b8"),
                border_style=border_style,
                title_align="left",
                box=ROUNDED,
                padding=(0, 1),
            )
        return Panel(
            self._render_body(card),
            title=title,
            border_style=border_style,
            title_align="left",
            box=ROUNDED,
            padding=(0, 1),
        )

    def _render_body(self, card: TranscriptCard):
        content = str(card.body or "").strip()
        if not content:
            return Text("")
        if card.kind == "assistant":
            return Markdown(content)
        if card.kind == "thinking":
            return Text(content, style="#c4b5fd")
        if content.startswith("{") and content.endswith("}"):
            try:
                return Syntax(content, "json", theme="monokai", word_wrap=True)
            except Exception:
                return Text(content)
        if "diff --git" in content or content.startswith("--- ") or content.startswith("@@ "):
            return Syntax(content, "diff", theme="monokai", word_wrap=True)
        return Text(content)

    def _refresh_command_palette(self, current_text: str) -> None:
        palette = self.query_one("#command-palette", Static)
        text = str(current_text or "")
        if not text.startswith("/"):
            self._command_matches = []
            self._command_selection_index = 0
            palette.update(
                Panel(
                    Text("Type / to browse commands. Use ↑ ↓ to select and Tab to complete.", style="#94a3b8"),
                    title="Command Palette",
                    border_style="#334155",
                    box=ROUNDED,
                )
            )
            return

        body = text[1:]
        command_fragment = body.split(maxsplit=1)[0].strip().lower() if body.strip() else ""
        self._command_matches = self.engine.command_registry.match_commands(command_fragment)
        if not self._command_matches:
            self._command_selection_index = 0
            palette.update(
                Panel(
                    Text(f"No commands match /{command_fragment}", style="#facc15"),
                    title="Command Palette",
                    border_style="#facc15",
                    box=ROUNDED,
                )
            )
            return

        self._command_selection_index = min(self._command_selection_index, len(self._command_matches) - 1)
        visible_count = 8
        window_start = 0
        if len(self._command_matches) > visible_count:
            half = visible_count // 2
            window_start = max(self._command_selection_index - half, 0)
            max_start = len(self._command_matches) - visible_count
            window_start = min(window_start, max_start)
        visible_matches = self._command_matches[window_start : window_start + visible_count]
        lines: list[Text] = []
        if window_start > 0:
            lines.append(Text(f"... {window_start} earlier command(s)", style="#475569"))
        for offset, command in enumerate(visible_matches):
            index = window_start + offset
            selected = index == self._command_selection_index
            line = Text()
            line.append("› " if selected else "  ", style="#67e8f9" if selected else "#475569")
            line.append(f"/{command.name}", style="#e2e8f0" if selected else "#cbd5e1")
            if command.usage:
                line.append(f" {command.usage}", style="#94a3b8")
            line.append("  ")
            line.append(command.description, style="#94a3b8")
            if command.aliases:
                line.append(f"  aliases: {', '.join('/' + alias for alias in command.aliases)}", style="#64748b")
            lines.append(line)
        remaining = len(self._command_matches) - (window_start + len(visible_matches))
        if remaining > 0:
            lines.append(Text(f"... {remaining} more command(s)", style="#475569"))
        palette.update(
            Panel(
                Group(*lines),
                title=f"Command Palette ({self._command_selection_index + 1}/{len(self._command_matches)})",
                border_style="#22d3ee",
                box=ROUNDED,
            )
        )

    def _refresh_sidebar(self) -> None:
        self.query_one("#sidebar", Static).update(self.engine.format_sidebar())

    def _apply_sidebar_visibility(self) -> None:
        self.query_one("#sidebar", Static).display = bool(getattr(self.engine, "sidebar_visible", False))
