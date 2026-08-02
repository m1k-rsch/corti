"""Memorize queue lifespan provider (HTTP API entrypoint).

Startup: sweep ``unprocessed_buffer`` and re-enqueue a flush item for
every session that still has rows. The per-session work queue is
in-memory, so a crash after a ``POST /add`` ack leaves the raw rows
durable but nobody scheduled to process them — this sweep closes that
gap on the next boot.

Runs after OME (order 60) so the worker's pipeline events always find a
started engine.

Shutdown: cancel the per-session worker tasks.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from corti.core.lifespan import LifespanProvider
from corti.core.observability.logging import get_logger

logger = get_logger(__name__)


class MemorizeQueueLifespanProvider(LifespanProvider):
    """Manage the per-session memorize worker queue lifecycle."""

    def __init__(self, order: int = 60) -> None:
        super().__init__(name="memorize_queue", order=order)

    async def startup(self, app: FastAPI) -> Any:
        from corti.service._memorize_queue import enqueue_all_pending

        try:
            count = await enqueue_all_pending()
        except Exception:
            # The sweep is best-effort recovery: a failing sweep must not
            # block server startup (rows stay buffered and are picked up
            # by the next add/flush anyway).
            logger.exception("memorize_queue_startup_sweep_failed")
            return None
        if count:
            logger.info(
                "memorize_queue_sweep_enqueued",
                extra={"sessions": count},
            )
        return count

    async def shutdown(self, app: FastAPI) -> None:
        from corti.service._memorize_queue import shutdown as shutdown_queue

        await shutdown_queue()
        logger.info("memorize_queue_stopped")
