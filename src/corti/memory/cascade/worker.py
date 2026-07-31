"""Cascade worker - consumes pending rows and runs the matching handler.

The worker is the only piece that crosses the md -> DB boundary.
Each cycle:

1. ``claim_pending_batch(BATCH_SIZE)`` atomically flips pending rows to
   ``processing`` and returns them in LSN order.
2. For each row, look up the kind's :class:`Handler` and call either
   :meth:`handle_added_or_modified` or :meth:`handle_deleted` based on
   the row's ``change_type``.
3. On success: ``mark_done``.
4. On :class:`RecoverableError`: retry inline up to ``MAX_RETRY``; if
   all attempts fail, ``mark_failed(retryable=True)``.
5. On any other exception: ``mark_failed(retryable=False)`` (treated
   as unrecoverable, surfaces in ``cascade fix`` for the user to
   triage by editing the md).

Batch processing is concurrent inside a batch (``asyncio.gather``);
ordering across rows is best-effort - the LSN gives a deterministic
prefix but the handlers themselves are independent.

PostgreSQL manages its own indexes via autovacuum and HNSW maintenance -
no application-level optimize or rebuild loop is needed.
"""

from __future__ import annotations

import asyncio
import contextlib

from corti.core.observability.logging import get_logger
from corti.infra.persistence.sqlite import MdChangeState, md_change_state_repo

from .errors import RecoverableError
from .handlers import Handler

logger = get_logger(__name__)

# Conservative defaults - surface in settings if tuning is needed.
DEFAULT_BATCH_SIZE = 50
DEFAULT_MAX_RETRY = 3
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_RETRY_BACKOFF_SECONDS = 2.0


class CascadeWorker:
    """Owns the claim -> dispatch -> mark cycle.

    Created with the ``{kind: Handler}`` map produced by
    :func:`memory.cascade.registry.build_handlers`. Holds no other
    state - every per-row decision goes through the repo.
    """

    def __init__(
        self,
        handlers: dict[str, Handler],
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_retry: int = DEFAULT_MAX_RETRY,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    ) -> None:
        self._handlers = handlers
        self._batch_size = batch_size
        self._max_retry = max_retry
        self._poll_interval = poll_interval_seconds
        self._retry_backoff = retry_backoff_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(), name="cascade-worker")
        logger.info("cascade_worker_started", batch_size=self._batch_size)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._task
        self._task = None
        logger.info("cascade_worker_stopped")

    async def drain_once(self) -> int:
        """Process one batch, return the number of rows handled.

        Used by CLI ``cascade sync`` and ``fix --apply`` to flush the
        queue without spinning the background task. Returns ``0`` when
        the queue is empty.
        """
        batch = await md_change_state_repo.claim_pending_batch(self._batch_size)
        if not batch:
            return 0
        results = await asyncio.gather(*(self._process_one(row) for row in batch))
        return len(batch)

    async def drain_until_empty(self, *, max_passes: int = 100) -> int:
        """Drain repeatedly until the queue is empty (or ``max_passes``).

        Returns the total number of rows processed. Bounded passes
        prevent a livelock if a stuck row keeps re-failing back to
        pending (which can't happen in the current design but is a
        cheap safety net).
        """
        total = 0
        for _ in range(max_passes):
            processed = await self.drain_once()
            if processed == 0:
                break
            total += processed
        return total

    # ── internals ──────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                processed = await self.drain_once()
            except Exception as exc:
                logger.exception("cascade_worker_drain_failed", error=str(exc))
                processed = 0
            if processed == 0:
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self._poll_interval
                    )
                except TimeoutError:
                    continue

    async def _process_one(self, row: MdChangeState) -> str | None:
        """Process one ``md_change_state`` row.

        Returns the ``row.kind`` when the handler actually mutated the
        kind's DB table (``upserted`` or ``deleted`` > 0). Returns
        ``None`` for skipped-only rows, failed rows, and rows where no
        handler is registered.
        """
        handler = self._handlers.get(row.kind)
        if handler is None:
            await md_change_state_repo.mark_failed(
                row.md_path,
                retryable=False,
                error=f"no handler registered for kind {row.kind!r}",
                new_retry_count=row.retry_count,
            )
            return None

        retry_count = row.retry_count
        last_error: str = ""
        for attempt in range(self._max_retry + 1):
            try:
                if row.change_type == "deleted":
                    outcome = await handler.handle_deleted(row.md_path)
                else:
                    outcome = await handler.handle_added_or_modified(row.md_path)
            except RecoverableError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "cascade_worker_recoverable",
                    md_path=row.md_path,
                    attempt=attempt,
                    error=last_error,
                )
                if attempt < self._max_retry:
                    retry_count += 1
                    await asyncio.sleep(self._retry_backoff * (attempt + 1))
                    continue
                await md_change_state_repo.mark_failed(
                    row.md_path,
                    retryable=True,
                    error=last_error,
                    new_retry_count=retry_count,
                )
                return None
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.exception(
                    "cascade_worker_unrecoverable",
                    md_path=row.md_path,
                    kind=row.kind,
                )
                await md_change_state_repo.mark_failed(
                    row.md_path,
                    retryable=False,
                    error=last_error,
                    new_retry_count=retry_count,
                )
                return None

            logger.info(
                "cascade_worker_processed",
                md_path=row.md_path,
                kind=row.kind,
                change_type=row.change_type,
                upserted=outcome.upserted,
                deleted=outcome.deleted,
                skipped=outcome.skipped,
            )
            await md_change_state_repo.mark_done(row.md_path)
            return row.kind if (outcome.upserted or outcome.deleted) else None
        return None
