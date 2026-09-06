"""Run lifecycle over BasicAgent execution, not another agent loop."""

import asyncio
from contextlib import aclosing, contextmanager, suppress
from uuid import uuid4

from easyagent.errors import ToolInterruption
from easyagent.runtime import RuntimeEventType

from .contracts import RunEvent, RunOptions, RunResult
from .errors import BusyError, InvalidRequestError, product_operation
from .observations import RuntimeObservationHook


class RunService:
    def __init__(self, session):
        self._session = session
        self.active_run_id: str | None = None
        self._stop_requested = False
        self.last_result: RunResult | None = None
        self._observations = RuntimeObservationHook()
        session._agent.hook_manager.add_hook(self._observations)

    @contextmanager
    def _run(self, prompt, options):
        self._session._ensure_open()
        if not isinstance(prompt, str) or not prompt.strip():
            raise InvalidRequestError("A non-empty prompt is required")
        if self.active_run_id or self._session._agent.busy:
            raise BusyError("Session already has an active operation")
        if self._session.pending() is not None:
            raise InvalidRequestError(
                "Resolve the pending interaction before starting another run"
            )
        with product_operation():
            options = RunOptions.model_validate(options or {})
        run_id = uuid4().hex
        self.active_run_id = run_id
        self._stop_requested = False
        self.last_result = None
        self._session.invalidate_context()
        try:
            self._session._agent.clear_stop_request()
            with product_operation():
                yield run_id, options
        finally:
            self._session._agent.clear_stop_request()
            self.active_run_id = None
            self._stop_requested = False
            self._session.invalidate_context()

    def _result(self, run_id, text="", error=None):
        pending = self._session.pending()
        status = (
            "cancelled"
            if self._stop_requested
            else "interaction_required"
            if pending
            else "failed"
            if error
            else "completed"
        )
        self.last_result = RunResult(
            run_id=run_id,
            session_id=self._session.id,
            status=status,
            text=str(text or ""),
            interaction=pending,
            error=error,
        )
        return self.last_result

    def run(self, prompt, options=None):
        with self._run(prompt, options) as (run_id, options):
            try:
                text = self._session._agent.invoke(prompt, max_iter=options.max_iter)
            except ToolInterruption:
                if self._session.pending() is None:
                    raise
                text = ""
            except Exception:
                if not self._stop_requested:
                    raise
                text = ""
            return self._result(run_id, text)

    async def arun(self, prompt, options=None):
        with self._run(prompt, options) as (run_id, options):
            try:
                text = await self._session._agent.ainvoke(
                    prompt, max_iter=options.max_iter
                )
            except ToolInterruption:
                if self._session.pending() is None:
                    raise
                text = ""
            except asyncio.CancelledError:
                self._stop_requested = True
                self._result(run_id)
                raise
            except Exception:
                if not self._stop_requested:
                    raise
                text = ""
            return self._result(run_id, text)

    async def stream(self, prompt, options=None):
        with self._run(prompt, options) as (run_id, options):
            sequence, text, error = 0, "", None
            try:
                source = self._stream_facts(prompt, options)
                async with aclosing(source):
                    async for payload in source:
                        kind = str(payload.get("type") or "unknown")
                        content = str(payload.get("content") or "")
                        data = dict(payload.get("data") or {})
                        if kind == "final":
                            text = content
                        elif kind == "error" and not data.get("interrupted"):
                            error = content
                        sequence += 1
                        yield RunEvent(
                            run_id=run_id,
                            session_id=self._session.id,
                            sequence=sequence,
                            type=kind,
                            content=content,
                            data=data,
                        )
            except ToolInterruption:
                if self._session.pending() is None:
                    raise
            except (asyncio.CancelledError, GeneratorExit):
                self._stop_requested = True
                self._result(run_id, text)
                raise
            result = self._result(run_id, text, error)
            yield RunEvent(
                run_id=run_id,
                session_id=self._session.id,
                sequence=sequence + 1,
                type="run_finished",
                data=result.model_dump(mode="json"),
            )

    async def _stream_facts(self, prompt, options):
        """Merge public framework events with the stream, pulling one item ahead.

        The consumer controls backpressure. Runtime notices can arrive while a
        model request is waiting for its first token, without leaking the bus.
        """
        agent = self._session._agent
        notices = asyncio.Queue()
        round_number = 0

        def on_runtime(event):
            nonlocal round_number
            self._observations.flush(agent.get_context_usage)
            round_number += 1
            notices.put_nowait({"type": "round_start", "data": {"round": round_number}})

        subscription = agent.event_bus.subscribe(
            on_runtime, event_types={RuntimeEventType.LLM_INVOKE_STARTED}
        )
        self._observations.bind(notices.put_nowait)
        source = agent.astream(prompt, max_iter=options.max_iter)
        next_raw = asyncio.create_task(anext(source))
        next_notice = asyncio.create_task(notices.get())
        try:
            while True:
                done, _ = await asyncio.wait(
                    {next_raw, next_notice}, return_when=asyncio.FIRST_COMPLETED
                )
                if next_notice in done:
                    yield next_notice.result()
                    next_notice = asyncio.create_task(notices.get())
                if next_raw in done:
                    self._observations.flush(agent.get_context_usage)
                    # Preserve runtime-before-token ordering even when both became ready.
                    if next_notice.done():
                        yield next_notice.result()
                        next_notice = asyncio.create_task(notices.get())
                    while not notices.empty():
                        yield notices.get_nowait()
                    try:
                        raw = next_raw.result()
                    except StopAsyncIteration:
                        break
                    yield raw.to_dict()
                    next_raw = asyncio.create_task(anext(source))
            records = self._session.inspector.read("metrics", limit=1)
            if records:
                yield {"type": "usage", "data": records[-1]}
        finally:
            self._observations.bind(None)
            agent.event_bus.unsubscribe(subscription)
            for task in (next_raw, next_notice):
                if not task.done():
                    task.cancel()
                with suppress(asyncio.CancelledError, StopAsyncIteration, Exception):
                    await task
            await source.aclose()

    def cancel(self, reason=""):
        self._session._ensure_open()
        if self.active_run_id is None:
            return False
        self._stop_requested = True
        self._session._agent.request_stop(reason or "Run cancelled by caller")
        return True
