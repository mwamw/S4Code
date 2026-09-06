"""Textual UI for S4Code."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any, Optional

from rich.box import ROUNDED
from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Input, Static

from s4code.interfaces.terminal.commands import register_builtin_commands
from s4code.interfaces.terminal.palette import CommandPaletteEntry as PaletteEntry
from s4code.interfaces.terminal.controller import TerminalController
from s4code.interfaces.terminal.theme import load_tui_theme
from s4code.interfaces.terminal.transcript import S4TranscriptState, TranscriptCard
from s4code.interfaces.terminal.palette import S4CommandPaletteBuilder
from .diff_renderer import DiffRenderer


FULL_RENDER_RECENT_CARDS = 40
COMPACT_RENDER_AFTER_CARDS = 60
COMPACT_CARD_BODY_LIMIT = 220
MAX_DIFF_HUNKS_RENDERED = 6
MAX_DIFF_LINES_PER_HUNK = 80


class TranscriptCardView(Static):
    def __init__(self, card_id: str) -> None:
        super().__init__("")
        self.card_id = card_id
        self.render_key: tuple[Any, ...] | None = None

    def sync(self, renderable: Any, render_key: tuple[Any, ...]) -> bool:
        if self.render_key == render_key:
            return False
        self.render_key = render_key
        self.update(renderable)
        return True

    def invalidate_render_cache(self) -> None:
        self.render_key = None


class S4TextualApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
        background: transparent;
    }

    VerticalScroll, Vertical, Horizontal, Static, Input {
        background: transparent;
    }

    TranscriptCardView {
        width: 100%;
        height: auto;
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
        padding: 1 1;
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
        Binding("escape", "interrupt", "Interrupt", show=False, priority=True),
        Binding("down", "command_palette_next", show=False),
        Binding("up", "command_palette_prev", show=False),
        Binding("tab", "command_palette_complete", show=False),
    ]

    def __init__(self, engine: TerminalController):
        super().__init__()
        self.engine = engine
        self._palette_builder = S4CommandPaletteBuilder(engine)
        self._diff_renderer = DiffRenderer(self)
        register_builtin_commands(self.engine.command_registry)
        self._busy = False
        self._transcript_state = S4TranscriptState()
        self._palette_entries: list[PaletteEntry] = []
        self._command_selection_index = 0
        self._palette_state_key = ""
        self._query_task: asyncio.Task[None] | None = None
        self._transcript_render_task: asyncio.Task[None] | None = None
        self._transcript_scroll_task: asyncio.Task[None] | None = None
        self._transcript_render_revision = 0
        self._interrupt_rendered = False
        self._pending_transcript_force_scroll = False
        self._pending_focus_card_id: str | None = None
        self._pending_focus_card_top = False
        self._card_widgets: dict[str, TranscriptCardView] = {}
        self._compact_card_ids: set[str] = set()
        self._rendered_card_count = 0
        self._theme_revision = 0
        self._sidebar_dirty = True
        self._last_sidebar_content = ""
        self._last_sidebar_refresh_at = 0.0
        self._recent_commands: list[str] = []
        self._diff_lexer_cache: dict[str, str] = {}
        self._theme = load_tui_theme(getattr(self.engine.settings.ui, "theme", "s4"))

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="main-column"):
                yield VerticalScroll(id="transcript")
                yield Static(id="command-palette")
            yield Static(id="sidebar")
        yield Input(placeholder="Ask S4Code or type /help", id="prompt-input")
        yield Footer()

    def on_mount(self) -> None:
        self._apply_theme_styles()
        self._hydrate_transcript_from_engine()
        self._render_transcript()
        self._refresh_command_palette("")
        self._apply_sidebar_visibility()
        self._refresh_sidebar(force=True)
        self._runtime_refresh_timer = self.set_interval(0.25, self._refresh_live_rounds)

    def on_unmount(self) -> None:
        self._runtime_refresh_timer.stop()
        if self._transcript_render_task is not None:
            self._transcript_render_task.cancel()
            self._transcript_render_task = None
        if self._transcript_scroll_task is not None:
            self._transcript_scroll_task.cancel()
            self._transcript_scroll_task = None
        try:
            self.engine.close()
        except Exception:
            pass

    def _theme_value(self, path: str, default: str) -> str:
        current: Any = self._theme
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return str(current or default)

    def _theme_card(self, kind: str) -> dict[str, str]:
        cards = self._theme.get("cards") if isinstance(self._theme, dict) else {}
        if not isinstance(cards, dict):
            cards = {}
        payload = (
            cards.get(kind)
            if isinstance(cards.get(kind), dict)
            else cards.get("default")
        )
        if not isinstance(payload, dict):
            payload = {}
        return {
            "border": str(
                payload.get("border")
                or self._theme_value("cards.default.border", "#64748b")
            ),
            "title": str(
                payload.get("title")
                or self._theme_value("cards.default.title", "#e2e8f0")
            ),
            "text": str(
                payload.get("text") or self._theme_value("layout.muted", "#94a3b8")
            ),
        }

    def _apply_theme_styles(self) -> None:
        def _safe_apply(callback) -> None:
            try:
                callback()
            except Exception:
                pass

        background = self._theme_value("layout.background", "transparent")
        _safe_apply(lambda: setattr(self.screen.styles, "background", background))
        _safe_apply(
            lambda: setattr(
                self.query_one(Header).styles,
                "color",
                self._theme_value("layout.header_text", "#e2e8f0"),
            )
        )
        _safe_apply(
            lambda: setattr(
                self.query_one(Footer).styles,
                "color",
                self._theme_value("layout.footer_text", "#94a3b8"),
            )
        )
        _safe_apply(
            lambda: setattr(
                self.query_one("#transcript", VerticalScroll).styles,
                "border",
                ("round", self._theme_value("layout.transcript_border", "#38bdf8")),
            )
        )
        _safe_apply(
            lambda: setattr(
                self.query_one("#transcript", VerticalScroll).styles,
                "scrollbar_visibility",
                "hidden",
            )
        )
        _safe_apply(
            lambda: setattr(
                self.query_one("#transcript", VerticalScroll).styles,
                "scrollbar_size_vertical",
                0,
            )
        )
        _safe_apply(
            lambda: setattr(
                self.query_one("#transcript", VerticalScroll).styles,
                "scrollbar_size_horizontal",
                0,
            )
        )
        _safe_apply(
            lambda: setattr(
                self.query_one("#sidebar", Static).styles,
                "border",
                ("round", self._theme_value("layout.sidebar_border", "#475569")),
            )
        )
        _safe_apply(
            lambda: setattr(
                self.query_one("#sidebar", Static).styles,
                "color",
                self._theme_value("layout.sidebar_text", "#cbd5e1"),
            )
        )
        _safe_apply(
            lambda: setattr(
                self.query_one("#command-palette", Static).styles,
                "border",
                ("round", self._theme_value("layout.palette_border", "#334155")),
            )
        )
        _safe_apply(
            lambda: setattr(
                self.query_one("#prompt-input", Input).styles,
                "border",
                ("round", self._theme_value("layout.input_border", "#22d3ee")),
            )
        )
        _safe_apply(
            lambda: setattr(
                self.query_one("#prompt-input", Input).styles,
                "color",
                self._theme_value("layout.input_text", "#e2e8f0"),
            )
        )

    def _reload_theme(self) -> None:
        self._theme = load_tui_theme(getattr(self.engine.settings.ui, "theme", "s4"))
        self._theme_revision += 1
        for widget in self._card_widgets.values():
            widget.invalidate_render_cache()
        self._transcript_state.mark_all_cards_dirty()
        self._apply_theme_styles()
        self._mark_sidebar_dirty()
        self._refresh_sidebar(force=True)
        try:
            current_input = self.query_one("#prompt-input", Input).value
        except Exception:
            current_input = ""
        self._refresh_command_palette(current_input)
        self._render_transcript()

    def action_clear_log(self) -> None:
        self._transcript_state.clear()
        self._compact_card_ids.clear()
        self._render_transcript()

    def action_copy_transcript(self) -> None:
        self._copy_to_clipboard(
            self._build_transcript_plain_text(), success_message="Transcript copied."
        )

    def action_copy_last_card(self) -> None:
        text = self._build_last_card_plain_text()
        if not text:
            self._transcript_state.append_card(
                "system", "Notice", "Nothing to copy yet."
            )
            self._render_transcript()
            return
        self._copy_to_clipboard(text, success_message="Latest card copied.")

    def action_command_palette_next(self) -> None:
        input_widget = self.query_one("#prompt-input", Input)
        if (
            not input_widget.has_focus
            or not input_widget.value.startswith("/")
            or not self._palette_entries
        ):
            return
        self._command_selection_index = (self._command_selection_index + 1) % len(
            self._palette_entries
        )
        self._refresh_command_palette(input_widget.value)

    def action_command_palette_prev(self) -> None:
        input_widget = self.query_one("#prompt-input", Input)
        if (
            not input_widget.has_focus
            or not input_widget.value.startswith("/")
            or not self._palette_entries
        ):
            return
        self._command_selection_index = (self._command_selection_index - 1) % len(
            self._palette_entries
        )
        self._refresh_command_palette(input_widget.value)

    def action_command_palette_complete(self) -> None:
        input_widget = self.query_one("#prompt-input", Input)
        if (
            not input_widget.has_focus
            or not input_widget.value.startswith("/")
            or not self._palette_entries
        ):
            return
        self._apply_palette_entry(
            self._palette_entries[self._command_selection_index], execute=False
        )

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
        self._interrupt_rendered = False
        self._transcript_state.append_card("user", "You", text)
        self._render_transcript(force_scroll=True)
        self._query_task = asyncio.create_task(self._process_submission(text))

    def action_interrupt(self) -> None:
        if self._busy and self._query_task is not None and not self._query_task.done():
            self._mark_query_interrupted()
            try:
                self.engine.request_stop("User pressed Esc in the S4Code TUI.")
            except Exception:
                pass
            self._query_task.cancel()
            return
        input_widget = self.query_one("#prompt-input", Input)
        if input_widget.value.startswith("/"):
            input_widget.value = ""
            self._refresh_command_palette("")

    def _mark_query_interrupted(self) -> None:
        if self._interrupt_rendered:
            return
        self._interrupt_rendered = True
        self._transcript_state.consume_event(
            {
                "type": "cancelled",
                "content": "Agent execution interrupted by Esc.",
            }
        )
        self._render_transcript()

    async def _process_submission(self, text: str) -> None:
        try:
            invocation = self.engine.command_registry.parse(text)
            if invocation is not None:
                self.engine.record_command_usage(invocation.name)
                self._recent_commands = [
                    item for item in self._recent_commands if item != invocation.name
                ]
                self._recent_commands.insert(0, invocation.name)
                del self._recent_commands[12:]
            result = self.engine.command_registry.execute(self.engine, text)
            if result is None:
                await self._run_query(text)
            else:
                ui_action = str(result.metadata.get("ui_action") or "")
                if ui_action == "copy_to_clipboard":
                    self._handle_copy_action(
                        str(result.metadata.get("copy_target") or "transcript")
                    )
                elif ui_action == "reload_theme":
                    self._reload_theme()
                if result.message:
                    if result.refresh_requested:
                        self._hydrate_transcript_from_engine(notice=result.message)
                    else:
                        self._transcript_state.append_card(
                            "system", "System", result.message
                        )
                    self._render_transcript(force_scroll=True)
                    self._apply_sidebar_visibility()
                    self._mark_sidebar_dirty()
                engine_action = str(result.metadata.get("engine_action") or "")
                if engine_action == "confirm_pending":
                    await self._run_pending_resolution(
                        "approve", str(result.metadata.get("answer") or "")
                    )
                elif engine_action == "deny_pending":
                    await self._run_pending_resolution(
                        "deny", str(result.metadata.get("answer") or "")
                    )
                elif engine_action == "answer_pending":
                    await self._run_pending_resolution(
                        "answer", str(result.metadata.get("answer") or "")
                    )
                if result.should_query and result.query:
                    await self._run_query(result.query)
                if result.exit_requested:
                    self.exit()
            self._mark_sidebar_dirty()
            self._refresh_sidebar(force=True)
        except asyncio.CancelledError:
            self._mark_query_interrupted()
            self._append_invoke_separator()
        except Exception as exc:
            self._transcript_state.append_card(
                "error", "Error", f"{type(exc).__name__}: {exc}"
            )
            self._render_transcript(force_scroll=True)
            self._mark_sidebar_dirty()
        finally:
            self._busy = False
            self._query_task = None
            self._interrupt_rendered = False

    async def _run_query(self, prompt: str) -> None:
        async for event in self.engine.stream_prompt(prompt):
            self._render_event(event)
        self._append_invoke_separator()

    async def _run_pending_resolution(self, action: str, answer: str = "") -> None:
        async for event in self.engine.permissions.stream_resolve_pending_interaction(
            action=action,
            answer=answer,
        ):
            self._render_event(event)
        self._append_invoke_separator()

    def _hydrate_transcript_from_engine(self, *, notice: Optional[str] = None) -> None:
        self._transcript_state.clear()
        welcome = self.engine.status.get_welcome_notice()
        self._transcript_state.append_card(
            str(welcome.get("kind") or "system"),
            str(welcome.get("title") or "Welcome"),
            str(welcome.get("body") or "").strip(),
        )
        history_cards = self.engine.checkpoints.get_transcript_history_cards()
        if history_cards:
            self._transcript_state.append_card(
                "system",
                "Restored Transcript",
                f"Loaded {len(history_cards)} history message(s) from session {self.engine.session_id}.",
            )
            for item in history_cards:
                self._transcript_state.append_card(
                    str(item.get("kind") or "system"),
                    str(item.get("title") or "History"),
                    str(item.get("body") or ""),
                    status=item.get("status"),
                    metadata=item.get("metadata")
                    if isinstance(item.get("metadata"), dict)
                    else None,
                )
        for startup_notice in self.engine.status.get_startup_notices():
            self._transcript_state.append_card(
                str(startup_notice.get("kind") or "system"),
                str(startup_notice.get("title") or "Notice"),
                str(startup_notice.get("body") or "").strip(),
            )
        if notice:
            self._transcript_state.append_card("system", "System", notice)
        pending = self.engine.permissions.get_pending_interaction()
        if pending is not None:
            self._transcript_state.consume_event(
                {
                    "type": "interruption",
                    "content": pending.get("message")
                    or "A pending interaction was restored with this session.",
                    "payload": pending,
                }
            )

    def _append_invoke_separator(self) -> None:
        self._transcript_state.append_card("separator", "", "")
        self._render_transcript(
            focus_card_id=self._latest_non_separator_card_id(),
            focus_top=True,
        )

    def _render_event(self, event: dict[str, object]) -> None:
        self._transcript_state.consume_event(dict(event))
        event_type = str(event.get("type") or "")
        if event_type in {
            "round_start",
            "tool_call",
            "tool_result",
            "round_metrics",
            "final",
            "interruption",
            "interaction_resolved",
            "error",
            "checkpoint",
            "cancelled",
            "compaction_start",
            "compaction_result",
            "system_notice",
            "runtime_snapshot",
        }:
            self._mark_sidebar_dirty()
        if event_type == "final":
            self._refresh_sidebar(force=True)
        if event_type in {
            "thinking_delta",
            "text_delta",
            "tool_call",
            "tool_result",
            "round_metrics",
            "runtime_snapshot",
        }:
            self._request_transcript_render()
            return
        self._render_transcript()

    def _request_transcript_render(
        self,
        *,
        force_scroll: bool = False,
        focus_card_id: str | None = None,
        focus_top: bool = False,
        delay: float = 0.03,
    ) -> None:
        self._pending_transcript_force_scroll = (
            self._pending_transcript_force_scroll or force_scroll
        )
        if focus_card_id:
            self._pending_focus_card_id = focus_card_id
            self._pending_focus_card_top = self._pending_focus_card_top or focus_top
        if (
            self._transcript_render_task is not None
            and not self._transcript_render_task.done()
        ):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._render_transcript(
                force_scroll=self._pending_transcript_force_scroll,
                focus_card_id=self._pending_focus_card_id,
                focus_top=self._pending_focus_card_top,
            )
            return
        self._transcript_render_task = loop.create_task(
            self._deferred_transcript_render(delay)
        )

    async def _deferred_transcript_render(self, delay: float) -> None:
        try:
            await asyncio.sleep(max(float(delay), 0.0))
            try:
                self._flush_transcript_render(
                    force_scroll=self._pending_transcript_force_scroll,
                    focus_card_id=self._pending_focus_card_id,
                    focus_top=self._pending_focus_card_top,
                )
            except Exception:
                return
        except asyncio.CancelledError:
            return
        finally:
            self._transcript_render_task = None

    def _render_transcript(
        self,
        *,
        force_scroll: bool = False,
        focus_card_id: str | None = None,
        focus_top: bool = False,
    ) -> None:
        if (
            self._transcript_render_task is not None
            and not self._transcript_render_task.done()
        ):
            self._transcript_render_task.cancel()
            self._transcript_render_task = None
        self._flush_transcript_render(
            force_scroll=force_scroll,
            focus_card_id=focus_card_id,
            focus_top=focus_top,
        )

    def _flush_transcript_render(
        self,
        *,
        force_scroll: bool = False,
        focus_card_id: str | None = None,
        focus_top: bool = False,
    ) -> None:
        self._transcript_render_revision += 1
        revision = self._transcript_render_revision
        requested_force_scroll = force_scroll or self._pending_transcript_force_scroll
        self._pending_transcript_force_scroll = False
        target_card_id = focus_card_id or self._pending_focus_card_id
        target_card_top = focus_top or self._pending_focus_card_top
        self._pending_focus_card_id = None
        self._pending_focus_card_top = False
        scroller = self.query_one("#transcript", VerticalScroll)
        forced_follow = requested_force_scroll
        should_follow = requested_force_scroll or self._should_follow_transcript(
            scroller
        )
        previous_scroll_y = getattr(scroller, "scroll_y", 0)
        mount_wait = self._sync_transcript_widgets()
        if mount_wait is not None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                mount_wait = None
            else:
                if (
                    self._transcript_scroll_task is not None
                    and not self._transcript_scroll_task.done()
                ):
                    self._transcript_scroll_task.cancel()
                self._transcript_scroll_task = loop.create_task(
                    self._restore_transcript_scroll_after_mount(
                        mount_wait,
                        should_follow=should_follow,
                        forced_follow=forced_follow,
                        previous_scroll_y=previous_scroll_y,
                        target_card_id=target_card_id,
                        target_card_top=target_card_top,
                        revision=revision,
                    )
                )
                return
        try:
            callback = getattr(self, "call_after_refresh", None)
            if callable(callback):
                callback(
                    self._restore_transcript_scroll,
                    should_follow,
                    forced_follow,
                    previous_scroll_y,
                    target_card_id,
                    target_card_top,
                    revision,
                )
            else:
                self._restore_transcript_scroll(
                    should_follow,
                    forced_follow,
                    previous_scroll_y,
                    target_card_id,
                    target_card_top,
                    revision,
                )
        except Exception:
            self._restore_transcript_scroll(
                should_follow,
                forced_follow,
                previous_scroll_y,
                target_card_id,
                target_card_top,
                revision,
            )

    @staticmethod
    def _should_follow_transcript(scroller: VerticalScroll) -> bool:
        try:
            max_scroll_y = float(getattr(scroller, "max_scroll_y", 0) or 0)
            scroll_y = float(getattr(scroller, "scroll_y", 0) or 0)
        except Exception:
            return True
        return max_scroll_y <= 0 or (max_scroll_y - scroll_y) <= 2

    def _restore_transcript_scroll(
        self,
        should_follow: bool,
        forced_follow: bool,
        previous_scroll_y: float,
        target_card_id: str | None = None,
        target_card_top: bool = False,
        revision: int | None = None,
    ) -> None:
        if revision is not None and revision != self._transcript_render_revision:
            return
        try:
            scroller = self.query_one("#transcript", VerticalScroll)
        except Exception:
            return
        try:
            if not forced_follow and self._transcript_scroll_changed_since_snapshot(
                scroller,
                previous_scroll_y,
            ):
                return
            if should_follow:
                target_widget = self._card_widgets.get(target_card_id or "")
                if target_widget is not None:
                    if target_card_top:
                        self._scroll_card_to_top(target_card_id)
                    else:
                        scroller.scroll_to_widget(
                            target_widget,
                            top=False,
                            animate=False,
                            immediate=True,
                        )
                else:
                    scroller.scroll_end(animate=False)
            else:
                scroller.scroll_to(y=previous_scroll_y, animate=False)
        except Exception:
            pass

    async def _restore_transcript_scroll_after_mount(
        self,
        mount_wait: Any,
        *,
        should_follow: bool,
        forced_follow: bool,
        previous_scroll_y: float,
        target_card_id: str | None,
        target_card_top: bool,
        revision: int | None = None,
    ) -> None:
        try:
            await mount_wait
        except asyncio.CancelledError:
            return
        except Exception:
            return
        # Mount completion does not mean the next layout has been calculated.
        # Use the refresh boundary, not a scheduler yield, before reading regions.
        self.call_after_refresh(
            self._restore_transcript_scroll,
            should_follow,
            forced_follow,
            previous_scroll_y,
            target_card_id,
            target_card_top,
            revision,
        )

    @staticmethod
    def _transcript_scroll_changed_since_snapshot(
        scroller: VerticalScroll,
        previous_scroll_y: float,
        *,
        tolerance: float = 0.75,
    ) -> bool:
        try:
            current_scroll_y = float(getattr(scroller, "scroll_y", 0) or 0)
        except Exception:
            return False
        return abs(current_scroll_y - float(previous_scroll_y or 0)) > max(
            float(tolerance), 0.0
        )

    def _scroll_card_to_top(self, card_id: str | None) -> None:
        if not card_id:
            return
        try:
            scroller = self.query_one("#transcript", VerticalScroll)
        except Exception:
            return
        target_widget = self._card_widgets.get(card_id)
        if target_widget is None:
            return
        try:
            target_y = max(
                float(getattr(scroller, "scroll_y", 0) or 0)
                + float(target_widget.region.y),
                0.0,
            )
            scroller.scroll_to(y=target_y, animate=False, immediate=True)
        except Exception:
            pass

    def _latest_non_separator_card_id(self) -> str | None:
        for card in reversed(self._transcript_state.cards):
            if card.kind != "separator":
                if card.kind == "system" and any(
                    bool(card.metadata.get(key))
                    for key in (
                        "outcome_summary",
                        "changed_files",
                        "verification",
                        "conclusion",
                    )
                ):
                    continue
                return card.card_id
        return None

    def _sync_transcript_widgets(self) -> Any | None:
        container = self.query_one("#transcript", VerticalScroll)
        cards = self._transcript_state.cards
        dirty_ids = self._transcript_state.consume_dirty_card_ids()
        mount_wait = None
        current_card_ids = [card.card_id for card in cards]
        current_card_id_set = set(current_card_ids)
        stale_card_ids = [
            card_id
            for card_id in list(self._card_widgets)
            if card_id not in current_card_id_set
        ]
        for card_id in stale_card_ids:
            widget = self._card_widgets.pop(card_id, None)
            if widget is None:
                continue
            try:
                widget.remove()
            except Exception:
                pass
        compact_card_ids = self._compute_compact_card_ids(cards)
        if compact_card_ids != self._compact_card_ids:
            dirty_ids.update(compact_card_ids ^ self._compact_card_ids)
            self._compact_card_ids = compact_card_ids
        new_widgets: list[TranscriptCardView] = []
        for card in cards:
            if card.card_id not in self._card_widgets:
                widget = TranscriptCardView(card.card_id)
                self._card_widgets[card.card_id] = widget
                new_widgets.append(widget)
                dirty_ids.add(card.card_id)
        if new_widgets:
            mount_wait = container.mount_all(new_widgets)
        self._rendered_card_count = len(cards)
        for card_id in dirty_ids:
            card = self._transcript_state.find_card(card_id)
            widget = self._card_widgets.get(card_id)
            if card is None or widget is None:
                continue
            render_key = self._card_render_key(card)
            if widget.render_key == render_key:
                continue
            widget.sync(self._build_panel(card), render_key)
        return mount_wait

    def _reset_transcript_widgets(self) -> None:
        for widget in list(self._card_widgets.values()):
            try:
                widget.remove()
            except Exception:
                pass
        self._card_widgets.clear()
        self._compact_card_ids.clear()
        self._rendered_card_count = 0

    def _card_render_key(self, card: TranscriptCard) -> tuple[Any, ...]:
        return (
            self._theme_revision,
            int(getattr(card, "revision", 0)),
            card.kind,
            card.title,
            card.status or "",
            card.card_id in self._compact_card_ids,
        )

    def _refresh_live_rounds(self) -> None:
        # Children may already be gone before the app's Unmount event arrives.
        if not self.query("#sidebar"):
            return
        if self._busy and self._transcript_state.refresh_round_timers():
            self._request_transcript_render()
        for notice in self.engine.runtime.poll_runtime_notices():
            self._render_event(notice)
        live_sidebar = self._busy or self.engine.runtime.has_live_runtime_activity(
            force=False
        )
        if self._sidebar_dirty:
            self._refresh_sidebar(force=True)
        elif live_sidebar:
            self._refresh_sidebar()

    def _build_panel(self, card: TranscriptCard) -> Panel:
        if card.kind == "separator":
            return Rule(
                style=self._theme_value("layout.separator", "#475569"), characters="─"
            )
        card_theme = self._theme_card(card.kind)
        border_style = card_theme["border"]
        title = card.title
        if card.status:
            title = f"{title} [{card.status.upper()}]"
        checkpoint_subtitle = self._checkpoint_subtitle(card)
        compact = card.card_id in self._compact_card_ids
        if card.kind == "round":
            return Panel(
                Text(
                    self._compact_round_body(card)
                    if compact
                    else (card.body or card.title),
                    style=card_theme["text"],
                ),
                title=card.title,
                border_style=border_style,
                title_align="left",
                subtitle=checkpoint_subtitle,
                subtitle_align="right",
                box=ROUNDED,
                padding=(0, 1),
            )
        body_renderable = (
            self._render_compact_body(card) if compact else self._render_body(card)
        )
        footer_left = self._footer_left(card, compact=compact)
        panel_content = (
            Group(body_renderable, footer_left)
            if footer_left is not None
            else body_renderable
        )
        return Panel(
            panel_content,
            title=title,
            border_style=border_style,
            title_align="left",
            subtitle=checkpoint_subtitle,
            subtitle_align="right",
            box=ROUNDED,
            padding=(0, 1),
        )

    def _footer_left(self, card: TranscriptCard, *, compact: bool) -> Text | None:
        if compact:
            return None
        footer = str(card.metadata.get("footer_left") or "").strip()
        if not footer:
            return None
        return Text(footer, style=self._theme_value("layout.muted", "#94a3b8"))

    def _checkpoint_subtitle(self, card: TranscriptCard) -> Text | None:
        checkpoints = card.metadata.get("checkpoints")
        if not isinstance(checkpoints, list) or not checkpoints:
            return None
        labels: list[str] = []
        for item in checkpoints[-2:]:
            if not isinstance(item, dict):
                continue
            checkpoint_id = str(item.get("checkpoint_id") or "").strip()
            label = str(item.get("label") or "").strip()
            if checkpoint_id and label:
                labels.append(f"{checkpoint_id} · {label}")
            elif checkpoint_id:
                labels.append(checkpoint_id)
        if not labels:
            return None
        if len(checkpoints) > 2:
            labels.insert(0, f"+{len(checkpoints) - 2}")
        return Text(
            "  ".join(labels),
            style=self._theme_value("layout.checkpoint", "bold #fbbf24"),
        )

    def _render_body(self, card: TranscriptCard):
        content = str(card.body or "").strip()
        diff_payload = self._diff_renderer._extract_diff_payload(card)
        if diff_payload is not None:
            return self._diff_renderer._render_diff_body(card, diff_payload)
        if not content:
            return Text("")
        if card.kind == "assistant":
            if self._looks_like_markdown(content):
                markdown_content = (
                    self._prepare_streaming_markdown(content)
                    if card.status == "streaming"
                    else content
                )
                try:
                    return Markdown(markdown_content)
                except Exception:
                    pass
            return Text(content, style=self._theme_card("assistant")["text"])
        if card.kind == "thinking":
            return Text(content, style=self._theme_card("thinking")["text"])
        if card.kind == "system":
            return Text(content, style=self._theme_card("system")["text"])
        if card.kind == "user":
            return Text(content, style=self._theme_card("user")["text"])
        if card.kind == "warning":
            return Text(content, style=self._theme_card("warning")["text"])
        if card.kind == "error":
            return Text(content, style=self._theme_card("error")["text"])
        if content.startswith("{") and content.endswith("}"):
            try:
                return Syntax(content, "json", theme="monokai", word_wrap=True)
            except Exception:
                return Text(content)
        if (
            "diff --git" in content
            or content.startswith("--- ")
            or content.startswith("@@ ")
        ):
            return Syntax(content, "diff", theme="monokai", word_wrap=True)
        return Text(content)

    @staticmethod
    def _looks_like_markdown(content: str) -> bool:
        starters = (
            "# ",
            "## ",
            "### ",
            "- ",
            "* ",
            "> ",
            "1. ",
            "```",
            "|",
        )
        if content.startswith(starters):
            return True
        markers = (
            "```",
            "\n#",
            "\n- ",
            "\n* ",
            "\n1. ",
            "\n> ",
            "\n|",
            "`",
        )
        return any(marker in content for marker in markers)

    @staticmethod
    def _prepare_streaming_markdown(content: str) -> str:
        normalized = str(content or "")
        if normalized.count("```") % 2 == 1:
            return normalized + "\n```"
        return normalized

    @staticmethod
    def _compact_round_body(card: TranscriptCard) -> str:
        content = str(card.body or card.title or "").strip()
        if not content:
            return ""
        return content.splitlines()[0].strip()

    def _compute_compact_card_ids(self, cards: list[TranscriptCard]) -> set[str]:
        total = len(cards)
        if total <= COMPACT_RENDER_AFTER_CARDS:
            return set()
        cutoff = max(total - FULL_RENDER_RECENT_CARDS, 0)
        return {card.card_id for card in cards[:cutoff] if card.kind != "separator"}

    def _render_compact_body(self, card: TranscriptCard) -> Text:
        summary = self._compact_card_summary(card)
        return Text(summary, style=self._theme_card(card.kind)["text"])

    def _compact_card_summary(self, card: TranscriptCard) -> str:
        diff_payload = self._diff_renderer._extract_diff_payload(card)
        if diff_payload is not None:
            label = str(
                diff_payload.get("relative_path") or diff_payload.get("file_path") or ""
            ).strip()
            detail = (
                str(card.body or "").strip().splitlines()[0]
                if str(card.body or "").strip()
                else "Diff available"
            )
            return self._truncate_compact_text(
                " | ".join(item for item in [label, detail] if item)
            )
        body = str(card.body or "").strip()
        if not body:
            return ""
        if card.kind == "round":
            return self._compact_round_body(card)
        return self._truncate_compact_text(" ".join(body.split()))

    @staticmethod
    def _truncate_compact_text(text: str) -> str:
        normalized = str(text or "").strip()
        if len(normalized) <= COMPACT_CARD_BODY_LIMIT:
            return normalized
        return normalized[:COMPACT_CARD_BODY_LIMIT].rstrip() + "..."

    def _refresh_command_palette(self, current_text: str) -> None:
        palette = self.query_one("#command-palette", Static)
        text = str(current_text or "")
        if not text.startswith("/"):
            self._palette_entries = []
            self._command_selection_index = 0
            self._palette_state_key = ""
            palette.update(Text(""))
            palette.display = False
            return

        palette.display = True
        entries, state_key = self._build_palette_entries(text)
        if state_key != self._palette_state_key:
            self._command_selection_index = 0
        self._palette_state_key = state_key
        self._palette_entries = entries
        if not self._palette_entries:
            self._command_selection_index = 0
            palette.update(
                Panel(
                    Text(
                        "No command or option matches the current input.",
                        style=self._theme_value("palette.empty", "#facc15"),
                    ),
                    title="Command Palette",
                    border_style=self._theme_value("palette.empty", "#facc15"),
                    box=ROUNDED,
                )
            )
            return

        self._command_selection_index = min(
            self._command_selection_index, len(self._palette_entries) - 1
        )
        visible_count = 5

        # Ensure window_start was initialized
        if not hasattr(self, "_palette_window_start"):
            self._palette_window_start = 0

        # Adjust window to keep selection visible
        if self._command_selection_index < self._palette_window_start:
            self._palette_window_start = self._command_selection_index
        elif (
            self._command_selection_index >= self._palette_window_start + visible_count
        ):
            self._palette_window_start = (
                self._command_selection_index - visible_count + 1
            )

        # Clamp window_start
        max_start = max(0, len(self._palette_entries) - visible_count)
        self._palette_window_start = min(max(0, self._palette_window_start), max_start)

        window_start = self._palette_window_start
        visible_entries = self._palette_entries[
            window_start : window_start + visible_count
        ]
        lines: list[Text] = []
        if window_start > 0:
            lines.append(
                Text(
                    f"... {window_start} earlier item(s)",
                    style=self._theme_value("palette.hidden_count", "#475569"),
                )
            )
        for offset, entry in enumerate(visible_entries):
            index = window_start + offset
            selected = index == self._command_selection_index
            line = Text(no_wrap=True, overflow="ellipsis")
            if selected:
                prefix_style = self._theme_value(
                    "palette.selected_prefix", "bold #082f49 on #67e8f9"
                )
                label_style = self._theme_value(
                    "palette.selected_label", "bold #082f49 on #67e8f9"
                )
                spacer_style = self._theme_value(
                    "palette.selected_spacer", "on #67e8f9"
                )
                desc_style = self._theme_value(
                    "palette.selected_description", "#0f172a on #a5f3fc"
                )
                alias_style = self._theme_value(
                    "palette.selected_alias", "#164e63 on #cffafe"
                )
            else:
                prefix_style = self._theme_value("palette.prefix", "#475569")
                label_style = self._theme_value("palette.label", "#cbd5e1")
                spacer_style = self._theme_value("palette.spacer", "#cbd5e1")
                desc_style = self._theme_value("palette.description", "#94a3b8")
                alias_style = self._theme_value("palette.alias", "#64748b")
            line.append("▶ " if selected else "  ", style=prefix_style)
            line.append(entry.label, style=label_style)
            line.append("  ", style=spacer_style)
            line.append(entry.description, style=desc_style)
            if entry.aliases:
                line.append(
                    f"  aliases: {', '.join('/' + alias for alias in entry.aliases)}",
                    style=alias_style,
                )
            lines.append(line)
        remaining = len(self._palette_entries) - (window_start + len(visible_entries))
        if remaining > 0:
            lines.append(
                Text(
                    f"... {remaining} more item(s)",
                    style=self._theme_value("palette.hidden_count", "#475569"),
                )
            )
        palette.update(
            Panel(
                Group(*lines),
                title=f"Command Palette ({self._command_selection_index + 1}/{len(self._palette_entries)})",
                border_style=self._theme_value("palette.border", "#22d3ee"),
                box=ROUNDED,
            )
        )

    def _build_palette_entries(self, current_text):
        return self._palette_builder.build_entries(current_text)

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
        value = (
            entry.execute_text
            if execute and entry.mode == "execute"
            else entry.insert_text
        )
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
            self._transcript_state.append_card(
                "system", "Notice", "Nothing to copy yet."
            )
            self._render_transcript(
                force_scroll=True,
                focus_card_id=self._latest_non_separator_card_id(),
            )
            self._force_scroll_transcript_end()
            return
        self._copy_to_clipboard(text, success_message=message)
        self._render_transcript(
            force_scroll=True,
            focus_card_id=self._latest_non_separator_card_id(),
        )
        self._force_scroll_transcript_end()

    def _force_scroll_transcript_end(self) -> None:
        def _scroll() -> None:
            try:
                scroller = self.query_one("#transcript", VerticalScroll)
            except Exception:
                return
            try:
                scroller.scroll_to(
                    y=float(getattr(scroller, "max_scroll_y", 0) or 0),
                    animate=False,
                    immediate=True,
                )
            except Exception:
                pass

        _scroll()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:

            async def _scroll_later() -> None:
                try:
                    await asyncio.sleep(0)
                    _scroll()
                    await asyncio.sleep(0.05)
                    _scroll()
                except Exception:
                    return

            loop.create_task(_scroll_later())
        try:
            callback = getattr(self, "call_after_refresh", None)
            if callable(callback):
                callback(_scroll)
        except Exception:
            _scroll()

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

    def _mark_sidebar_dirty(self) -> None:
        self._sidebar_dirty = True

    def _build_sidebar_renderable(self, payload: dict[str, Any]) -> Any:
        lines: list[Text] = []
        title_style = self._theme_value("cards.system.title", "bold #e2e8f0")
        body_style = self._theme_value("cards.system.text", "#cbd5e1")
        muted_style = self._theme_value("layout.muted", "#94a3b8")

        def _line(text: str, *, style: str = body_style) -> None:
            lines.append(Text(text, style=style))

        project = str(payload.get("project_name") or "-")
        branch = str(payload.get("branch") or "-")
        model = str(payload.get("model") or "-")
        provider = str(payload.get("provider") or "-")
        session_id = str(payload.get("session_id") or "-")
        permissions = str(payload.get("permission_mode") or "-")
        worktree = dict(payload.get("worktree") or {})
        active_worktree = worktree.get("active") or {}
        context = dict(payload.get("context") or {})
        skills = dict(payload.get("skills") or {})
        pending = dict(payload.get("pending") or {})
        restore = dict(payload.get("restore") or {})
        deferred = dict(payload.get("deferred_tools") or {})
        mcp = dict(payload.get("mcp") or {})

        _line(project, style=title_style)
        _line(f"Branch: {branch}")
        _line(f"Model: {model} via {provider}")
        _line(f"Session: {session_id}")
        _line(f"Permissions: {permissions}", style=muted_style)
        if active_worktree:
            _line(f"Worktree: {active_worktree.get('branch') or '-'}")
            _line(str(active_worktree.get("path") or "-"), style=muted_style)
        else:
            _line("Worktree: none", style=muted_style)
        lines.append(Text(""))
        context_bar = str(context.get("usage_bar") or "[----------------]")
        context_percent = str(context.get("usage_percent") or "-")
        used_tokens = context.get("used_tokens")
        max_tokens = context.get("max_tokens")
        remaining_tokens = context.get("remaining_tokens")
        _line(f"Context {context_bar} {context_percent}")
        _line(
            f"{used_tokens if used_tokens is not None else '?'} / {max_tokens if max_tokens is not None else '?'} used"
            f" · {remaining_tokens if remaining_tokens is not None else '?'} remaining",
            style=muted_style,
        )
        lines.append(Text(""))
        active_skills = list(skills.get("active") or [])
        queued_skills = list(skills.get("queued") or [])
        _line("Skills", style=title_style)
        _line(
            "Active: " + (", ".join(active_skills[:3]) if active_skills else "none"),
            style=muted_style,
        )
        _line(
            "Queued: " + (", ".join(queued_skills[:3]) if queued_skills else "none"),
            style=muted_style,
        )
        _line(
            f"Deferred: {deferred.get('loaded', 0)} loaded · {deferred.get('pending_schema', 0)} waiting",
            style=muted_style,
        )
        if mcp.get("enabled"):
            _line(
                "MCP: "
                f"{mcp.get('connected', 0)} connected · {mcp.get('disabled', 0)} disabled · "
                f"{mcp.get('unavailable', 0)} unavailable",
                style=muted_style,
            )
        lines.append(Text(""))
        _line("Background", style=title_style)
        _line(
            f"{payload.get('active_background_count', 0)} active · {payload.get('failed_background_count', 0)} failed",
            style=muted_style,
        )
        for item in list(payload.get("background_tasks") or [])[:4]:
            _line(
                f"- {item.get('task_id') or '-'} [{item.get('status') or '-'}]",
                style=muted_style,
            )
        if pending.get("active"):
            lines.append(Text(""))
            _line("Pending", style=title_style)
            _line(f"{pending.get('title') or 'Approval required'}", style=body_style)
            _line(f"Risk: {pending.get('risk_level') or 'unknown'}", style=muted_style)
        if restore.get("summary"):
            lines.append(Text(""))
            _line("Continuity", style=title_style)
            _line(str(restore.get("summary") or ""), style=muted_style)
        return Group(*lines)

    def _refresh_sidebar(self, *, force: bool = False) -> None:
        sidebar = self.query_one("#sidebar", Static)
        if not bool(sidebar.display):
            return
        now = time.monotonic()
        if not force and (now - self._last_sidebar_refresh_at) < 0.75:
            return
        payload = self.engine.status.get_sidebar_payload(force=force)
        content_key = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, default=str
        )
        self._last_sidebar_refresh_at = now
        self._sidebar_dirty = False
        if content_key == self._last_sidebar_content:
            return
        self._last_sidebar_content = content_key
        sidebar.update(
            Panel(
                self._build_sidebar_renderable(payload),
                title="Status",
                title_align="left",
                border_style=self._theme_value("layout.sidebar_border", "#475569"),
                box=ROUNDED,
                padding=(0, 1),
            )
        )

    def _apply_sidebar_visibility(self) -> None:
        sidebar = self.query_one("#sidebar", Static)
        visible = bool(getattr(self.engine, "sidebar_visible", False))
        sidebar.display = visible
        if visible:
            self._mark_sidebar_dirty()
