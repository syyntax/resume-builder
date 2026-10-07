"""In-process job queue and event bus (DESIGN.md §6.1). One instance per deployment.

Jobs run one at a time per user and at most `max_concurrent` across users. Progress events are published
to subscribers (the SSE endpoint) by application id.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger("resume_tailor.jobs")


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def subscribe(self, topic: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers[topic].add(queue)
        return queue

    def unsubscribe(self, topic: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers[topic].discard(queue)
        if not self._subscribers[topic]:
            self._subscribers.pop(topic, None)

    def publish(self, topic: str, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(topic, ())):
            with contextlib.suppress(asyncio.QueueFull):  # a stalled client misses events, not the job
                queue.put_nowait(event)


class JobRunner:
    def __init__(self, max_concurrent: int) -> None:
        self._slots = asyncio.Semaphore(max(1, max_concurrent))
        self._user_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._tasks: set[asyncio.Task[None]] = set()

    def submit(self, owner_id: str, job: Callable[[], Awaitable[None]]) -> None:
        async def run() -> None:
            async with self._user_locks[owner_id], self._slots:
                try:
                    await job()
                except Exception:  # noqa: BLE001  (jobs report their own failures; never crash the loop)
                    log.exception("job failed for owner %s", owner_id)

        task = asyncio.create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @property
    def active(self) -> int:
        return len(self._tasks)

    async def drain(self) -> None:
        """Wait for running jobs (tests use this to make background work deterministic)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)
