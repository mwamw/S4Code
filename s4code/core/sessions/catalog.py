"""S4Code session helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


from easyagent.session import SQLiteSessionStore

from s4code.core.paths import S4Paths
from s4code.core.project import ProjectContext


def _normalize_project_root(value: str | Path | None) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    return str(Path(raw).expanduser().resolve())


@dataclass(slots=True)
class S4SessionSummary:
    session_id: str
    agent_name: str
    title: str
    updated_at: Optional[datetime]
    model: Optional[str]
    provider: Optional[str]
    project_root: Optional[str]
    permission_mode: Optional[str]
    branch: Optional[str] = None
    forked_from_session_id: Optional[str] = None


class SessionCatalog:
    def __init__(self, paths: S4Paths, *, store=None):
        self.paths = paths.ensure()
        self.store = (
            store
            if store is not None
            else SQLiteSessionStore(str(self.paths.session_db_path))
        )

    def new_session_id(self, project: ProjectContext) -> str:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"s4-{project.project_name}-{timestamp}-{uuid4().hex[:6]}"

    def build_metadata(
        self,
        *,
        project: ProjectContext,
        title: str,
        settings_payload: dict[str, Any],
        session_overrides: dict[str, Any],
        forked_from_session_id: Optional[str] = None,
    ) -> dict[str, Any]:
        llm_payload = dict(settings_payload.get("llm") or {})
        product_payload = dict(settings_payload.get("product") or {})
        return {
            "product": "s4code",
            "title": title,
            "project_root": str(project.project_root),
            "project_name": project.project_name,
            "branch": project.branch,
            "active_model_profile": settings_payload.get("active_model_profile"),
            "model": llm_payload.get("model"),
            "provider": llm_payload.get("provider"),
            "permission_mode": product_payload.get("permission_mode"),
            "session_overrides": session_overrides,
            "forked_from_session_id": forked_from_session_id,
        }

    def list_sessions(
        self, *, limit: int = 30, project_root: str | Path | None = None
    ) -> list[S4SessionSummary]:
        target_project_root = _normalize_project_root(project_root)
        filters = {"product": "s4code"}
        if target_project_root is not None:
            filters["project_root"] = target_project_root
        items = self.store.list_sessions(limit=limit, metadata_filter=filters)
        result: list[S4SessionSummary] = []
        for item in items:
            metadata = dict(item.get("metadata") or {})
            if metadata.get("product") != "s4code":
                continue
            item_project_root = _normalize_project_root(metadata.get("project_root"))
            if (
                target_project_root is not None
                and item_project_root != target_project_root
            ):
                continue
            result.append(
                S4SessionSummary(
                    session_id=str(item["session_id"]),
                    agent_name=str(item["agent_name"]),
                    title=str(metadata.get("title") or item["session_id"]),
                    updated_at=item.get("updated_at"),
                    model=metadata.get("model"),
                    provider=metadata.get("provider"),
                    project_root=item_project_root,
                    permission_mode=metadata.get("permission_mode"),
                    branch=metadata.get("branch"),
                    forked_from_session_id=metadata.get("forked_from_session_id"),
                )
            )
            if len(result) >= limit:
                break
        return result

    def get_record(self, session_id: str) -> Optional[dict[str, Any]]:
        return self.store.get_session(session_id)
