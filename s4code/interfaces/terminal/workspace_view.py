"""Workspace listings and diff presentation."""

from __future__ import annotations

from typing import Any, Optional


class WorkspacePresenter:
    def __init__(self, controller):
        self.controller = controller

    def _capture_working_tree_diff(self) -> str:
        try:
            diff = self.controller.project.get_diff(max_lines=1200)
        except Exception:
            return ""
        normalized = str(diff or "").strip()
        if normalized in {"", "No diff.", "Not a git repository."}:
            return ""
        return normalized

    def _maybe_attach_bash_diff(
        self,
        event: dict[str, Any],
        *,
        before_diff: str,
    ) -> dict[str, Any]:
        after_diff = self._capture_working_tree_diff()
        if not after_diff or after_diff == before_diff:
            return event
        updated = dict(event)
        structured_data = dict(updated.get("structured_data") or {})
        existing_diff = structured_data.get("diff")
        if (
            not isinstance(existing_diff, dict)
            or not str(existing_diff.get("unified") or "").strip()
        ):
            structured_data["diff"] = {
                "unified": after_diff,
                "file_path": str(self.controller.project.project_root),
                "relative_path": "Working tree diff after Bash",
                "created": False,
                "source": "bash",
            }
            updated["structured_data"] = structured_data
        return updated

    def format_files(self, relative_path: str = ".", *, limit: int = 200) -> str:
        files = self.controller.project.list_files(relative_path, limit=limit)
        if not files:
            return f"No files found under {relative_path!r}."
        return "\n".join(files)

    def format_diff(self, target: Optional[str] = None) -> str:
        return self.controller.project.get_diff(target=target)
