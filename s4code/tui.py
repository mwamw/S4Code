"""Textual UI for S4Code."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from typing import Any, Optional

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


@dataclass(slots=True)
class DiffHunk:
    header: str
    lines: tuple[str, ...]


@dataclass(slots=True)
class ParsedUnifiedDiff:
    prelude: tuple[str, ...]
    hunks: tuple[DiffHunk, ...]


@dataclass(slots=True)
class PaletteEntry:
    label: str
    description: str
    insert_text: str
    execute_text: str
    mode: str = "insert"
    aliases: tuple[str, ...] = ()


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
        max-height: 11;
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
        Binding("ctrl+shift+c", "copy_transcript", "Copy Transcript"),
        Binding("ctrl+alt+c", "copy_last_card", "Copy Last Card"),
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
        self._palette_entries: list[PaletteEntry] = []
        self._command_selection_index = 0
        self._palette_state_key = ""
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
        for notice in self.engine.get_startup_notices():
            self._transcript_state.append_card(
                str(notice.get("kind") or "system"),
                str(notice.get("title") or "Notice"),
                str(notice.get("body") or "").strip(),
            )
        pending = self.engine.get_pending_interaction()
        if pending is not None:
            self._transcript_state.consume_event(
                {
                    "type": "interruption",
                    "content": pending.get("message") or "A pending interaction was restored with this session.",
                    "payload": pending,
                }
            )
        self._render_transcript()
        self._refresh_command_palette("")
        self._apply_sidebar_visibility()
        self._refresh_sidebar()
        self.set_interval(0.2, self._refresh_live_rounds)

    def action_clear_log(self) -> None:
        self._transcript_state.clear()
        self._render_transcript()

    def action_copy_transcript(self) -> None:
        self._copy_to_clipboard(self._build_transcript_plain_text(), success_message="Transcript copied.")

    def action_copy_last_card(self) -> None:
        text = self._build_last_card_plain_text()
        if not text:
            self._transcript_state.append_card("system", "Notice", "Nothing to copy yet.")
            self._render_transcript()
            return
        self._copy_to_clipboard(text, success_message="Latest card copied.")

    def action_command_palette_next(self) -> None:
        input_widget = self.query_one("#prompt-input", Input)
        if not input_widget.has_focus or not input_widget.value.startswith("/") or not self._palette_entries:
            return
        self._command_selection_index = (self._command_selection_index + 1) % len(self._palette_entries)
        self._refresh_command_palette(input_widget.value)

    def action_command_palette_prev(self) -> None:
        input_widget = self.query_one("#prompt-input", Input)
        if not input_widget.has_focus or not input_widget.value.startswith("/") or not self._palette_entries:
            return
        self._command_selection_index = (self._command_selection_index - 1) % len(self._palette_entries)
        self._refresh_command_palette(input_widget.value)

    def action_command_palette_complete(self) -> None:
        input_widget = self.query_one("#prompt-input", Input)
        if not input_widget.has_focus or not input_widget.value.startswith("/") or not self._palette_entries:
            return
        self._apply_palette_entry(self._palette_entries[self._command_selection_index], execute=False)

    @on(Input.Changed, "#prompt-input")
    def handle_input_changed(self, event: Input.Changed) -> None:
        self._refresh_command_palette(event.value)

    @on(Input.Submitted, "#prompt-input")
    async def handle_input(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text or self._busy:
            event.input.value = ""
            return
        palette_resolution = self._resolve_palette_submit(text)
        if palette_resolution is not None:
            mode, value = palette_resolution
            if mode == "insert":
                event.input.value = value
                try:
                    event.input.cursor_position = len(value)
                except Exception:
                    pass
                event.input.focus()
                self._refresh_command_palette(value)
                return
            text = value
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
                ui_action = str(result.metadata.get("ui_action") or "")
                if ui_action == "copy_to_clipboard":
                    self._handle_copy_action(str(result.metadata.get("copy_target") or "transcript"))
                if result.message:
                    self._transcript_state.append_card("system", "System", result.message)
                    self._render_transcript()
                    self._apply_sidebar_visibility()
                engine_action = str(result.metadata.get("engine_action") or "")
                if engine_action == "confirm_pending":
                    await self._run_pending_resolution("approve", str(result.metadata.get("answer") or ""))
                elif engine_action == "deny_pending":
                    await self._run_pending_resolution("deny", str(result.metadata.get("answer") or ""))
                elif engine_action == "answer_pending":
                    await self._run_pending_resolution("answer", str(result.metadata.get("answer") or ""))
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

    async def _run_pending_resolution(self, action: str, answer: str = "") -> None:
        async for event in self.engine.stream_resolve_pending_interaction(
            action=action,
            answer=answer,
        ):
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

    def _refresh_live_rounds(self) -> None:
        if self._busy and self._transcript_state.refresh_round_timers():
            self._render_transcript()

    def _build_panel(self, card: TranscriptCard) -> Panel:
        palette = {
            "system": ("#fb923c", "#ffedd5"),
            "user": ("#10b981", "#dcfce7"),
            "assistant": ("#60a5fa", "#dbeafe"),
            "thinking": ("#a78bfa", "#ede9fe"),
            "tool": ("#f59e0b", "#fef3c7"),
            "warning": ("#facc15", "#fef9c3"),
            "error": ("#f87171", "#fee2e2"),
            "round": ("#475569", "#94a3b8"),
        }
        border_style, _title_style = palette.get(card.kind, ("#64748b", "#e2e8f0"))
        title = card.title
        if card.status:
            title = f"{title} [{card.status.upper()}]"
        if card.kind == "round":
            return Panel(
                Text(card.body or card.title, style="#94a3b8"),
                title=card.title,
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
        diff_payload = self._extract_diff_payload(card)
        if diff_payload is not None:
            return self._render_diff_body(card, diff_payload)
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

    @staticmethod
    def _extract_diff_payload(card: TranscriptCard) -> Optional[dict[str, Any]]:
        payload = card.metadata.get("diff")
        if not isinstance(payload, dict):
            return None
        unified = str(payload.get("unified") or "").strip()
        if not unified:
            return None
        return payload

    @staticmethod
    def _parse_unified_diff(diff_text: str) -> ParsedUnifiedDiff:
        prelude: list[str] = []
        hunks: list[DiffHunk] = []
        current_header: Optional[str] = None
        current_lines: list[str] = []
        for line in diff_text.splitlines():
            if line.startswith("@@ "):
                if current_header is not None:
                    hunks.append(DiffHunk(current_header, tuple(current_lines)))
                current_header = line
                current_lines = []
                continue
            if current_header is None:
                prelude.append(line)
            else:
                current_lines.append(line)
        if current_header is not None:
            hunks.append(DiffHunk(current_header, tuple(current_lines)))
        return ParsedUnifiedDiff(tuple(prelude), tuple(hunks))

    def _render_diff_body(self, card: TranscriptCard, diff_payload: dict[str, Any]):
        diff_text = str(diff_payload.get("unified") or "").strip()
        parsed = self._parse_unified_diff(diff_text)
        renderables: list[Any] = []
        summary = str(card.body or "").strip()
        if summary:
            renderables.append(Text(summary, style="#e2e8f0"))
        header = self._render_diff_prelude(parsed.prelude, diff_payload)
        if header is not None:
            renderables.append(header)
        lexer = self._guess_diff_lexer(diff_payload)
        for index, hunk in enumerate(parsed.hunks, start=1):
            renderables.append(
                Panel(
                    self._render_diff_hunk(hunk, lexer),
                    title=hunk.header,
                    title_align="left",
                    border_style="#334155",
                    box=ROUNDED,
                    padding=(0, 1),
                )
            )
        if len(renderables) == 1 and summary:
            return renderables[0]
        if not renderables:
            return Syntax(diff_text, "diff", theme="monokai", word_wrap=True)
        return Group(*renderables)

    def _render_diff_prelude(self, lines: tuple[str, ...], diff_payload: dict[str, Any]) -> Optional[Panel]:
        if not lines and not diff_payload.get("relative_path") and not diff_payload.get("file_path"):
            return None
        body = Text()
        relative_path = str(diff_payload.get("relative_path") or "").strip()
        file_path = str(diff_payload.get("file_path") or "").strip()
        label = relative_path or file_path
        if label:
            body.append(label, style="bold #bfdbfe")
            if lines:
                body.append("\n")
        for index, line in enumerate(lines):
            body.append_text(self._render_diff_prelude_line(line))
            if index != len(lines) - 1:
                body.append("\n")
        return Panel(
            body,
            title="Changed File",
            title_align="left",
            border_style="#475569",
            box=ROUNDED,
            padding=(0, 1),
        )

    @staticmethod
    def _render_diff_prelude_line(line: str) -> Text:
        if line.startswith("diff --git"):
            return Text(line, style="bold #93c5fd")
        if line.startswith("new file mode"):
            return Text(line, style="#86efac")
        if line.startswith("--- "):
            return Text(line, style="#fca5a5")
        if line.startswith("+++ "):
            return Text(line, style="#86efac")
        return Text(line, style="#94a3b8")

    def _guess_diff_lexer(self, diff_payload: dict[str, Any]) -> str:
        file_path = str(diff_payload.get("file_path") or diff_payload.get("relative_path") or "").strip()
        if not file_path:
            return "text"
        code_sample = self._diff_code_sample(str(diff_payload.get("unified") or ""))
        try:
            return Syntax.guess_lexer(file_path, code=code_sample or None)
        except Exception:
            return "text"

    @staticmethod
    def _diff_code_sample(diff_text: str) -> str:
        sample_lines: list[str] = []
        for line in diff_text.splitlines():
            if line.startswith(("diff --git", "--- ", "+++ ", "@@ ", "new file mode", "index ")):
                continue
            if line.startswith(("+", "-", " ")):
                sample_lines.append(line[1:])
            if len(sample_lines) >= 40:
                break
        return "\n".join(sample_lines)

    def _render_diff_hunk(self, hunk: DiffHunk, lexer: str) -> Text:
        rendered = Text()
        highlighter = self._make_line_highlighter(lexer)
        for index, line in enumerate(hunk.lines):
            rendered.append_text(self._render_diff_line(line, highlighter))
            if index != len(hunk.lines) - 1:
                rendered.append("\n")
        return rendered

    @staticmethod
    def _make_line_highlighter(lexer: str) -> Optional[Syntax]:
        try:
            return Syntax("", lexer, theme="monokai", word_wrap=False)
        except Exception:
            return None

    def _render_diff_line(self, line: str, highlighter: Optional[Syntax]) -> Text:
        if line.startswith("+"):
            return self._render_code_diff_line(
                prefix="+",
                body=line[1:],
                highlighter=highlighter,
                prefix_style="bold #4ade80 on #052e16",
                body_background="#052e16",
            )
        if line.startswith("-"):
            return self._render_code_diff_line(
                prefix="-",
                body=line[1:],
                highlighter=highlighter,
                prefix_style="bold #f87171 on #3f1111",
                body_background="#3f1111",
            )
        if line.startswith(" "):
            return self._render_code_diff_line(
                prefix=" ",
                body=line[1:],
                highlighter=highlighter,
                prefix_style="#64748b",
            )
        if line.startswith("\\"):
            return Text(line, style="italic #94a3b8")
        return Text(line, style="#cbd5e1")

    @staticmethod
    def _render_code_diff_line(
        *,
        prefix: str,
        body: str,
        highlighter: Optional[Syntax],
        prefix_style: str,
        body_background: Optional[str] = None,
    ) -> Text:
        rendered = Text(prefix, style=prefix_style)
        try:
            body_text = highlighter.highlight(body) if highlighter is not None else Text(body)
        except Exception:
            body_text = Text(body)
        if body_background:
            body_text.stylize(f"on {body_background}")
        rendered.append_text(body_text)
        return rendered

    def _refresh_command_palette(self, current_text: str) -> None:
        palette = self.query_one("#command-palette", Static)
        text = str(current_text or "")
        if not text.startswith("/"):
            self._palette_entries = []
            self._command_selection_index = 0
            self._palette_state_key = ""
            palette.update(
                Panel(
                    Text("Type / to browse commands. Use ↑ ↓ to select, Tab to insert, and Enter to accept.", style="#94a3b8"),
                    title="Command Palette",
                    border_style="#334155",
                    box=ROUNDED,
                )
            )
            return

        entries, state_key = self._build_palette_entries(text)
        if state_key != self._palette_state_key:
            self._command_selection_index = 0
        self._palette_state_key = state_key
        self._palette_entries = entries
        if not self._palette_entries:
            self._command_selection_index = 0
            palette.update(
                Panel(
                    Text("No command or option matches the current input.", style="#facc15"),
                    title="Command Palette",
                    border_style="#facc15",
                    box=ROUNDED,
                )
            )
            return

        self._command_selection_index = min(self._command_selection_index, len(self._palette_entries) - 1)
        visible_count = 5
        
        # Ensure window_start was initialized
        if not hasattr(self, "_palette_window_start"):
            self._palette_window_start = 0

        # Adjust window to keep selection visible
        if self._command_selection_index < self._palette_window_start:
            self._palette_window_start = self._command_selection_index
        elif self._command_selection_index >= self._palette_window_start + visible_count:
            self._palette_window_start = self._command_selection_index - visible_count + 1
            
        # Clamp window_start
        max_start = max(0, len(self._palette_entries) - visible_count)
        self._palette_window_start = min(max(0, self._palette_window_start), max_start)
        
        window_start = self._palette_window_start
        visible_entries = self._palette_entries[window_start : window_start + visible_count]
        lines: list[Text] = []
        if window_start > 0:
            lines.append(Text(f"... {window_start} earlier item(s)", style="#475569"))
        for offset, entry in enumerate(visible_entries):
            index = window_start + offset
            selected = index == self._command_selection_index
            line = Text(no_wrap=True, overflow="ellipsis")
            if selected:
                prefix_style = "bold #082f49 on #67e8f9"
                label_style = "bold #082f49 on #67e8f9"
                spacer_style = "on #67e8f9"
                desc_style = "#0f172a on #a5f3fc"
                alias_style = "#164e63 on #cffafe"
            else:
                prefix_style = "#475569"
                label_style = "#cbd5e1"
                spacer_style = "#cbd5e1"
                desc_style = "#94a3b8"
                alias_style = "#64748b"
            line.append("▶ " if selected else "  ", style=prefix_style)
            line.append(entry.label, style=label_style)
            line.append("  ", style=spacer_style)
            line.append(entry.description, style=desc_style)
            if entry.aliases:
                line.append(f"  aliases: {', '.join('/' + alias for alias in entry.aliases)}", style=alias_style)
            lines.append(line)
        remaining = len(self._palette_entries) - (window_start + len(visible_entries))
        if remaining > 0:
            lines.append(Text(f"... {remaining} more item(s)", style="#475569"))
        palette.update(
            Panel(
                Group(*lines),
                title=f"Command Palette ({self._command_selection_index + 1}/{len(self._palette_entries)})",
                border_style="#22d3ee",
                box=ROUNDED,
            )
        )

    def _build_palette_entries(self, current_text: str) -> tuple[list[PaletteEntry], str]:
        text = str(current_text or "").strip()
        if text == "/":
            commands = self.engine.command_registry.list_commands()
            return ([self._command_to_palette_entry(command) for command in commands], "commands:")
        invocation = self.engine.command_registry.parse(text)
        if invocation is None:
            return ([], "")

        if invocation.name == "model":
            fragment = invocation.arg_text.strip().lower()
            entries: list[PaletteEntry] = []
            for item in self.engine.get_model_choices():
                name = str(item["name"])
                provider = str(item["provider"])
                model = str(item["model"])
                if fragment and fragment not in name.lower() and fragment not in provider.lower() and fragment not in model.lower():
                    continue
                marker = "* " if item.get("active") else ""
                entries.append(
                    PaletteEntry(
                        label=f"{marker}{name}",
                        description=f"{provider} / {model}",
                        insert_text=f"/model {name}",
                        execute_text=f"/model {name}",
                        mode="execute",
                    )
                )
            return (entries, f"model:{fragment}")

        if invocation.name == "resume":
            fragment = invocation.arg_text.strip().lower()
            return (self._build_session_palette_entries(fragment, prefix="/resume "), f"resume:{fragment}")

        if invocation.name == "session":
            if not invocation.args:
                entries = [
                    PaletteEntry("/session show", "Show the current session details.", "/session show", "/session show"),
                    PaletteEntry("/session list", "List saved S4Code sessions.", "/session list", "/session list"),
                    PaletteEntry("/session load", "Load a saved session.", "/session load ", "/session load ", mode="insert"),
                    PaletteEntry("/session rename", "Rename the current session.", "/session rename ", "/session rename ", mode="insert"),
                    PaletteEntry("/session fork", "Fork the current session into a new branch session.", "/session fork ", "/session fork ", mode="insert"),
                ]
                return (entries + self._build_session_palette_entries("", prefix="/session load "), "session:root")
            subcommand = invocation.args[0].lower()
            remainder = invocation.arg_text[len(invocation.args[0]) :].strip().lower()
            if subcommand in {"load", "resume"}:
                return (
                    self._build_session_palette_entries(remainder, prefix=f"/session {subcommand} "),
                    f"session-load:{remainder}",
                )

        command_fragment = invocation.name
        if " " not in text[1:]:
            matches = self.engine.command_registry.match_commands(command_fragment)
            return ([self._command_to_palette_entry(command) for command in matches], f"commands:{command_fragment}")
        return ([], f"noop:{text}")

    def _command_to_palette_entry(self, command: Any) -> PaletteEntry:
        usage = f" {command.usage}" if command.usage else ""
        insert_text = f"/{command.name}"
        if command.usage:
            insert_text += " "
        return PaletteEntry(
            label=f"/{command.name}{usage}",
            description=command.description,
            insert_text=insert_text,
            execute_text=f"/{command.name}",
            mode="insert",
            aliases=tuple(command.aliases),
        )

    def _build_session_palette_entries(self, fragment: str, *, prefix: str) -> list[PaletteEntry]:
        entries: list[PaletteEntry] = []
        for item in self.engine.get_session_choices():
            session_id = str(item["session_id"])
            title = str(item["title"] or session_id)
            project_root = str(item.get("project_root") or "-")
            model = str(item.get("model") or "-")
            provider = str(item.get("provider") or "-")
            search_blob = " ".join([session_id, title, project_root, model, provider]).lower()
            if fragment and fragment not in search_blob:
                continue
            marker = "* " if item.get("current") else ""
            entries.append(
                PaletteEntry(
                    label=f"{marker}{session_id}",
                    description=f"{title} · {provider}/{model} · {project_root}",
                    insert_text=f"{prefix}{session_id}",
                    execute_text=f"{prefix}{session_id}",
                    mode="execute",
                )
            )
        return entries

    def _resolve_palette_submit(self, text: str) -> tuple[str, str] | None:
        if not text.startswith("/") or not self._palette_entries:
            return None
        selected = self._palette_entries[self._command_selection_index]
        if selected.mode == "execute":
            return ("execute", selected.execute_text)
        invocation = self.engine.command_registry.parse(text)
        if invocation is not None and " " not in text[1:]:
            exact = self.engine.command_registry.get(invocation.name)
            if exact is not None and text == f"/{exact.name}":
                return None
        if text.strip() == selected.insert_text.strip():
            return None
        return ("insert", selected.insert_text)

    def _apply_palette_entry(self, entry: PaletteEntry, *, execute: bool) -> None:
        input_widget = self.query_one("#prompt-input", Input)
        value = entry.execute_text if execute and entry.mode == "execute" else entry.insert_text
        input_widget.value = value
        try:
            input_widget.cursor_position = len(value)
        except Exception:
            pass
        input_widget.focus()
        self._refresh_command_palette(value)

    def _handle_copy_action(self, target: str) -> None:
        if target == "last":
            text = self._build_last_card_plain_text()
            message = "Latest card copied."
        else:
            text = self._build_transcript_plain_text()
            message = "Transcript copied."
        if not text:
            self._transcript_state.append_card("system", "Notice", "Nothing to copy yet.")
            self._render_transcript()
            return
        self._copy_to_clipboard(text, success_message=message)

    def _build_transcript_plain_text(self) -> str:
        blocks = []
        for card in self._transcript_state.cards:
            title = card.title
            if card.status:
                title = f"{title} [{card.status.upper()}]"
            body = str(card.body or "").strip()
            blocks.append(f"{title}\n{body}".rstrip())
        return "\n\n".join(blocks).strip()

    def _build_last_card_plain_text(self) -> str:
        if not self._transcript_state.cards:
            return ""
        card = self._transcript_state.cards[-1]
        title = card.title
        if card.status:
            title = f"{title} [{card.status.upper()}]"
        body = str(card.body or "").strip()
        return f"{title}\n{body}".rstrip()

    def _copy_to_clipboard(self, text: str, *, success_message: str) -> None:
        copied = False
        copy_fn = getattr(self, "copy_to_clipboard", None)
        if callable(copy_fn):
            try:
                copy_fn(text)
                copied = True
            except Exception:
                copied = False
        if not copied:
            try:
                import pyperclip  # type: ignore

                pyperclip.copy(text)
                copied = True
            except Exception:
                copied = False
        if not copied:
            try:
                encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
                print(f"\033]52;c;{encoded}\a", end="", flush=True)
                copied = True
            except Exception:
                copied = False
        if copied:
            self._transcript_state.append_card("system", "Notice", success_message)
        else:
            self._transcript_state.append_card(
                "warning",
                "Copy Unavailable",
                "Clipboard copy is not available in this environment.",
            )
        self._render_transcript()

    def _refresh_sidebar(self) -> None:
        self.query_one("#sidebar", Static).update(self.engine.format_sidebar())

    def _apply_sidebar_visibility(self) -> None:
        self.query_one("#sidebar", Static).display = bool(getattr(self.engine, "sidebar_visible", False))
