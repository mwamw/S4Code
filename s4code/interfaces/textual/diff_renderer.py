"""Textual UI for S4Code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from rich.box import ROUNDED
from rich.console import Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual.widgets import Static

from s4code.interfaces.terminal.transcript import TranscriptCard


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


class DiffRenderer:
    def __init__(self, app):
        self.app = app

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
            renderables.append(
                Text(summary, style=self.app._theme_value("diff.summary", "#e2e8f0"))
            )
        header = self._render_diff_prelude(parsed.prelude, diff_payload)
        if header is not None:
            renderables.append(header)
        lexer = self._guess_diff_lexer(diff_payload)
        hidden_hunks = max(len(parsed.hunks) - MAX_DIFF_HUNKS_RENDERED, 0)
        for index, hunk in enumerate(parsed.hunks[:MAX_DIFF_HUNKS_RENDERED], start=1):
            visible_lines = hunk.lines[:MAX_DIFF_LINES_PER_HUNK]
            renderables.append(
                Panel(
                    self._render_diff_hunk(
                        DiffHunk(hunk.header, tuple(visible_lines)), lexer
                    ),
                    title=hunk.header,
                    title_align="left",
                    border_style=self.app._theme_value("diff.hunk_border", "#334155"),
                    box=ROUNDED,
                    padding=(0, 1),
                )
            )
            hidden_lines = max(len(hunk.lines) - len(visible_lines), 0)
            if hidden_lines > 0:
                renderables.append(
                    Text(
                        f"... {hidden_lines} more line(s) hidden in this hunk",
                        style=self.app._theme_value("diff.summary", "#94a3b8"),
                    )
                )
        if hidden_hunks > 0:
            renderables.append(
                Text(
                    f"... {hidden_hunks} more hunk(s) hidden",
                    style=self.app._theme_value("diff.summary", "#94a3b8"),
                )
            )
        if len(renderables) == 1 and summary:
            return renderables[0]
        if not renderables:
            return Syntax(diff_text, "diff", theme="monokai", word_wrap=True)
        return Group(*renderables)

    def _render_diff_prelude(
        self, lines: tuple[str, ...], diff_payload: dict[str, Any]
    ) -> Optional[Panel]:
        if (
            not lines
            and not diff_payload.get("relative_path")
            and not diff_payload.get("file_path")
        ):
            return None
        body = Text()
        relative_path = str(diff_payload.get("relative_path") or "").strip()
        file_path = str(diff_payload.get("file_path") or "").strip()
        label = relative_path or file_path
        if label:
            body.append(
                label, style=self.app._theme_value("diff.file_label", "bold #bfdbfe")
            )
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
            border_style=self.app._theme_value("diff.prelude_border", "#475569"),
            box=ROUNDED,
            padding=(0, 1),
        )

    def _render_diff_prelude_line(self, line: str) -> Text:
        if line.startswith("diff --git"):
            return Text(
                line, style=self.app._theme_value("diff.git_header", "bold #93c5fd")
            )
        if line.startswith("new file mode"):
            return Text(line, style=self.app._theme_value("diff.new_file", "#86efac"))
        if line.startswith("--- "):
            return Text(
                line, style=self.app._theme_value("diff.deleted_file", "#fca5a5")
            )
        if line.startswith("+++ "):
            return Text(line, style=self.app._theme_value("diff.new_file", "#86efac"))
        return Text(line, style=self.app._theme_value("diff.prelude", "#94a3b8"))

    def _guess_diff_lexer(self, diff_payload: dict[str, Any]) -> str:
        file_path = str(
            diff_payload.get("file_path") or diff_payload.get("relative_path") or ""
        ).strip()
        if not file_path:
            return "text"
        cached = self.app._diff_lexer_cache.get(file_path)
        if cached is not None:
            return cached
        code_sample = self._diff_code_sample(str(diff_payload.get("unified") or ""))
        try:
            lexer = Syntax.guess_lexer(file_path, code=code_sample or None)
        except Exception:
            lexer = "text"
        self.app._diff_lexer_cache[file_path] = lexer
        return lexer

    @staticmethod
    def _diff_code_sample(diff_text: str) -> str:
        sample_lines: list[str] = []
        for line in diff_text.splitlines():
            if line.startswith(
                ("diff --git", "--- ", "+++ ", "@@ ", "new file mode", "index ")
            ):
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
                prefix_style=self.app._theme_value(
                    "diff.add_prefix", "bold #4ade80 on #052e16"
                ),
                body_background=self.app._theme_value("diff.add_background", "#052e16"),
            )
        if line.startswith("-"):
            return self._render_code_diff_line(
                prefix="-",
                body=line[1:],
                highlighter=highlighter,
                prefix_style=self.app._theme_value(
                    "diff.delete_prefix", "bold #f87171 on #3f1111"
                ),
                body_background=self.app._theme_value(
                    "diff.delete_background", "#3f1111"
                ),
            )
        if line.startswith(" "):
            return self._render_code_diff_line(
                prefix=" ",
                body=line[1:],
                highlighter=highlighter,
                prefix_style=self.app._theme_value("diff.context_prefix", "#64748b"),
            )
        if line.startswith("\\"):
            return Text(
                line, style=self.app._theme_value("diff.escape", "italic #94a3b8")
            )
        return Text(line, style=self.app._theme_value("diff.plain", "#cbd5e1"))

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
            body_text = (
                highlighter.highlight(body) if highlighter is not None else Text(body)
            )
        except Exception:
            body_text = Text(body)
        if body_background:
            body_text.stylize(f"on {body_background}")
        rendered.append_text(body_text)
        return rendered
