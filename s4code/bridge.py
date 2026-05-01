"""NDJSON bridge for the TypeScript S4Code frontend."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any, Optional

from .query_engine import S4QueryEngine


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


class BridgeSession:
    def __init__(self, *, cwd: str | Path, session_id: Optional[str] = None) -> None:
        self.cwd = Path(cwd).resolve()
        self._session_id = session_id
        self.engine = self._create_engine(session_id=session_id)

    def _create_engine(self, *, session_id: Optional[str]) -> S4QueryEngine:
        return S4QueryEngine(cwd=self.cwd, session_id=session_id)

    def close(self) -> None:
        try:
            self.engine.close()
        except Exception:
            pass

    def reset_engine(self, *, session_id: Optional[str]) -> None:
        self.close()
        self._session_id = session_id
        self.engine = self._create_engine(session_id=session_id)

    @staticmethod
    def _permission_mode(engine: S4QueryEngine) -> str:
        permission_context = getattr(engine.agent, "permission_context", None)
        mode = getattr(permission_context, "mode", None)
        return str(getattr(mode, "value", mode) or "-")

    def init_payload(self) -> dict[str, Any]:
        saver = getattr(self.engine, "save_session", None)
        if callable(saver):
            try:
                saver(tolerate_failure=True)
            except Exception:
                pass
        return {
            "cwd": str(self.cwd),
            "session_id": self.engine.session_id,
            "project_name": self.engine.project.project_name,
            "project_root": str(self.engine.project.project_root),
            "branch": self.engine.project.branch or "-",
            "model": getattr(self.engine.agent.llm, "model", "-"),
            "provider": getattr(self.engine.agent.llm, "provider_name", "-"),
            "permission_mode": self._permission_mode(self.engine),
            "welcome": self.engine.get_welcome_notice(),
            "startup_notices": self.engine.get_startup_notices(),
            "sidebar": self.engine.get_sidebar_payload(force=True),
            "context": self.engine.get_context_panel_payload(),
            "restore": self.engine.get_restore_continuity_payload(),
            "pending": self.engine.get_pending_risk_payload(),
        }

    def render_view(self, view: str, params: dict[str, Any]) -> dict[str, Any]:
        engine = self.engine
        view_name = str(view or "").strip().lower()
        if view_name == "help":
            return {"title": "Help", "text": engine.format_help()}
        if view_name == "status":
            return {"title": "Status", "text": engine.format_status_overview()}
        if view_name == "context":
            return {"title": "Context", "text": engine.format_context(), "payload": engine.get_context_panel_payload()}
        if view_name == "cost":
            return {"title": "Cost", "text": engine.format_cost()}
        if view_name == "trace":
            limit_turns = int(params.get("limit_turns") or 5)
            return {"title": "Trace", "text": engine.format_trace(limit_turns=limit_turns)}
        if view_name == "tools":
            return {"title": "Tools", "text": engine.format_tools()}
        if view_name == "skills":
            return {"title": "Skills", "text": engine.format_skills()}
        if view_name == "worktree":
            return {"title": "Worktree", "text": engine.format_worktree_status(), "payload": engine.get_worktree_status_payload()}
        if view_name == "mcp":
            return {"title": "MCP", "text": engine.format_mcp()}
        if view_name == "sessions":
            limit = int(params.get("limit") or 20)
            return {"title": "Sessions", "text": engine.format_sessions(limit=limit)}
        if view_name == "restore":
            return {"title": "Restore", "text": engine.format_restore_report(), "payload": engine.get_restore_continuity_payload()}
        if view_name == "pending":
            return {"title": "Pending", "text": engine.format_pending_interaction(), "payload": engine.get_pending_risk_payload()}
        if view_name == "tasks":
            limit = int(params.get("limit") or 20)
            return {"title": "Tasks", "text": engine.format_tasks(limit=limit)}
        if view_name == "task_detail":
            task_id = str(params.get("task_id") or "").strip()
            return {"title": f"Task {task_id or '-'}", "text": engine.format_task_detail(task_id)}
        if view_name == "task_output":
            task_id = str(params.get("task_id") or "").strip()
            block = bool(params.get("block"))
            timeout_ms = params.get("timeout_ms")
            timeout_arg = int(timeout_ms) if timeout_ms is not None else None
            return {
                "title": f"Task Output {task_id or '-'}",
                "text": engine.format_task_output(task_id, block=block, timeout_ms=timeout_arg),
            }
        if view_name == "diff":
            target = str(params.get("target") or "").strip() or None
            return {"title": "Diff", "text": engine.format_diff(target=target)}
        if view_name == "doctor":
            return {"title": "Doctor", "text": engine.format_doctor()}
        if view_name == "runtime":
            getter = getattr(engine, "get_runtime_snapshot_payload", None)
            payload = getter() if callable(getter) else None
            return {"title": "Runtime", "text": engine.format_runtime_panel(), "payload": payload}
        raise ValueError(f"Unknown view: {view_name}")

    def build_prompt(self, kind: str, params: dict[str, Any]) -> dict[str, Any]:
        prompt_kind = str(kind or "").strip().lower()
        if prompt_kind == "review":
            target = str(params.get("target") or "").strip() or None
            builder = getattr(self.engine, "build_review_prompt", None)
            if not callable(builder):
                raise ValueError("review prompt builder is unavailable")
            return {"prompt": builder(target)}
        raise ValueError(f"Unknown prompt kind: {prompt_kind}")

    def run_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        engine = self.engine
        action_name = str(action or "").strip().lower()
        if action_name == "load_session":
            session_id = str(params.get("session_id") or "").strip() or None
            if not session_id:
                raise ValueError("load_session requires session_id")
            self.reset_engine(session_id=session_id)
            return {
                "text": f"Loaded session {self.engine.session_id}.",
                "init": self.init_payload(),
            }
        if action_name == "set_model":
            target = str(params.get("target") or "").strip()
            updater = getattr(engine, "update_model", None)
            if not callable(updater):
                raise ValueError("Model switching is unavailable")
            return {"text": updater(target)}
        if action_name == "set_permission_mode":
            mode = str(params.get("mode") or "").strip()
            updater = getattr(engine, "update_permission_mode", None)
            if not callable(updater):
                raise ValueError("Permission mode switching is unavailable")
            return {"text": updater(mode)}
        if action_name == "compact_history":
            max_tokens = params.get("max_tokens")
            max_tokens_arg = int(max_tokens) if max_tokens is not None else None
            return {"text": engine.compact_history(max_tokens=max_tokens_arg)}
        if action_name == "queue_skill":
            name = str(params.get("name") or "").strip()
            queuer = getattr(engine, "queue_turn_skill", None)
            if not callable(queuer):
                raise ValueError("Skill queueing is unavailable")
            return {"text": queuer(name)}
        if action_name == "clear_turn_skills":
            clearer = getattr(engine, "clear_turn_skills", None)
            if not callable(clearer):
                raise ValueError("Skill clearing is unavailable")
            return {"text": clearer()}
        if action_name == "enter_worktree":
            name = str(params.get("name") or "").strip() or None
            enter = getattr(engine, "enter_worktree", None)
            if not callable(enter):
                raise ValueError("Worktree entry is unavailable")
            return {"text": enter(name)}
        if action_name == "exit_worktree":
            exit_worktree = getattr(engine, "exit_worktree", None)
            if not callable(exit_worktree):
                raise ValueError("Worktree exit is unavailable")
            return {
                "text": exit_worktree(
                    action=str(params.get("action") or "keep"),
                    discard_changes=bool(params.get("discard_changes")),
                )
            }
        if action_name == "stop_task":
            task_id = str(params.get("task_id") or "").strip()
            stopper = getattr(engine, "stop_task", None)
            if not callable(stopper):
                raise ValueError("Task stopping is unavailable")
            return {"text": stopper(task_id)}
        raise ValueError(f"Unknown action: {action_name}")


class BridgeServer:
    def __init__(self, *, cwd: str | Path, session_id: Optional[str] = None) -> None:
        self.session = BridgeSession(cwd=cwd, session_id=session_id)

    def emit(self, request_id: str, payload: dict[str, Any]) -> None:
        envelope = {
            "request_id": request_id,
            **payload,
        }
        sys.stdout.write(json.dumps(envelope, ensure_ascii=False, default=_json_default) + "\n")
        sys.stdout.flush()

    async def _handle_stream_prompt(self, request_id: str, params: dict[str, Any]) -> None:
        prompt = params.get("prompt")
        if not isinstance(prompt, str):
            raise ValueError("submit_prompt requires prompt")
        max_iter = int(params.get("max_iter") or 20)
        async for event in self.session.engine.stream_prompt(prompt, max_iter=max_iter):
            self.emit(
                request_id,
                {
                    "type": "event",
                    "event": dict(event),
                },
            )
        self.emit(
            request_id,
            {
                "type": "response",
                "ok": True,
                "result": {
                    "done": True,
                    "sidebar": self.session.engine.get_sidebar_payload(force=True),
                },
            },
        )

    async def _handle_resolve_pending(self, request_id: str, params: dict[str, Any]) -> None:
        action = str(params.get("action") or "").strip()
        answer = str(params.get("answer") or "")
        max_iter = int(params.get("max_iter") or 20)
        async for event in self.session.engine.stream_resolve_pending_interaction(
            action=action,
            answer=answer,
            max_iter=max_iter,
        ):
            self.emit(
                request_id,
                {
                    "type": "event",
                    "event": dict(event),
                },
            )
        self.emit(
            request_id,
            {
                "type": "response",
                "ok": True,
                "result": {
                    "done": True,
                    "sidebar": self.session.engine.get_sidebar_payload(force=True),
                },
            },
        )

    async def dispatch(self, request: dict[str, Any]) -> None:
        request_id = str(request.get("request_id") or "").strip()
        method = str(request.get("method") or "").strip()
        params = request.get("params") or {}
        if not request_id:
            raise ValueError("request_id is required")
        if not isinstance(params, dict):
            raise ValueError("params must be an object")

        if method == "submit_prompt":
            await self._handle_stream_prompt(request_id, params)
            return
        if method == "resolve_pending":
            await self._handle_resolve_pending(request_id, params)
            return

        if method == "init":
            result = self.session.init_payload()
        elif method == "render_view":
            result = self.session.render_view(str(params.get("view") or ""), params)
        elif method == "build_prompt":
            result = self.session.build_prompt(str(params.get("kind") or ""), params)
        elif method == "action":
            result = self.session.run_action(str(params.get("action") or ""), params)
        elif method == "get_sidebar_payload":
            result = self.session.engine.get_sidebar_payload(force=bool(params.get("force")))
        elif method == "get_context_panel":
            result = self.session.engine.get_context_panel_payload()
        elif method == "get_restore_summary":
            result = self.session.engine.get_restore_continuity_payload()
        elif method == "get_pending":
            result = self.session.engine.get_pending_risk_payload()
        elif method == "poll_runtime_notices":
            result = {
                "notices": self.session.engine.poll_runtime_notices(),
                "sidebar": self.session.engine.get_sidebar_payload(force=True),
            }
        elif method == "shutdown":
            self.session.close()
            result = {"closed": True}
        else:
            raise ValueError(f"Unknown method: {method}")

        self.emit(
            request_id,
            {
                "type": "response",
                "ok": True,
                "result": result,
            },
        )


def run_server(*, cwd: str | Path, session_id: Optional[str]) -> int:
    server = BridgeServer(cwd=cwd, session_id=session_id)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            raw = str(line).strip()
            if not raw:
                continue
            request_id = ""
            try:
                request = json.loads(raw)
                if not isinstance(request, dict):
                    raise ValueError("request must be an object")
                request_id = str(request.get("request_id") or "").strip()
                loop.run_until_complete(server.dispatch(request))
            except Exception as exc:
                server.emit(
                    request_id or "unknown",
                    {
                        "type": "response",
                        "ok": False,
                        "error": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
    finally:
        server.session.close()
        loop.run_until_complete(loop.shutdown_asyncgens())
        asyncio.set_event_loop(None)
        loop.close()
    return 0


def run_single_request(*, cwd: str | Path, session_id: Optional[str], request_json: str) -> int:
    server = BridgeServer(cwd=cwd, session_id=session_id)
    request_id = ""
    try:
        request = json.loads(request_json)
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        request_id = str(request.get("request_id") or "").strip()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(server.dispatch(request))
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            asyncio.set_event_loop(None)
            loop.close()
    except Exception as exc:
        server.emit(
            request_id or "unknown",
            {
                "type": "response",
                "ok": False,
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            },
        )
        return 1
    finally:
        server.session.close()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="S4Code TypeScript bridge")
    parser.add_argument("--cwd", default=".", help="Working directory")
    parser.add_argument("--session-id", default=None, help="Optional session id to resume")
    parser.add_argument("--request-json", default=None, help="Optional one-shot request payload")
    args = parser.parse_args(argv)
    if args.request_json:
        return run_single_request(cwd=args.cwd, session_id=args.session_id, request_json=args.request_json)
    return run_server(cwd=args.cwd, session_id=args.session_id)


if __name__ == "__main__":
    raise SystemExit(main())
