"""Textual UI for S4Code."""

from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass
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

from .commands import register_builtin_commands
from .query_engine import S4QueryEngine
from .theme import load_tui_theme
from .transcript_state import S4TranscriptState, TranscriptCard


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
        self._transcript_render_task: asyncio.Task[None] | None = None
        self._transcript_scroll_task: asyncio.Task[None] | None = None
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
        self.set_interval(0.25, self._refresh_live_rounds)

    def on_unmount(self) -> None:
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
        payload = cards.get(kind) if isinstance(cards.get(kind), dict) else cards.get("default")
        if not isinstance(payload, dict):
            payload = {}
        return {
            "border": str(payload.get("border") or self._theme_value("cards.default.border", "#64748b")),
            "title": str(payload.get("title") or self._theme_value("cards.default.title", "#e2e8f0")),
            "text": str(payload.get("text") or self._theme_value("layout.muted", "#94a3b8")),
        }

    def _apply_theme_styles(self) -> None:
        def _safe_apply(callback) -> None:
            try:
                callback()
            except Exception:
                pass

        background = self._theme_value("layout.background", "transparent")
        _safe_apply(lambda: setattr(self.screen.styles, "background", background))
        _safe_apply(lambda: setattr(self.query_one(Header).styles, "color", self._theme_value("layout.header_text", "#e2e8f0")))
        _safe_apply(lambda: setattr(self.query_one(Footer).styles, "color", self._theme_value("layout.footer_text", "#94a3b8")))
        _safe_apply(lambda: setattr(self.query_one("#transcript", VerticalScroll).styles, "border", ("round", self._theme_value("layout.transcript_border", "#38bdf8"))))
        _safe_apply(lambda: setattr(self.query_one("#transcript", VerticalScroll).styles, "scrollbar_visibility", "hidden"))
        _safe_apply(lambda: setattr(self.query_one("#transcript", VerticalScroll).styles, "scrollbar_size_vertical", 0))
        _safe_apply(lambda: setattr(self.query_one("#transcript", VerticalScroll).styles, "scrollbar_size_horizontal", 0))
        _safe_apply(lambda: setattr(self.query_one("#sidebar", Static).styles, "border", ("round", self._theme_value("layout.sidebar_border", "#475569"))))
        _safe_apply(lambda: setattr(self.query_one("#sidebar", Static).styles, "color", self._theme_value("layout.sidebar_text", "#cbd5e1")))
        _safe_apply(lambda: setattr(self.query_one("#command-palette", Static).styles, "border", ("round", self._theme_value("layout.palette_border", "#334155"))))
        _safe_apply(lambda: setattr(self.query_one("#prompt-input", Input).styles, "border", ("round", self._theme_value("layout.input_border", "#22d3ee"))))
        _safe_apply(lambda: setattr(self.query_one("#prompt-input", Input).styles, "color", self._theme_value("layout.input_text", "#e2e8f0")))

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
            result = self.engine.command_registry.execute(self.engine, text)
            if result is None:
                await self._run_query(text)
            else:
                ui_action = str(result.metadata.get("ui_action") or "")
                if ui_action == "copy_to_clipboard":
                    self._handle_copy_action(str(result.metadata.get("copy_target") or "transcript"))
                elif ui_action == "reload_theme":
                    self._reload_theme()
                if result.message:
                    if result.refresh_requested:
                        self._hydrate_transcript_from_engine(notice=result.message)
                    else:
                        self._transcript_state.append_card("system", "System", result.message)
                    self._render_transcript(force_scroll=True)
                    self._apply_sidebar_visibility()
                    self._mark_sidebar_dirty()
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
            self._mark_sidebar_dirty()
            self._refresh_sidebar(force=True)
        except asyncio.CancelledError:
            self._mark_query_interrupted()
            self._append_invoke_separator()
        except Exception as exc:
            self._transcript_state.append_card("error", "Error", f"{type(exc).__name__}: {exc}")
            self._render_transcript(force_scroll=True)
            self._mark_sidebar_dirty()
        finally:
            if self._interrupt_rendered:
                try:
                    self.engine.clear_stop_request()
                except Exception:
                    pass
            self._busy = False
            self._query_task = None
            self._interrupt_rendered = False

    async def _run_query(self, prompt: str) -> None:
        async for event in self.engine.stream_prompt(prompt):
            self._render_event(event)
        self._append_invoke_separator()

    async def _run_pending_resolution(self, action: str, answer: str = "") -> None:
        async for event in self.engine.stream_resolve_pending_interaction(
            action=action,
            answer=answer,
        ):
            self._render_event(event)
        self._append_invoke_separator()

    def _hydrate_transcript_from_engine(self, *, notice: Optional[str] = None) -> None:
        self._transcript_state.clear()
        self._transcript_state.append_card("system", "System", "S4Code ready. Type /help for commands.")
        history_cards = self.engine.get_transcript_history_cards()
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
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else None,
                )
        for startup_notice in self.engine.get_startup_notices():
            self._transcript_state.append_card(
                str(startup_notice.get("kind") or "system"),
                str(startup_notice.get("title") or "Notice"),
                str(startup_notice.get("body") or "").strip(),
            )
        if notice:
            self._transcript_state.append_card("system", "System", notice)
        pending = self.engine.get_pending_interaction()
        if pending is not None:
            self._transcript_state.consume_event(
                {
                    "type": "interruption",
                    "content": pending.get("message") or "A pending interaction was restored with this session.",
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
        self._pending_transcript_force_scroll = self._pending_transcript_force_scroll or force_scroll
        if focus_card_id:
            self._pending_focus_card_id = focus_card_id
            self._pending_focus_card_top = self._pending_focus_card_top or focus_top
        if self._transcript_render_task is not None and not self._transcript_render_task.done():
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
        self._transcript_render_task = loop.create_task(self._deferred_transcript_render(delay))

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
        if self._transcript_render_task is not None and not self._transcript_render_task.done():
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
        requested_force_scroll = force_scroll or self._pending_transcript_force_scroll
        self._pending_transcript_force_scroll = False
        target_card_id = focus_card_id or self._pending_focus_card_id
        target_card_top = focus_top or self._pending_focus_card_top
        self._pending_focus_card_id = None
        self._pending_focus_card_top = False
        scroller = self.query_one("#transcript", VerticalScroll)
        should_follow = requested_force_scroll or self._should_follow_transcript(scroller)
        previous_scroll_y = getattr(scroller, "scroll_y", 0)
        mount_wait = self._sync_transcript_widgets()
        if mount_wait is not None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                mount_wait = None
            else:
                if self._transcript_scroll_task is not None and not self._transcript_scroll_task.done():
                    self._transcript_scroll_task.cancel()
                self._transcript_scroll_task = loop.create_task(
                    self._restore_transcript_scroll_after_mount(
                        mount_wait,
                        should_follow=should_follow,
                        previous_scroll_y=previous_scroll_y,
                        target_card_id=target_card_id,
                        target_card_top=target_card_top,
                    )
                )
                return
        try:
            callback = getattr(self, "call_after_refresh", None)
            if callable(callback):
                callback(
                    self._restore_transcript_scroll,
                    should_follow,
                    previous_scroll_y,
                    target_card_id,
                    target_card_top,
                )
            else:
                self._restore_transcript_scroll(
                    should_follow,
                    previous_scroll_y,
                    target_card_id,
                    target_card_top,
                )
        except Exception:
            self._restore_transcript_scroll(
                should_follow,
                previous_scroll_y,
                target_card_id,
                target_card_top,
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
        previous_scroll_y: float,
        target_card_id: str | None = None,
        target_card_top: bool = False,
    ) -> None:
        try:
            scroller = self.query_one("#transcript", VerticalScroll)
        except Exception:
            return
        try:
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
        previous_scroll_y: float,
        target_card_id: str | None,
        target_card_top: bool,
    ) -> None:
        try:
            await mount_wait
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            return
        except Exception:
            return
        self._restore_transcript_scroll(
            should_follow,
            previous_scroll_y,
            target_card_id,
            target_card_top,
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
            target_y = max(float(getattr(scroller, "scroll_y", 0) or 0) + float(target_widget.region.y), 0.0)
            scroller.scroll_to(y=target_y, animate=False, immediate=True)
        except Exception:
            pass

    def _latest_non_separator_card_id(self) -> str | None:
        for card in reversed(self._transcript_state.cards):
            if card.kind != "separator":
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
        if self._busy and self._transcript_state.refresh_round_timers():
            self._request_transcript_render()
        live_sidebar = self._busy or self.engine.has_live_runtime_activity(force=False)
        if self._sidebar_dirty:
            self._refresh_sidebar(force=True)
        elif live_sidebar:
            self._refresh_sidebar()

    def _build_panel(self, card: TranscriptCard) -> Panel:
        if card.kind == "separator":
            return Rule(style=self._theme_value("layout.separator", "#475569"), characters="─")
        card_theme = self._theme_card(card.kind)
        border_style = card_theme["border"]
        title = card.title
        if card.status:
            title = f"{title} [{card.status.upper()}]"
        checkpoint_subtitle = self._checkpoint_subtitle(card)
        compact = card.card_id in self._compact_card_ids
        if card.kind == "round":
            return Panel(
                Text(self._compact_round_body(card) if compact else (card.body or card.title), style=card_theme["text"]),
                title=card.title,
                border_style=border_style,
                title_align="left",
                subtitle=checkpoint_subtitle,
                subtitle_align="right",
                box=ROUNDED,
                padding=(0, 1),
            )
        return Panel(
            self._render_compact_body(card) if compact else self._render_body(card),
            title=title,
            border_style=border_style,
            title_align="left",
            subtitle=checkpoint_subtitle,
            subtitle_align="right",
            box=ROUNDED,
            padding=(0, 1),
        )

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
        return Text("  ".join(labels), style=self._theme_value("layout.checkpoint", "bold #fbbf24"))

    def _render_body(self, card: TranscriptCard):
        content = str(card.body or "").strip()
        diff_payload = self._extract_diff_payload(card)
        if diff_payload is not None:
            return self._render_diff_body(card, diff_payload)
        if not content:
            return Text("")
        if card.kind == "assistant":
            if self._looks_like_markdown(content):
                markdown_content = self._prepare_streaming_markdown(content) if card.status == "streaming" else content
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
        if "diff --git" in content or content.startswith("--- ") or content.startswith("@@ "):
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
        return {
            card.card_id
            for card in cards[:cutoff]
            if card.kind != "separator"
        }

    def _render_compact_body(self, card: TranscriptCard) -> Text:
        summary = self._compact_card_summary(card)
        return Text(summary, style=self._theme_card(card.kind)["text"])

    def _compact_card_summary(self, card: TranscriptCard) -> str:
        diff_payload = self._extract_diff_payload(card)
        if diff_payload is not None:
            label = str(diff_payload.get("relative_path") or diff_payload.get("file_path") or "").strip()
            detail = str(card.body or "").strip().splitlines()[0] if str(card.body or "").strip() else "Diff available"
            return self._truncate_compact_text(" | ".join(item for item in [label, detail] if item))
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
            renderables.append(Text(summary, style=self._theme_value("diff.summary", "#e2e8f0")))
        header = self._render_diff_prelude(parsed.prelude, diff_payload)
        if header is not None:
            renderables.append(header)
        lexer = self._guess_diff_lexer(diff_payload)
        hidden_hunks = max(len(parsed.hunks) - MAX_DIFF_HUNKS_RENDERED, 0)
        for index, hunk in enumerate(parsed.hunks[:MAX_DIFF_HUNKS_RENDERED], start=1):
            visible_lines = hunk.lines[:MAX_DIFF_LINES_PER_HUNK]
            renderables.append(
                Panel(
                    self._render_diff_hunk(DiffHunk(hunk.header, tuple(visible_lines)), lexer),
                    title=hunk.header,
                    title_align="left",
                    border_style=self._theme_value("diff.hunk_border", "#334155"),
                    box=ROUNDED,
                    padding=(0, 1),
                )
            )
            hidden_lines = max(len(hunk.lines) - len(visible_lines), 0)
            if hidden_lines > 0:
                renderables.append(
                    Text(
                        f"... {hidden_lines} more line(s) hidden in this hunk",
                        style=self._theme_value("diff.summary", "#94a3b8"),
                    )
                )
        if hidden_hunks > 0:
            renderables.append(
                Text(
                    f"... {hidden_hunks} more hunk(s) hidden",
                    style=self._theme_value("diff.summary", "#94a3b8"),
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
            body.append(label, style=self._theme_value("diff.file_label", "bold #bfdbfe"))
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
            border_style=self._theme_value("diff.prelude_border", "#475569"),
            box=ROUNDED,
            padding=(0, 1),
        )

    def _render_diff_prelude_line(self, line: str) -> Text:
        if line.startswith("diff --git"):
            return Text(line, style=self._theme_value("diff.git_header", "bold #93c5fd"))
        if line.startswith("new file mode"):
            return Text(line, style=self._theme_value("diff.new_file", "#86efac"))
        if line.startswith("--- "):
            return Text(line, style=self._theme_value("diff.deleted_file", "#fca5a5"))
        if line.startswith("+++ "):
            return Text(line, style=self._theme_value("diff.new_file", "#86efac"))
        return Text(line, style=self._theme_value("diff.prelude", "#94a3b8"))

    def _guess_diff_lexer(self, diff_payload: dict[str, Any]) -> str:
        file_path = str(diff_payload.get("file_path") or diff_payload.get("relative_path") or "").strip()
        if not file_path:
            return "text"
        cached = self._diff_lexer_cache.get(file_path)
        if cached is not None:
            return cached
        code_sample = self._diff_code_sample(str(diff_payload.get("unified") or ""))
        try:
            lexer = Syntax.guess_lexer(file_path, code=code_sample or None)
        except Exception:
            lexer = "text"
        self._diff_lexer_cache[file_path] = lexer
        return lexer

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
                prefix_style=self._theme_value("diff.add_prefix", "bold #4ade80 on #052e16"),
                body_background=self._theme_value("diff.add_background", "#052e16"),
            )
        if line.startswith("-"):
            return self._render_code_diff_line(
                prefix="-",
                body=line[1:],
                highlighter=highlighter,
                prefix_style=self._theme_value("diff.delete_prefix", "bold #f87171 on #3f1111"),
                body_background=self._theme_value("diff.delete_background", "#3f1111"),
            )
        if line.startswith(" "):
            return self._render_code_diff_line(
                prefix=" ",
                body=line[1:],
                highlighter=highlighter,
                prefix_style=self._theme_value("diff.context_prefix", "#64748b"),
            )
        if line.startswith("\\"):
            return Text(line, style=self._theme_value("diff.escape", "italic #94a3b8"))
        return Text(line, style=self._theme_value("diff.plain", "#cbd5e1"))

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
                    Text("No command or option matches the current input.", style=self._theme_value("palette.empty", "#facc15")),
                    title="Command Palette",
                    border_style=self._theme_value("palette.empty", "#facc15"),
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
            lines.append(Text(f"... {window_start} earlier item(s)", style=self._theme_value("palette.hidden_count", "#475569")))
        for offset, entry in enumerate(visible_entries):
            index = window_start + offset
            selected = index == self._command_selection_index
            line = Text(no_wrap=True, overflow="ellipsis")
            if selected:
                prefix_style = self._theme_value("palette.selected_prefix", "bold #082f49 on #67e8f9")
                label_style = self._theme_value("palette.selected_label", "bold #082f49 on #67e8f9")
                spacer_style = self._theme_value("palette.selected_spacer", "on #67e8f9")
                desc_style = self._theme_value("palette.selected_description", "#0f172a on #a5f3fc")
                alias_style = self._theme_value("palette.selected_alias", "#164e63 on #cffafe")
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
                line.append(f"  aliases: {', '.join('/' + alias for alias in entry.aliases)}", style=alias_style)
            lines.append(line)
        remaining = len(self._palette_entries) - (window_start + len(visible_entries))
        if remaining > 0:
            lines.append(Text(f"... {remaining} more item(s)", style=self._theme_value("palette.hidden_count", "#475569")))
        palette.update(
            Panel(
                Group(*lines),
                title=f"Command Palette ({self._command_selection_index + 1}/{len(self._palette_entries)})",
                border_style=self._theme_value("palette.border", "#22d3ee"),
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

        if invocation.name in {"theme", "themes"}:
            fragment = invocation.arg_text.strip().lower()
            entries = [
                PaletteEntry("/theme list", "List available TUI themes.", "/theme list", "/theme list", mode="execute"),
            ]
            for item in self.engine.get_theme_choices():
                name = str(item.get("name") or "")
                kind = str(item.get("kind") or "theme")
                if fragment and fragment not in name.lower() and fragment not in kind.lower():
                    continue
                marker = "* " if item.get("active") else ""
                entries.append(
                    PaletteEntry(
                        label=f"{marker}{name}",
                        description=f"{kind} theme",
                        insert_text=f"/theme {name}",
                        execute_text=f"/theme {name}",
                        mode="execute",
                    )
                )
            return (entries, f"theme:{fragment}")

        if invocation.name == "resume":
            fragment = invocation.arg_text.strip().lower()
            return (self._build_session_palette_entries(fragment, prefix="/resume "), f"resume:{fragment}")

        if invocation.name in {"permissions", "perm"}:
            if not invocation.args:
                entries = [
                    PaletteEntry("/permissions show", "Show current permission mode and rules.", "/permissions show", "/permissions show", mode="execute"),
                    PaletteEntry("/permissions history", "Show permission mode/rule change history.", "/permissions history", "/permissions history", mode="execute"),
                    PaletteEntry("/permissions mode", "Switch permission mode.", "/permissions mode ", "/permissions mode ", mode="insert"),
                    PaletteEntry("/permissions allow", "Add an allow rule.", "/permissions allow ", "/permissions allow ", mode="insert"),
                    PaletteEntry("/permissions deny", "Add a deny rule.", "/permissions deny ", "/permissions deny ", mode="insert"),
                    PaletteEntry("/permissions ask", "Add an ask/confirm rule.", "/permissions ask ", "/permissions ask ", mode="insert"),
                    PaletteEntry("/permissions clear session", "Clear session-scoped permission rules.", "/permissions clear session", "/permissions clear session", mode="execute"),
                    PaletteEntry("/permissions clear all", "Clear all permission rule sources.", "/permissions clear all", "/permissions clear all", mode="execute"),
                ]
                return (entries, "permissions:root")
            subcommand = invocation.args[0].lower()
            if subcommand == "mode":
                fragment = invocation.arg_text[len(invocation.args[0]) :].strip().lower()
                modes = ("default", "accept_edits", "dont_ask", "bypass", "plan")
                entries = [
                    PaletteEntry(
                        label=mode,
                        description=f"Set permission mode to {mode}.",
                        insert_text=f"/permissions mode {mode}",
                        execute_text=f"/permissions mode {mode}",
                        mode="execute",
                    )
                    for mode in modes
                    if not fragment or fragment in mode
                ]
                return (entries, f"permissions-mode:{fragment}")
            if subcommand in {"allow", "deny", "ask"}:
                fragment = invocation.arg_text[len(invocation.args[0]) :].strip().lower()
                entries = [
                    PaletteEntry(
                        label=f"/permissions {subcommand} *",
                        description="Match all tools. Add path=, host=, command=, mcp=, or risk= to narrow scope.",
                        insert_text=f"/permissions {subcommand} * ",
                        execute_text=f"/permissions {subcommand} * ",
                        mode="insert",
                    ),
                    PaletteEntry(
                        label=f"/permissions {subcommand} FileEdit path=",
                        description="Match file edits under a path prefix.",
                        insert_text=f"/permissions {subcommand} FileEdit path=",
                        execute_text=f"/permissions {subcommand} FileEdit path=",
                        mode="insert",
                    ),
                    PaletteEntry(
                        label=f"/permissions {subcommand} WebFetch host=",
                        description="Match WebFetch by hostname/domain.",
                        insert_text=f"/permissions {subcommand} WebFetch host=",
                        execute_text=f"/permissions {subcommand} WebFetch host=",
                        mode="insert",
                    ),
                    PaletteEntry(
                        label=f"/permissions {subcommand} Bash command=",
                        description="Match shell commands by command prefix.",
                        insert_text=f"/permissions {subcommand} Bash command=",
                        execute_text=f"/permissions {subcommand} Bash command=",
                        mode="insert",
                    ),
                ]
                if fragment:
                    entries = [
                        entry for entry in entries
                        if fragment in entry.label.lower() or fragment in entry.description.lower()
                    ]
                return (entries, f"permissions-rule:{subcommand}:{fragment}")
            if subcommand in {"clear", "reset"}:
                fragment = invocation.arg_text[len(invocation.args[0]) :].strip().lower()
                sources = ("session", "all")
                entries = [
                    PaletteEntry(
                        label=source,
                        description=f"Clear {source} permission rules.",
                        insert_text=f"/permissions clear {source}",
                        execute_text=f"/permissions clear {source}",
                        mode="execute",
                    )
                    for source in sources
                    if not fragment or fragment in source
                ]
                return (entries, f"permissions-clear:{fragment}")

        if invocation.name == "plan":
            fragment = invocation.arg_text.strip().lower()
            entries = [
                PaletteEntry("/plan on", "Enter plan mode.", "/plan on", "/plan on", mode="execute"),
                PaletteEntry("/plan off", "Exit plan mode.", "/plan off", "/plan off", mode="execute"),
            ]
            if fragment:
                entries = [
                    entry for entry in entries
                    if fragment in entry.label.lower() or fragment in entry.description.lower()
                ]
            return (entries, f"plan:{fragment}")

        if invocation.name == "copy":
            fragment = invocation.arg_text.strip().lower()
            entries = [
                PaletteEntry("/copy transcript", "Copy the full transcript.", "/copy transcript", "/copy transcript", mode="execute"),
                PaletteEntry("/copy last", "Copy only the latest card.", "/copy last", "/copy last", mode="execute"),
            ]
            if fragment:
                entries = [
                    entry for entry in entries
                    if fragment in entry.label.lower() or fragment in entry.description.lower()
                ]
            return (entries, f"copy:{fragment}")

        if invocation.name == "skills":
            if not invocation.args:
                entries = [
                    PaletteEntry(
                        "/skills list",
                        "List discovered skills.",
                        "/skills list",
                        "/skills list",
                        mode="execute",
                    ),
                    PaletteEntry(
                        "/skills clear",
                        "Clear the next-turn skill queue.",
                        "/skills clear",
                        "/skills clear",
                        mode="execute",
                    ),
                ]
                entries.extend(self._build_skill_palette_entries("", prefix="/skills use "))
                return (entries, "skills:root")
            subcommand = invocation.args[0].lower()
            remainder = invocation.arg_text[len(invocation.args[0]) :].strip().lower()
            if subcommand in {"use", "enable", "select"}:
                return (
                    self._build_skill_palette_entries(remainder, prefix="/skills use "),
                    f"skills-use:{remainder}",
                )

        if invocation.name == "mcp":
            if not invocation.args:
                entries = [
                    PaletteEntry("/mcp list", "List MCP services and connection status.", "/mcp list", "/mcp list"),
                    PaletteEntry("/mcp status", "Show one MCP service in detail.", "/mcp status ", "/mcp status ", mode="insert"),
                    PaletteEntry("/mcp tools", "List tools exposed by one MCP service.", "/mcp tools ", "/mcp tools ", mode="insert"),
                    PaletteEntry("/mcp resources", "List resources exposed by one MCP service.", "/mcp resources ", "/mcp resources ", mode="insert"),
                    PaletteEntry("/mcp refresh", "Refresh one MCP service or all services.", "/mcp refresh ", "/mcp refresh ", mode="insert"),
                    PaletteEntry("/mcp connect", "Connect one MCP service or all services.", "/mcp connect ", "/mcp connect ", mode="insert"),
                    PaletteEntry("/mcp disconnect", "Disconnect one MCP service or all services.", "/mcp disconnect ", "/mcp disconnect ", mode="insert"),
                ]
                return (entries, "mcp:root")
            subcommand = invocation.args[0].lower()
            remainder = invocation.arg_text[len(invocation.args[0]) :].strip().lower()
            if subcommand == "status":
                return (
                    self._build_mcp_palette_entries(remainder, prefix="/mcp status "),
                    f"mcp-status:{remainder}",
                )
            if subcommand == "tools":
                return (
                    self._build_mcp_palette_entries(remainder, prefix="/mcp tools "),
                    f"mcp-tools:{remainder}",
                )
            if subcommand in {"resources", "res"}:
                return (
                    self._build_mcp_palette_entries(remainder, prefix="/mcp resources "),
                    f"mcp-resources:{remainder}",
                )
            if subcommand in {"refresh", "reload"}:
                return (
                    self._build_mcp_palette_entries(remainder, prefix="/mcp refresh ", include_all=True),
                    f"mcp-refresh:{remainder}",
                )
            if subcommand in {"connect", "reconnect"}:
                return (
                    self._build_mcp_palette_entries(remainder, prefix="/mcp connect ", include_all=True),
                    f"mcp-connect:{remainder}",
                )
            if subcommand in {"disconnect", "close"}:
                return (
                    self._build_mcp_palette_entries(remainder, prefix="/mcp disconnect ", include_all=True),
                    f"mcp-disconnect:{remainder}",
                )

        if invocation.name == "worktree":
            if not invocation.args:
                payload = self.engine.get_worktree_status_payload()
                active = payload.get("active") or {}
                description = "Show the current worktree runtime status."
                if active:
                    description = (
                        f"Active: {active.get('branch') or '-'} · {active.get('path') or '-'}"
                    )
                entries = [
                    PaletteEntry("/worktree show", description, "/worktree show", "/worktree show", mode="execute"),
                    PaletteEntry("/worktree enter", "Create and enter a managed worktree.", "/worktree enter ", "/worktree enter ", mode="insert"),
                    PaletteEntry("/worktree exit keep", "Leave the active worktree and keep it on disk.", "/worktree exit keep", "/worktree exit keep", mode="execute"),
                    PaletteEntry("/worktree exit remove discard", "Leave and delete the active worktree, discarding changes.", "/worktree exit remove discard", "/worktree exit remove discard", mode="execute"),
                ]
                return (entries, "worktree:root")
            subcommand = invocation.args[0].lower()
            if subcommand in {"exit", "close"}:
                entries = [
                    PaletteEntry("/worktree exit keep", "Leave the active worktree and keep it on disk.", "/worktree exit keep", "/worktree exit keep", mode="execute"),
                    PaletteEntry("/worktree exit remove", "Leave the active worktree and remove it if clean.", "/worktree exit remove", "/worktree exit remove", mode="execute"),
                    PaletteEntry("/worktree exit remove discard", "Leave and delete the active worktree, discarding changes.", "/worktree exit remove discard", "/worktree exit remove discard", mode="execute"),
                ]
                return (entries, f"worktree-exit:{subcommand}")

        if invocation.name == "agent":
            if not invocation.args:
                entries = [
                    PaletteEntry("/agent list", "List runtime agent handles.", "/agent list", "/agent list", mode="execute"),
                ]
                entries.extend(self._build_agent_palette_entries("", prefix="/agent show "))
                return (entries, "agent:root")
            subcommand = invocation.args[0].lower()
            remainder = invocation.arg_text[len(invocation.args[0]) :].strip().lower()
            if subcommand in {"show", "get"}:
                return (
                    self._build_agent_palette_entries(remainder, prefix=f"/agent {subcommand} "),
                    f"agent-show:{remainder}",
                )
            if subcommand == "wait":
                return (
                    self._build_agent_palette_entries(remainder, prefix="/agent wait "),
                    f"agent-wait:{remainder}",
                )
            if subcommand == "stop":
                return (
                    self._build_agent_palette_entries(remainder, prefix="/agent stop "),
                    f"agent-stop:{remainder}",
                )

        if invocation.name == "task":
            if not invocation.args:
                entries = [
                    PaletteEntry("/tasks", "List structured tasks.", "/tasks", "/tasks", mode="execute"),
                ]
                entries.extend(self._build_task_palette_entries("", prefix="/task show "))
                return (entries, "task:root")
            subcommand = invocation.args[0].lower()
            remainder = invocation.arg_text[len(invocation.args[0]) :].strip().lower()
            if subcommand in {"show", "get"}:
                return (
                    self._build_task_palette_entries(remainder, prefix=f"/task {subcommand} "),
                    f"task-show:{remainder}",
                )
            if subcommand == "output":
                return (
                    self._build_task_palette_entries(remainder, prefix="/task output "),
                    f"task-output:{remainder}",
                )
            if subcommand == "stop":
                return (
                    self._build_task_palette_entries(remainder, prefix="/task stop "),
                    f"task-stop:{remainder}",
                )

        if invocation.name == "session":
            if not invocation.args:
                entries = [
                    PaletteEntry("/session show", "Show the current session details.", "/session show", "/session show"),
                    PaletteEntry("/session list", "List saved S4Code sessions.", "/session list", "/session list"),
                    PaletteEntry("/session timeline", "Show checkpoint and trace timeline.", "/session timeline", "/session timeline", mode="execute"),
                    PaletteEntry("/session checkpoints", "List restorable checkpoints.", "/session checkpoints", "/session checkpoints", mode="execute"),
                    PaletteEntry("/session tree", "Show fork/restore session tree.", "/session tree", "/session tree", mode="execute"),
                    PaletteEntry("/session rewind", "Restore history to a checkpoint.", "/session rewind ", "/session rewind ", mode="insert"),
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
            if subcommand == "rewind":
                return (
                    self._build_checkpoint_palette_entries(remainder, prefix="/session rewind "),
                    f"session-rewind:{remainder}",
                )

        if invocation.name == "rewind":
            fragment = invocation.arg_text.strip().lower()
            return (
                self._build_checkpoint_palette_entries(fragment, prefix="/rewind "),
                f"rewind:{fragment}",
            )

        if invocation.name in {"checkpoint", "checkpoints"}:
            fragment = invocation.arg_text.strip().lower()
            entries = [
                PaletteEntry("/checkpoint list", "List restorable checkpoints.", "/checkpoint list", "/checkpoint list", mode="execute"),
                PaletteEntry("/checkpoint", "Create a checkpoint with an optional label.", "/checkpoint ", "/checkpoint ", mode="insert"),
            ]
            if fragment:
                entries = [
                    entry for entry in entries
                    if fragment in entry.label.lower() or fragment in entry.description.lower()
            ]
            return (entries, f"checkpoint:{fragment}")

        if invocation.name == "sidebar":
            fragment = invocation.arg_text.strip().lower()
            entries = [
                PaletteEntry("/sidebar show", "Show the right-side info panel.", "/sidebar show", "/sidebar show", mode="execute"),
                PaletteEntry("/sidebar hide", "Hide the right-side info panel.", "/sidebar hide", "/sidebar hide", mode="execute"),
            ]
            if fragment:
                entries = [
                    entry for entry in entries
                    if fragment in entry.label.lower() or fragment in entry.description.lower()
                ]
            return (entries, f"sidebar:{fragment}")

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

    def _build_skill_palette_entries(self, fragment: str, *, prefix: str) -> list[PaletteEntry]:
        entries: list[PaletteEntry] = []
        for item in self.engine.get_skill_choices():
            name = str(item["name"])
            listing = str(item.get("listing_description") or item.get("description") or name)
            source = str(item.get("source_path") or item.get("source_type") or "-")
            search_blob = " ".join(
                [
                    name,
                    listing,
                    str(item.get("when_to_use") or ""),
                    source,
                ]
            ).lower()
            if fragment and fragment not in search_blob:
                continue
            marker = "* " if item.get("pending") else ""
            entries.append(
                PaletteEntry(
                    label=f"{marker}{name}",
                    description=f"{item.get('exposure_mode')}/{item.get('execution_mode')} · {listing} · {source}",
                    insert_text=f"{prefix}{name}",
                    execute_text=f"{prefix}{name}",
                    mode="execute",
                )
            )
        return entries

    def _build_agent_palette_entries(self, fragment: str, *, prefix: str) -> list[PaletteEntry]:
        entries: list[PaletteEntry] = []
        for item in self.engine.get_agent_choices():
            agent_id = str(item.get("agent_id") or "")
            status = str(item.get("status") or "-")
            name = str(item.get("name") or "-")
            task_id = str(item.get("task_id") or "-")
            output_file = str(item.get("output_file") or "-")
            search_blob = " ".join([agent_id, status, name, task_id, output_file]).lower()
            if fragment and fragment not in search_blob:
                continue
            entries.append(
                PaletteEntry(
                    label=agent_id,
                    description=f"{status} · {name} · task={task_id} · output={output_file}",
                    insert_text=f"{prefix}{agent_id}",
                    execute_text=f"{prefix}{agent_id}",
                    mode="execute",
                )
            )
        return entries

    def _build_task_palette_entries(self, fragment: str, *, prefix: str) -> list[PaletteEntry]:
        entries: list[PaletteEntry] = []
        for item in self.engine.get_task_choices():
            task_id = str(item.get("task_id") or "")
            status = str(item.get("status") or "-")
            title = str(item.get("title") or task_id)
            kind = str(item.get("kind") or "-")
            search_blob = " ".join([task_id, status, title, kind]).lower()
            if fragment and fragment not in search_blob:
                continue
            entries.append(
                PaletteEntry(
                    label=task_id,
                    description=f"{status} · {kind} · {title}",
                    insert_text=f"{prefix}{task_id}",
                    execute_text=f"{prefix}{task_id}",
                    mode="execute",
                )
            )
        return entries

    def _build_checkpoint_palette_entries(self, fragment: str, *, prefix: str) -> list[PaletteEntry]:
        entries: list[PaletteEntry] = []
        for item in self.engine.get_checkpoint_choices():
            checkpoint_id = str(item.get("checkpoint_id") or "")
            label = str(item.get("label") or checkpoint_id)
            reason = str(item.get("reason") or "-")
            created_at = str(item.get("created_at") or "-")
            search_blob = " ".join([checkpoint_id, label, reason, created_at]).lower()
            if fragment and fragment not in search_blob:
                continue
            entries.append(
                PaletteEntry(
                    label=checkpoint_id,
                    description=f"{label} · {reason} · {created_at}",
                    insert_text=f"{prefix}{checkpoint_id}",
                    execute_text=f"{prefix}{checkpoint_id}",
                    mode="execute",
                )
            )
        if not entries and not fragment:
            entries.append(
                PaletteEntry(
                    label="last",
                    description="Rewind to the latest checkpoint.",
                    insert_text=f"{prefix}last",
                    execute_text=f"{prefix}last",
                    mode="execute",
                )
            )
        return entries

    def _build_mcp_palette_entries(self, fragment: str, *, prefix: str, include_all: bool = False) -> list[PaletteEntry]:
        entries: list[PaletteEntry] = []
        if include_all and (not fragment or "all".startswith(fragment)):
            entries.append(
                PaletteEntry(
                    label="all",
                    description="Apply this action to all MCP services.",
                    insert_text=prefix.rstrip(),
                    execute_text=prefix.rstrip(),
                    mode="execute",
                )
            )
        for item in self.engine.get_mcp_status_payload(include_capabilities=False):
            server_name = str(item.get("server_name") or "").strip()
            if not server_name:
                continue
            status = str(item.get("status") or "-").strip()
            transport = str(item.get("transport_summary") or "-").strip()
            last_error = str(item.get("last_error") or "").strip()
            search_blob = " ".join([server_name, status, transport, last_error]).lower()
            if fragment and fragment not in search_blob:
                continue
            marker = "* " if status == "connected" else ""
            description = f"{status} · {transport}"
            if last_error:
                description += f" · {last_error}"
            entries.append(
                PaletteEntry(
                    label=f"{marker}{server_name}",
                    description=description,
                    insert_text=f"{prefix}{server_name}",
                    execute_text=f"{prefix}{server_name}",
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

    def _refresh_sidebar(self, *, force: bool = False) -> None:
        sidebar = self.query_one("#sidebar", Static)
        if not bool(sidebar.display):
            return
        now = time.monotonic()
        if not force and (now - self._last_sidebar_refresh_at) < 0.75:
            return
        content = self.engine.format_sidebar(force=force)
        self._last_sidebar_refresh_at = now
        self._sidebar_dirty = False
        if content == self._last_sidebar_content:
            return
        self._last_sidebar_content = content
        sidebar.update(content)

    def _apply_sidebar_visibility(self) -> None:
        sidebar = self.query_one("#sidebar", Static)
        visible = bool(getattr(self.engine, "sidebar_visible", False))
        sidebar.display = visible
        if visible:
            self._mark_sidebar_dirty()
