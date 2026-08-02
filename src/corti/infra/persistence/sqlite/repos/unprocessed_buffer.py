"""Repository for ``unprocessed_buffer`` — chat message accumulator.

Singleton bound to the process-wide ``sqlite_manager`` session factory.

Pure SQLModel persistence: row ↔ domain conversion lives in
``corti.memory.extract.pipeline`` (the only caller that needs it).

Exposes:

- :meth:`list_for_track` — load all rows of (session_id, track), ordered by ts.
- :meth:`replace` — atomically swap all rows of (session_id, track) for a
  freshly-built list of :class:`UnprocessedBuffer` rows.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from corti.core.persistence.sqlite import RepoBase, session_scope

from ..sqlite_manager import get_session_factory
from ..tables import UnprocessedBuffer


class _UnprocessedBufferRepo(RepoBase[UnprocessedBuffer]):
    model = UnprocessedBuffer

    def _factory_lookup(self) -> async_sessionmaker[AsyncSession]:
        return get_session_factory()

    async def list_for_track(
        self,
        session_id: str,
        track: str,
        *,
        app_id: str = "default",
        project_id: str = "default",
    ) -> list[UnprocessedBuffer]:
        """Return all rows of (app, project, session, track), ts asc."""
        async with session_scope(self._factory) as s:
            stmt = (
                select(UnprocessedBuffer)
                .where(
                    UnprocessedBuffer.app_id == app_id,
                    UnprocessedBuffer.project_id == project_id,
                    UnprocessedBuffer.session_id == session_id,
                    UnprocessedBuffer.track == track,
                )
                .order_by(UnprocessedBuffer.timestamp.asc())  # type: ignore[union-attr]
            )
            return list((await s.execute(stmt)).scalars().all())

    async def replace(
        self,
        session_id: str,
        track: str,
        rows: list[UnprocessedBuffer],
        *,
        app_id: str = "default",
        project_id: str = "default",
    ) -> None:
        """Atomically rewrite all rows of (app, project, session, track).

        Delete-then-insert in one transaction. Empty ``rows`` clears the slice.
        The delete is scoped to the same (app, project) as the incoming rows so
        one space's buffer never wipes another's.
        """
        async with session_scope(self._factory) as s:
            await s.execute(
                delete(UnprocessedBuffer).where(
                    UnprocessedBuffer.app_id == app_id,
                    UnprocessedBuffer.project_id == project_id,
                    UnprocessedBuffer.session_id == session_id,
                    UnprocessedBuffer.track == track,
                )
            )
            if rows:
                s.add_all(rows)
            await s.commit()

    async def append_many(
        self,
        rows: list[UnprocessedBuffer],
        *,
        app_id: str = "default",
        project_id: str = "default",
    ) -> int:
        """Append rows to the buffer without touching existing rows.

        ``INSERT OR IGNORE`` on the composite PK ``(message_id, app_id,
        project_id)`` — a row that is already buffered (deterministic
        message ids make retried payloads collide) is silently skipped.
        Returns the number of rows actually inserted.

        This is the fast-ack write path of ``POST /add``: it must stay
        a single bounded SQLite statement — no read-modify-write, so
        concurrent adds on the same session cannot lose each other's
        rows. Boundary processing later rewrites the whole slice via
        :meth:`replace` under the per-session worker, which is the only
        consumer allowed to delete.
        """
        if not rows:
            return 0
        table = UnprocessedBuffer.__table__
        values = [
            {column.name: getattr(row, column.name) for column in table.columns}
            for row in rows
        ]
        stmt = (
            sqlite_insert(table)
            .values(values)
            .on_conflict_do_nothing(
                index_elements=["message_id", "app_id", "project_id"],
            )
        )
        async with session_scope(self._factory) as s:
            result = await s.execute(stmt)
            await s.commit()
        return int(result.rowcount or 0)


unprocessed_buffer_repo = _UnprocessedBufferRepo()
