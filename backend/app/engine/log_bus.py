from __future__ import annotations

import asyncio
from collections import defaultdict


class LogBus:
    """In-process fan-out for run events.

    Each run_id has a set of subscriber queues plus a bounded snapshot list so
    late subscribers get historical events already emitted (last 500).
    """

    def __init__(self) -> None:
        self._queues: dict[int, set[asyncio.Queue]] = defaultdict(set)
        self._snapshots: dict[int, list[dict]] = defaultdict(list)

    def subscribe(self, run_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues[run_id].add(q)
        return q

    def unsubscribe(self, run_id: int, q: asyncio.Queue) -> None:
        self._queues[run_id].discard(q)

    def snapshot(self, run_id: int) -> list[dict]:
        return list(self._snapshots.get(run_id, []))

    def publish(self, run_id: int, event: str, data: dict) -> None:
        payload = {"event": event, "data": data}
        snap = self._snapshots[run_id]
        snap.append(payload)
        if len(snap) > 500:
            del snap[: len(snap) - 500]
        for q in list(self._queues.get(run_id, set())):
            try:
                q.put_nowait(payload)
            except Exception:
                pass
        if event == "run.finished":
            # notify all subscribers to close
            for q in list(self._queues.get(run_id, set())):
                try:
                    q.put_nowait(None)
                except Exception:
                    pass

    def clear(self, run_id: int) -> None:
        self._snapshots.pop(run_id, None)
        self._queues.pop(run_id, None)


log_bus = LogBus()
