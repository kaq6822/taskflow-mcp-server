from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.engine.log_bus import log_bus
from app.engine.run_engine import get_engine

router = APIRouter(prefix="/api", tags=["stream"])


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: int):
    engine = get_engine()
    if not engine.has_run(run_id) and not await engine.run_exists(run_id):
        raise HTTPException(404, "run not found")

    async def events():
        queue = log_bus.subscribe(run_id)
        try:
            snapshot = log_bus.snapshot(run_id)
            for ev in snapshot:
                yield {"event": ev["event"], "data": json.dumps(ev["data"])}
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                if ev is None:
                    break
                yield {"event": ev["event"], "data": json.dumps(ev["data"])}
                if ev["event"] == "run.finished":
                    break
        finally:
            log_bus.unsubscribe(run_id, queue)

    return EventSourceResponse(events())
