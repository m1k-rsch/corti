"""Per-session memorize work queue — the async tail of ``/add`` and ``/flush``.

The HTTP layer is the *feedback loop*: ``POST /add`` durably appends the
raw messages to ``unprocessed_buffer``, enqueues a work item here, and
acks the caller immediately. Everything expensive — boundary detection
(LLM), memcell carving, both extraction pipelines, OME strategy fan-out —
runs later, on a dedicated per-session worker.

Why a per-session FIFO instead of a global pool:

- **Ordering**: add-then-flush on the same session must process in that
  order (flush forces a boundary over whatever add left behind). A global
  queue or APS date-triggered jobs cannot guarantee per-session FIFO.
- **Exactly-once-per-row**: workers process the *buffer*, not the payload.
  A payload's rows are consumed into memcells (or rolled back into the
  tail) by the first item that sees them; a later item for the same
  session only sees what is still buffered, so the same message can never
  be carved twice even when two adds race each other's persistence.
- **No lost updates**: the per-session lock still serialises the
  read-merge-boundary-write cycle inside the worker.

Durability story: the queue itself is in-memory by design — the durable
record is the ``unprocessed_buffer`` slice. If the process dies after
acking but before the worker runs, the rows are still there; the next
``/add`` / ``/flush`` for that session (or the boot-time sweep,
:func:`enqueue_all_pending`) picks them up. At-least-once, never lost.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from corti.core.observability.logging import get_logger
from corti.service._boundary import _TRACK

logger = get_logger(__name__)


@dataclass(frozen=True)
class MemorizeWorkItem:
    """One unit of session-buffer processing.

    ``is_final=False`` → run boundary detection in mid-conversation mode
    (rows that don't carve a cell stay buffered). ``is_final=True`` →
    flush semantics: force a boundary over whatever remains.
    """

    session_id: str
    app_id: str
    project_id: str
    is_final: bool


_queues: dict[str, asyncio.Queue[MemorizeWorkItem]] = {}
_workers: dict[str, asyncio.Task[None]] = {}
_busy: set[str] = set()


def _import_memorize() -> Any:
    """Lazily import the memorize service (avoids a service↔service cycle)."""
    from corti.service.memorize import memorize

    return memorize


def enqueue_memorize(item: MemorizeWorkItem) -> None:
    """Append a work item to the session's FIFO and ensure a worker runs.

    Non-blocking: the caller (route handler) must be able to return the
    ack immediately. The worker task is created on first use per session
    and lives until it is cancelled at shutdown.
    """
    queue = _queues.setdefault(item.session_id, asyncio.Queue())
    queue.put_nowait(item)
    worker = _workers.get(item.session_id)
    if worker is None or worker.done():
        _workers[item.session_id] = asyncio.create_task(_drain(item.session_id))


async def _drain(session_id: str) -> None:
    """Per-session worker loop: consume items strictly in FIFO order.

    A failed run never kills the worker: the error is logged and the
    buffer rows remain, so the next item (or a flush) retries them.
    """
    queue = _queues[session_id]
    memorize = _import_memorize()
    try:
        while True:
            item = await queue.get()
            _busy.add(session_id)
            try:
                await memorize(
                    {
                        "session_id": item.session_id,
                        "app_id": item.app_id,
                        "project_id": item.project_id,
                        "messages": [],
                    },
                    is_final=item.is_final,
                    queue_driven=True,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "memorize_worker_run_failed",
                    extra={
                        "session_id": item.session_id,
                        "app_id": item.app_id,
                        "project_id": item.project_id,
                        "is_final": item.is_final,
                    },
                )
            finally:
                _busy.discard(session_id)
                queue.task_done()
    except asyncio.CancelledError:
        raise


def is_idle(session_id: str | None = None) -> bool:
    """True when no session (or the given session) has queued or in-flight work."""
    if session_id is not None:
        queue = _queues.get(session_id)
        return session_id not in _busy and (queue is None or queue.empty())
    return not _busy and all(q.empty() for q in _queues.values())


async def enqueue_all_pending() -> int:
    """Boot-time recovery sweep: re-queue every session with buffered rows.

    The queue is in-memory, so a crash after an ack leaves rows in the
    buffer with no worker to process them. On startup we enqueue a flush
    item per distinct (app, project, session) so nothing waits forever
    for the next interaction. Returns the number of sessions re-queued.
    """
    from sqlalchemy import select

    from corti.infra.persistence.sqlite import UnprocessedBuffer, get_engine

    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            select(
                UnprocessedBuffer.app_id,
                UnprocessedBuffer.project_id,
                UnprocessedBuffer.session_id,
            )
            .where(UnprocessedBuffer.track == _TRACK)
            .distinct()
        )
        pending = [tuple(row) for row in result.all()]
    if not pending:
        return 0
    for app_id, project_id, session_id in pending:
        enqueue_memorize(
            MemorizeWorkItem(
                session_id=session_id,
                app_id=app_id,
                project_id=project_id,
                is_final=True,
            )
        )
    logger.info(
        "memorize_queue_recovered_sessions",
        extra={"count": len(pending), "track": _TRACK},
    )
    return len(pending)


async def shutdown() -> None:
    """Cancel all worker tasks (app teardown).

    In-flight processing is cancelled; buffered rows survive for the next
    boot's sweep. Also used by tests to guarantee a clean loop.
    """
    tasks = list(_workers.values())
    _workers.clear()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _reset_for_tests() -> None:
    """Test-only: drop all queues and workers (see conftest singleton resets)."""
    for task in _workers.values():
        task.cancel()
    _workers.clear()
    _queues.clear()
    _busy.clear()
