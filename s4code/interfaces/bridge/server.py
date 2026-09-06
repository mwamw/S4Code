"""Headless NDJSON transport for S4Code Core. No terminal dependencies."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import aclosing, redirect_stdout
import json
import os
from pathlib import Path
import sys

from pydantic import ValidationError
from s4code.core.application import S4CodeRuntime
from s4code.core.errors import BusyError, InvalidRequestError, S4CodeError
from .core_handlers import CoreRequest, CoreRequestHandler, StreamParams

PROTOCOL_VERSION = 1
_protocol_output = sys.stdout


def _error_payload(exc):
    code = (
        exc.code
        if isinstance(exc, S4CodeError)
        else "invalid_request"
        if isinstance(exc, (ValueError, ValidationError))
        else "internal_error"
    )
    message = (
        str(exc) if code != "internal_error" else "The operation could not be completed"
    )
    print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
    return {"code": code, "message": message}


def _emit_response(request_id, payload):
    _protocol_output.write(
        json.dumps({"request_id": request_id, **payload}, ensure_ascii=False) + "\n"
    )
    _protocol_output.flush()


class BridgeServer:
    def __init__(
        self,
        *,
        cwd=None,
        session_id=None,
        transient_session=False,
        ignore_session_model_overrides=False,
        background_streams=True,
        runtime=None,
    ):
        self.runtime = runtime or S4CodeRuntime(cwd=cwd)
        try:
            overrides = (
                {"product": {"session_auto_save": False}} if transient_session else None
            )
            self.session = self.runtime.open_session(
                session_id,
                overrides=overrides,
                ignore_saved_model=ignore_session_model_overrides,
            )
        except BaseException:
            if runtime is None:
                self.runtime.close()
            raise
        self.background_streams = background_streams
        self.active_streams = {}
        self._stream_sessions = {}
        self.closed = False

    def emit(self, request_id, payload):
        _emit_response(request_id, payload)

    async def shutdown(self):
        if self.closed:
            return
        for request_id, task in list(self.active_streams.items()):
            self._stream_sessions[request_id].runs.cancel("Bridge closed")
            task.cancel()
        if self.active_streams:
            await asyncio.gather(
                *list(self.active_streams.values()), return_exceptions=True
            )
        self.active_streams.clear()
        self._stream_sessions.clear()
        self.runtime.close()
        self.closed = True

    async def _stream(self, request_id, session, params):
        try:
            async with aclosing(
                session.stream(params.prompt, {"max_iter": params.max_iter})
            ) as events:
                async for event in events:
                    self.emit(
                        request_id,
                        {"type": "event", "event": event.model_dump(mode="json")},
                    )
            result = session.runs.last_result.model_dump(mode="json")
            self.emit(request_id, {"type": "response", "ok": True, "result": result})
        except asyncio.CancelledError:
            result = session.runs.last_result
            self.emit(
                request_id,
                {
                    "type": "response",
                    "ok": True,
                    "result": result.model_dump(mode="json")
                    if result
                    else {"session_id": session.id, "status": "cancelled", "text": ""},
                },
            )
        except Exception as exc:
            self.emit(
                request_id,
                {"type": "response", "ok": False, "error": _error_payload(exc)},
            )
        finally:
            self.active_streams.pop(request_id, None)
            self._stream_sessions.pop(request_id, None)

    async def dispatch(self, request):
        request = CoreRequest.model_validate(request)
        rid, method, params = request.request_id, request.method, request.params
        if self.closed:
            raise InvalidRequestError("Bridge is closed")
        if method == "initialize":
            if (
                set(params) - {"protocol_version"}
                or params.get("protocol_version") != PROTOCOL_VERSION
            ):
                raise InvalidRequestError("Unsupported protocol version")
            result = {
                "protocol_version": PROTOCOL_VERSION,
                "capabilities": ["sessions", "stream", "interactions", "snapshots"],
                "session_id": self.session.id,
            }
        elif method == "shutdown":
            if params:
                raise InvalidRequestError("shutdown accepts no parameters")
            await self.shutdown()
            result = {"closed": True}
        elif method == "core.stream":
            p = StreamParams.model_validate(params)
            session = (
                self.runtime.open_session(p.session_id)
                if p.session_id
                else self.session
            )
            if rid in self.active_streams:
                raise InvalidRequestError("Duplicate active request ID")
            if session in self._stream_sessions.values() or session.runs.active_run_id:
                raise BusyError("Session already has an active run")
            if self.background_streams:
                self._stream_sessions[rid] = session
                self.active_streams[rid] = asyncio.create_task(
                    self._stream(rid, session, p)
                )
                # Establish Core ownership before accepting a cancel/close request.
                await asyncio.sleep(0)
            else:
                await self._stream(rid, session, p)
            return
        else:
            result = CoreRequestHandler(self.session, self.runtime).handle(
                method, params
            )
            if method == "core.stop" and result["stop_requested"]:
                target = params.get("session_id") or self.session.id
                tasks = [
                    task
                    for key, task in list(self.active_streams.items())
                    if self._stream_sessions[key].id == target
                ]
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
        self.emit(rid, {"type": "response", "ok": True, "result": result})


async def _serve(*, request_json=None, request_file=None, **options):
    server = BridgeServer(**options, background_streams=request_json is None)

    async def handle(raw):
        rid = "unknown"
        try:
            request = json.loads(raw)
            if not isinstance(request, dict):
                raise InvalidRequestError("Request must be an object")
            rid = str(request.get("request_id") or rid)
            await server.dispatch(request)
            return True
        except Exception as exc:
            _emit_response(
                rid, {"type": "response", "ok": False, "error": _error_payload(exc)}
            )
            return False

    try:
        if request_json is not None:
            return 0 if await handle(request_json) else 1
        if request_file:
            position = 0
            while not server.closed:
                with Path(request_file).open(encoding="utf-8") as handle_file:
                    handle_file.seek(position)
                    while not server.closed:
                        before = handle_file.tell()
                        line = handle_file.readline()
                        if not line.endswith("\n"):
                            position = before
                            break
                        position = handle_file.tell()
                        if line.strip():
                            await handle(line)
                await asyncio.sleep(0.02)
        else:
            loop = asyncio.get_running_loop()
            reader = asyncio.StreamReader(limit=16 * 1024 * 1024)
            protocol = asyncio.StreamReaderProtocol(reader)
            transport, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin)
            try:
                while not server.closed:
                    line = await reader.readline()
                    if not line:
                        break
                    if line.strip():
                        await handle(line.decode("utf-8"))
            finally:
                transport.close()
        return 0
    finally:
        await server.shutdown()


def run_server(**options):
    try:
        with redirect_stdout(sys.stderr):
            return asyncio.run(_serve(**options))
    except Exception as exc:
        _emit_response(
            "unknown", {"type": "response", "ok": False, "error": _error_payload(exc)}
        )
        return 1


def run_single_request(**options):
    return run_server(**options)


def main(argv=None):
    parser = argparse.ArgumentParser(description="S4Code Core bridge")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--session-id")
    parser.add_argument("--transient-session", action="store_true")
    parser.add_argument("--ignore-session-model-overrides", action="store_true")
    parser.add_argument("--request-json")
    parser.add_argument("--request-file")
    options = vars(parser.parse_args(argv))
    options["transient_session"] |= os.environ.get("S4CODE_TRANSIENT_SESSION") == "1"
    return run_server(**options)


if __name__ == "__main__":
    raise SystemExit(main())
