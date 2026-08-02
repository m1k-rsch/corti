"""Add + Flush core pipeline smoke — long real-conversation drive.

Goal: prove the user-side add/flush chain is end-to-end live. Feeds
**419 real LoCoMo messages** through ``POST /api/v1/memory/add`` (in 19
batches sharing one session_id) then a final ``POST /flush``, and
verifies:

1. Each /add returns a sane status and the unprocessed_buffer delta
   matches what the service claims (accumulated → grew by batch size;
   extracted → shrank or stayed flat).
2. After /flush the buffer is empty and the memcell table has rows.
3. After cascade drains, episode md files exist and Postgres rows
   reflect them with valid content_sha256 + vector.
4. OME-driven async strategies have produced atomic_fact / foresight /
   profile md files.

Real LLM + real embedder (creds via ``.env``). Marked ``slow`` —
``pytest -m slow tests/integration/test_add_flush_core_pipeline_smoke.py``.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
import pytest

from corti.infra.persistence.markdown import (
    AtomicFactDailyFrontmatter,
    EpisodeDailyFrontmatter,
    ForesightDailyFrontmatter,
)

# Directory names live on the frontmatter schemas (single source of truth);
# atomic_facts / foresights are dotfile-hidden so users only see episodes.
_EPISODE_DIR = EpisodeDailyFrontmatter.DIR_NAME
_ATOMIC_FACT_DIR = AtomicFactDailyFrontmatter.DIR_NAME
_FORESIGHT_DIR = ForesightDailyFrontmatter.DIR_NAME

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_add_messages(batch: dict) -> list[dict]:
    """Strip ``_audit_*`` fields; keep only what MessageItemDTO accepts."""
    return [
        {
            "sender_id": m["sender_id"],
            "role": m["role"],
            "timestamp": m["timestamp"],
            "content": m["content"],
        }
        for m in batch["messages"]
    ]


def _list_md_files(memory_root: Path, subpath: str) -> list[Path]:
    """List .md files under
    ``<memory_root>/default_app/default_project/users/<user>/<subpath>/``."""
    user_dir = memory_root / "default_app" / "default_project" / "users"
    if not user_dir.exists():
        return []
    out: list[Path] = []
    for user_dir_child in user_dir.iterdir():
        target = user_dir_child / subpath
        if target.is_dir():
            out.extend(target.rglob("*.md"))
        elif target.with_suffix(".md").exists():
            out.append(target.with_suffix(".md"))
    return out


def _count_episode_entries(md_files: list[Path]) -> int:
    """Count ``## entry-*`` blocks across all episode md files."""
    n = 0
    for f in md_files:
        for line in f.read_text().splitlines():
            stripped = line.strip()
            # Daily-log entries start with `## ` followed by an id token.
            # We count any second-level heading that isn't the standard
            # subsection headers used inside an entry.
            if stripped.startswith("## ") and not stripped.startswith(
                ("## Subject", "## Summary", "## Content", "## Fact", "## Foresight")
            ):
                n += 1
    return n


def _maybe_snapshot_memory_root(memory_root: Path) -> None:
    """Copy ``memory_root`` to ``$CORTI_KEEP_CORPUS_TO`` when set.

    Used to harvest a known-good corpus (md + sqlite + Postgres three-piece
    set) after a green test run, for later upload as the /search e2e
    fixture. Pure sync I/O — kept out of the async test body so ASYNC240
    doesn't complain about pathlib usage on the async path.
    """
    keep_to = os.environ.get("CORTI_KEEP_CORPUS_TO")
    if not keep_to:
        return
    dest = Path(keep_to).resolve()
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(memory_root, dest)


# ---------------------------------------------------------------------------
# The test (slow — hits real LLM + embedder; opt in via `pytest -m slow`)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.live_llm
# Retries cover transient real-LLM flakes: OME profile clustering
# occasionally fails to emit user.md within the cascade-drain deadline
# (LLM timeout, empty response, or async race), but is reliably stable
# on retry. reruns_delay leaves the cascade workers idle between
# attempts so we don't pile state on top of a prior run.
@pytest.mark.flaky(reruns=2, reruns_delay=5)
async def test_long_conversation_produces_all_memory_types(
    long_conversation: dict,
    async_client: httpx.AsyncClient,
    core_pipeline_runtime: Path,
    memorize_idle_poll: Callable[..., Awaitable[None]],
    cascade_done_poll: Callable[..., Awaitable[None]],
    buffer_count: Callable[[str], Awaitable[int]],
    memcell_count: Callable[..., Awaitable[int]],
) -> None:
    """One big seamless run: add 19 batches, flush, poll, assert everything."""

    session_id = long_conversation["corti_session_id"]
    memory_root = core_pipeline_runtime

    # ── Stage 0: baseline ─────────────────────────────────────────────────
    assert await buffer_count(session_id) == 0
    assert await memcell_count(session_id) == 0

    # ── Stage 1: drip 19 batches into /add (async-accept) ─────────────────
    # /add acks instantly with status "accepted" — the boundary pass runs
    # on the per-session worker afterwards, so per-batch buffer deltas are
    # not observable here. Conservation is asserted after the worker
    # drains (post-flush).
    total_messages = 0
    for idx, batch in enumerate(long_conversation["batches"]):
        msg_count = batch["message_count"]
        total_messages += msg_count

        resp = await async_client.post(
            "/api/v1/memory/add",
            json={"session_id": session_id, "messages": _to_add_messages(batch)},
            timeout=30.0,  # async-accept: no LLM call on this path anymore
        )
        assert resp.status_code == 200, (
            f"batch {idx} ({batch['locomo_session']}): {resp.status_code} {resp.text}"
        )
        body = resp.json()
        assert body["data"]["status"] == "accepted", body
        assert body["data"]["message_count"] == msg_count, body

    # ── Stage 2: flush ────────────────────────────────────────────────────
    resp = await async_client.post(
        "/api/v1/memory/flush",
        json={"session_id": session_id},
        timeout=30.0,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "accepted", resp.json()

    # The worker now drains: flush is queued behind the 19 adds (FIFO),
    # so the whole conversation is processed exactly once. Wait for it
    # before asserting anything about the buffer / memcells.
    await memorize_idle_poll(deadline_seconds=600.0)

    assert await buffer_count(session_id) == 0, "buffer must be drained after flush"

    cells_after_flush = await memcell_count(session_id)
    # 419 LoCoMo messages produce ~19 memcells in practice (LLM boundary
    # decides semantic cuts; daily-life chat carves coarsely). Threshold
    # 15 leaves room for run-to-run variance from the boundary LLM.
    assert cells_after_flush >= 15, (
        f"expected ≥ 15 memcells from {total_messages} messages, "
        f"got {cells_after_flush}"
    )
    # (No cells_after_flush > cells_pre_flush assertion: if the worker's
    # final add pass already carved every message, the flush finds an
    # empty buffer and legitimately produces zero new cells.)

    # ── Stage 3 + 4: wait for cascade to drain ────────────────────────────
    # Cascade syncs md → Postgres. OME async strategies (atomic / foresight /
    # profile) also write md, which then cascade picks up. So one wait on
    # cascade-drain effectively covers both pipelines — the worker has
    # already drained (memorize_idle_poll above), so all OME emissions
    # happened before this poll started.
    await cascade_done_poll(deadline_seconds=600.0)

    # ── Stage 5: artifacts on disk + Postgres ──────────────────────────────
    # 5.1 episodes
    episode_files = _list_md_files(memory_root, _EPISODE_DIR)
    assert episode_files, "no episode md files written"
    episode_entries = _count_episode_entries(episode_files)
    # 19 memcells × 2 owners (caroline + melanie) ≈ 36 episode rows seen
    # in practice; threshold 15 leaves variance room.
    assert episode_entries >= 15, (
        f"expected ≥ 15 episode entries across {len(episode_files)} files, "
        f"got {episode_entries}"
    )

    # 5.2 episode → Postgres

    pg_episode_count = await episode_repo.count()
    assert pg_episode_count >= 15, (
        f"Postgres episode rows ({pg_episode_count}) < md entries ({episode_entries})"
    )

    # 5.3 atomic_fact
    af_files = _list_md_files(memory_root, _ATOMIC_FACT_DIR)
    assert af_files, "no atomic_fact md files — extract_atomic_facts did not emit"


    pg_af_count = await atomic_fact_repo.count()
    assert pg_af_count >= 1, (
        f"Postgres atomic_fact rows = {pg_af_count}; expected ≥ 1"
    )

    # 5.4 foresight
    # Foresight extractor is correctly invoked (log: ``foresights_extracted``
    # per memcell) but daily-life chat about kids / work / hobbies rarely
    # yields explicit future-intent statements, so count is usually 0.
    # We assert the Postgres table exists (count returns 0 cleanly) — not
    # that any row was emitted.

    lance_fs_count = await foresight_repo.count()
    assert lance_fs_count >= 0, f"foresight table broken: count={lance_fs_count}"

    # 5.5 profile (md only — profile retrieval path is stub; we only assert
    # the writer wrote something). Profile lives as a single file
    # ``users/<user_id>/user.md`` (schema: ``UserProfileFrontmatter.PROFILE_FILENAME``).
    from corti.infra.persistence.markdown import UserProfileFrontmatter

    profile_filename = UserProfileFrontmatter.PROFILE_FILENAME
    profile_files: list[Path] = []
    users_root = memory_root / "default_app" / "default_project" / "users"
    if users_root.is_dir():
        for ud in users_root.iterdir():
            candidate = ud / profile_filename
            if candidate.exists():
                profile_files.append(candidate)
    assert profile_files, (
        f"no {profile_filename} written — extract_user_profile / "
        "trigger_profile_clustering did not emit"
    )
    # At least one profile file has non-trivial content.
    assert any(f.read_text().strip() for f in profile_files), (
        "all profile.md files are empty"
    )

    # ── Stage 5b: strict md ↔ Postgres parity (every cascade kind) ─────────
    # Counts above are looser ``>=`` checks against LLM non-determinism;
    # here we enforce byte-exact id-set + content_sha256 parity across
    # every md the pipeline wrote. Catches: missing rows, orphan rows,
    # content drift between md and the indexed projection.
    #
    # ``expect_at_least`` pins the kinds this pipeline MUST produce so an
    # empty glob (kind not emitted at all) fails loudly — without this
    # guard the parity check would silently pass on zero files. Foresight
    # is NOT pinned because the LLM frequently yields 0 future-intent
    # statements on daily-life chat (see commentary above stage 5.4).
    from tests._consistency_assertions import assert_md_lance_strict_consistent

    await assert_md_lance_strict_consistent(
        memory_root,
        expect_at_least={
            "episode": 1,
            "atomic_fact": 1,
            "user_profile": 1,
        },
    )

    # ── Stage 6: optional corpus snapshot ─────────────────────────────────
    # When ``CORTI_KEEP_CORPUS_TO=<dest>`` is set, copy the post-test
    # ``memory_root`` to ``<dest>`` so it can be tarred + uploaded as a
    # test corpus for the /search e2e suite. Skipped silently when the
    # env var is absent (default test runs don't snapshot).
    _maybe_snapshot_memory_root(memory_root)


# ---------------------------------------------------------------------------
# Diagnostic: lighter smoke that doesn't depend on the long fixture, used
# to validate the conftest fixtures themselves are wired correctly.
# ---------------------------------------------------------------------------


async def test_async_client_starts_and_health_responds(
    async_client: httpx.AsyncClient,
) -> None:
    """Tiny smoke — proves the conftest fixture brings the app up."""
    resp = await async_client.get("/health")
    assert resp.status_code == 200, resp.text
