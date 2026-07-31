"""SearchManager — top-level orchestrator for ``POST /api/v1/memory/search``.

Hard partition by ``owner_type``:

* ``user``  → ``episodes`` (+ ``profiles`` when ``include_profile=true``)

Per kind, :func:`memory.search.adapter.resolve_pipeline` decides whether
the path is "single-route recall, no fusion" (``KEYWORD`` / ``VECTOR``)
or "sparse + dense → everalgo.rank" (``HYBRID`` / ``AGENTIC``). Component
guards (embedding / cross-encoder / LLM) raise early when a method is
selected without its prerequisites.

``HYBRID`` defaults to **no LLM rerank** — the response comes back
straight after the heap-expand pipeline (RRF-ordered expansion → LR-calibrated
global top-N competition with fact eviction). ``enable_llm_rerank`` is
**ignored** for the hierarchy path. ``AGENTIC`` keeps its own
internal cross-encoder rerank loop; the flag is ignored there.

``SearchEpisodeItem.atomic_facts`` is populated **only** when the HYBRID
pipeline runs over episodes. The other methods leave it empty: there is
no query-relevance score we can assign to a fact pulled by parent_id
alone, and emitting ``score=0.0`` facts would muddy the contract.

The manager never writes to storage; it only reads Postgres + markdown.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import TYPE_CHECKING

from corti.component.utils.datetime import to_display_tz
from corti.core.observability.logging import get_logger
from corti.core.observability.tracing import gen_request_id
from corti.infra.persistence.sqlite import (
    UnprocessedBuffer,
    unprocessed_buffer_repo,
)
from everalgo.rank import DEFAULT_RANK_CONFIG, RankConfig, arank
from everalgo.rank.fusion import rrf
from everalgo.types import Candidate, RankInput

from .adapter import resolve_pipeline
from .agentic import search_episodes_agentic
from .dto import (
    FilterNode,
    SearchData,
    SearchEpisodeItem,
    SearchMethod,
    SearchProfileItem,
    SearchRequest,
    SearchResponse,
    UnprocessedMessageDTO,
)
from .filters import compile_filters
from .hierarchy import build_ep_to_fact_parents, heap_expand
from .shaper import (
    reshape_hybrid_output,
    shape_episode_from_candidate,
)

if TYPE_CHECKING:
    from corti.component.embedding import EmbeddingProvider
    from corti.component.rerank import RerankProvider
    from corti.component.tokenizer import Tokenizer
    from everalgo.llm.protocols import LLMClient

    from .recall import (
        AtomicFactRecaller,
        EpisodeRecaller,
        ProfileRecaller,
    )

logger = get_logger(__name__)

# Recall pool sizing — matches the legacy enterprise constants
# ``DEFAULT_RECALL_MULTIPLIER`` / ``DEFAULT_TOPK_LIMIT``.
# Multiplier kicks in for ``top_k > 0``; ``top_k = -1`` (unlimited) is capped
# at the fixed top-k limit (100) rather than ``100 * multiplier`` — that way
# the recall pool never balloons to 500 in unlimited mode.
_DEFAULT_RECALL_MULTIPLIER = 2
_DEFAULT_TOP_K_CAP = 100

# Vector ``radius`` (cosine similarity threshold) default for **unlimited
# mode only**. In ``top_k > 0`` mode we trust the truncation cap to ditch
# low-quality tail; in ``top_k = -1`` mode we would otherwise return up to
# 100 candidates with no quality floor, so we layer a default 0.5
# similarity threshold the way enterprise does (enterprise uses 0.6 — we
# pick 0.5 slightly looser because Postgres cosine vs Milvus cosine score
# distributions can drift a bit on the same model).
_DEFAULT_UNLIMITED_RADIUS = 0.5

# ``maxsim_atomic`` recall pool sizing — atomic facts are ~28× denser than
# episodes (one memcell → 1 episode + ~28 atomic facts), so the fact pool
# is sized as ``top_k_episode * 20`` to consistently cover enough distinct
# parent memcells before the max-pool reduction. Capped to keep the ANN
# scan bounded on very large top_k requests.
_MAXSIM_FACT_MULTIPLIER = 20
_MAXSIM_FACT_POOL_CAP = 2000

# Mirror of ``service._boundary._TRACK``. The unprocessed buffer is a single
# shared track because boundary detection is single-pass — switching mode
# requires a fresh process. Hard-coded here (instead of importing) to keep
# the memory layer free of service-layer imports per the DDD direction rule.
_UNPROCESSED_TRACK = "memorize"


class SearchManager:
    """Orchestrates per-kind recall, fusion, and shape into the public DTO."""

    def __init__(
        self,
        *,
        episode_recaller: EpisodeRecaller,
        atomic_fact_recaller: AtomicFactRecaller,
        profile_recaller: ProfileRecaller,
        embedding: EmbeddingProvider | None,
        reranker: RerankProvider | None,
        llm_client: LLMClient | None,
        search_tokenizer: Tokenizer | None = None,
    ) -> None:
        self._ep = episode_recaller
        self._fact = atomic_fact_recaller
        self._profile = profile_recaller
        self._embedding = embedding
        self._reranker = reranker
        self._llm = llm_client
        self._search_tokenizer = search_tokenizer

    # ── Public entry ────────────────────────────────────────────────

    async def search(self, req: SearchRequest) -> SearchResponse:
        request_id = gen_request_id()
        # Compile filters first: a malformed `filters` payload is a user
        # input error (422) and should surface before the server-side
        # component guard (500). The two steps are independent.
        where = compile_filters(
            req.filters,
            owner_id=req.owner_id,
            owner_type=req.owner_type,
            app_id=req.app_id,
            project_id=req.project_id,
        )
        self._validate_components(req)

        episodes, profiles, unprocessed = await asyncio.gather(
            self._search_episodes(req, where),
            self._fetch_profile(req),
            self._load_unprocessed(req),
        )
        data = SearchData(
            episodes=episodes,
            profiles=profiles,
            unprocessed_messages=unprocessed,
        )

        return SearchResponse(request_id=request_id, data=data)

    # ── Unprocessed buffer ──────────────────────────────────────────

    async def _load_unprocessed(
        self, req: SearchRequest
    ) -> list[UnprocessedMessageDTO]:
        """Load in-flight buffer rows for ``filters.session_id`` (if present).

        Returns ``[]`` unless ``filters`` carries a top-level ``session_id``
        eq scalar — buffer rows have no ``user_id`` / ``agent_id`` attribution
        (boundary detection runs before owner inference), so session is the
        only meaningful query dimension.
        """
        session_id = _extract_top_level_session_id(req.filters)
        if session_id is None:
            return []
        rows = await unprocessed_buffer_repo.list_for_track(
            session_id,
            _UNPROCESSED_TRACK,
            app_id=req.app_id,
            project_id=req.project_id,
        )
        return [_unprocessed_buffer_to_dto(r) for r in rows]

    # ── Episodes ────────────────────────────────────────────────────

    async def _search_episodes(
        self, req: SearchRequest, where: str
    ) -> list[SearchEpisodeItem]:
        if req.method == SearchMethod.AGENTIC:
            return await search_episodes_agentic(
                req.query,
                owner_id=req.owner_id,
                where=where,
                app_id=req.app_id,
                project_id=req.project_id,
                episode_recaller=self._ep,
                atomic_fact_recaller=self._fact,
                embed_query_fn=self._embedding.embed,  # type: ignore[union-attr]
                reranker=self._reranker,  # type: ignore[arg-type]
                llm=self._llm,  # type: ignore[arg-type]
                top_k=self._top_k(req.top_k),
            )

        fusion_mode, _ = resolve_pipeline(req.method, "episode")
        enable_rerank = _effective_llm_rerank(req)
        top_k = self._top_k(req.top_k)

        # ── KEYWORD / VECTOR: single-route recall ──
        if fusion_mode is None:
            if req.method == SearchMethod.KEYWORD:
                cands = await self._ep.sparse_recall(
                    req.query, where, limit=self._recall_limit(req.top_k)
                )
            else:
                cands = await self._maxsim_atomic_recall(req, where, top_k)
            return [
                ep
                for ep in (shape_episode_from_candidate(c) for c in cands[:top_k])
                if ep is not None
            ]

        # ── HYBRID: parallel sparse + dense recall ──
        sparse, dense, query_vector = await self._recall_sparse_dense(
            self._ep, req, where, top_k
        )

        if fusion_mode == "hierarchy":
            rrf_candidates = rrf(sparse, dense)
            ep_to_parents = build_ep_to_fact_parents(rrf_candidates)
            episode_to_facts = await self._fact.facts_for_episodes(
                ep_to_parents,
                where,
                per_episode=max(top_k * 2, 20),
                query_vector=query_vector,
            )
            scored = heap_expand(
                sparse=sparse,
                dense=dense,
                episode_to_facts=episode_to_facts,
                top_k=top_k,
            )
            episode_pool = {c.id: c for c in (*sparse, *dense)}
            shaped = reshape_hybrid_output(scored, episode_pool=episode_pool)
            if req.min_score is not None:
                shaped = [s for s in shaped if s.score >= req.min_score]
            return shaped

        # rrf / lr: standard everalgo fusion path (fallback).
        output = await arank(
            RankInput(
                query=req.query,
                memory_type=self._ep.everalgo_memory_type,  # type: ignore[arg-type]
                sparse_candidates=sparse,
                dense_candidates=dense,
                top_k=top_k,
                radius=_effective_radius(req),
            ),
            config=RankConfig(fusion_mode=fusion_mode)
            if fusion_mode != "rrf"
            else DEFAULT_RANK_CONFIG,
            llm=self._llm,
            enable_rerank=enable_rerank,
            rerank_top_k=top_k,
        )
        ep_candidates = (_scored_as_candidate(s) for s in output.items)
        return [
            ep
            for ep in (shape_episode_from_candidate(c) for c in ep_candidates)
            if ep is not None
        ]

    # ── Profile ─────────────────────────────────────────────────────

    async def _fetch_profile(self, req: SearchRequest) -> list[SearchProfileItem]:
        if not req.include_profile or req.owner_type != "user":
            return []
        return await self._profile.fetch(req.owner_id)

    # ── Recall helpers ──────────────────────────────────────────────

    async def _single_route_recall(
        self,
        recaller: EpisodeRecaller,
        req: SearchRequest,
        where: str,
        top_k: int,
        *,
        cap: int = _DEFAULT_TOP_K_CAP,
    ) -> list[Candidate]:
        if req.method == SearchMethod.KEYWORD:
            return await recaller.sparse_recall(
                req.query, where, limit=self._recall_limit(req.top_k, cap=cap)
            )
        vector = await self._embed_query(req.query)
        cands = await recaller.dense_recall(
            vector, where, limit=self._recall_limit(req.top_k, cap=cap)
        )
        return self._apply_radius(cands, _effective_radius(req))

    async def _recall_sparse_dense(
        self,
        recaller: EpisodeRecaller,
        req: SearchRequest,
        where: str,
        top_k: int,
        *,
        cap: int = _DEFAULT_TOP_K_CAP,
    ) -> tuple[list[Candidate], list[Candidate], list[float]]:
        """Fan out keyword + vector recall in parallel.

        The third return is the query embedding itself — the HYBRID
        pipeline passes it into ``facts_for_episodes`` so per-fact
        cosine scoring reuses the same vector instead of re-embedding
        the query. Returns
        ``[]`` for ``vector`` when no embedding provider is configured.
        """
        vector = await self._embed_query(req.query)
        limit = self._recall_limit(req.top_k, cap=cap)
        sparse, dense = await asyncio.gather(
            recaller.sparse_recall(req.query, where, limit=limit),
            recaller.dense_recall(vector, where, limit=limit)
            if vector
            else _empty_candidates(),
        )
        dense = self._apply_radius(dense, _effective_radius(req))
        return sparse, dense, vector

    async def _maxsim_atomic_recall(
        self, req: SearchRequest, where: str, top_k: int
    ) -> list[Candidate]:
        """MaxSim-style: ANN atomic_facts → max-pool by memcell → batch fetch episodes.

        Trades one extra Postgres ANN scan (over the ~28× denser
        ``atomic_fact`` table) for finer-grained semantic match — long
        episodes whose single mean-pooled vector dilutes a specific topic
        recover via the matching atomic fact's own embedding. Mirrors
        Corti/EverAlgo's MaxSim retrieval pattern.
        """
        vector = await self._embed_query(req.query)
        if not vector:
            return []
        fact_limit = min(top_k * _MAXSIM_FACT_MULTIPLIER, _MAXSIM_FACT_POOL_CAP)
        fact_cands = await self._fact.dense_recall(vector, where, limit=fact_limit)
        # Max-pool fact scores by parent episode entry_id.
        ep_score: dict[str, float] = {}
        for fc in fact_cands:
            pid = fc.metadata.get("parent_id")
            if not isinstance(pid, str) or not pid:
                continue
            if fc.score > ep_score.get(pid, -1.0):
                ep_score[pid] = fc.score
        if not ep_score:
            return []
        ranked = sorted(ep_score.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        top_entry_ids = [eid for eid, _ in ranked]
        score_by_entry = dict(ranked)
        ep_cands = await self._ep.fetch_by_entry_ids(top_entry_ids, where)
        rescored: list[Candidate] = []
        for c in ep_cands:
            eid = c.metadata.get("entry_id")
            s = score_by_entry.get(eid, 0.0) if isinstance(eid, str) else 0.0
            rescored.append(
                Candidate(id=c.id, score=s, source="vector", metadata=c.metadata)
            )
        rescored.sort(key=lambda c: c.score, reverse=True)
        return self._apply_radius(rescored, _effective_radius(req))

    async def _embed_query(self, query: str) -> list[float]:
        if self._embedding is None:
            return []
        return await self._embedding.embed(query)

    # ── Limits / filters ────────────────────────────────────────────

    @staticmethod
    def _top_k(top_k: int, *, cap: int = _DEFAULT_TOP_K_CAP) -> int:
        """Resolve ``-1`` to ``cap``; pass others through unchanged."""
        return cap if top_k == -1 else top_k

    @staticmethod
    def _recall_limit(top_k_request: int, *, cap: int = _DEFAULT_TOP_K_CAP) -> int:
        """Effective recall pool size — branches on the *raw* request value.

        Mirrors enterprise:

        - ``top_k == -1`` (unlimited)  → fixed ``cap``
        - ``top_k > 0``                → ``top_k * DEFAULT_RECALL_MULTIPLIER``
        """
        if top_k_request == -1:
            return cap
        return max(
            top_k_request * _DEFAULT_RECALL_MULTIPLIER, _DEFAULT_RECALL_MULTIPLIER
        )

    @staticmethod
    def _apply_radius(cands: list[Candidate], radius: float | None) -> list[Candidate]:
        if radius is None:
            return cands
        return [c for c in cands if c.score >= radius]

    # ── Component guards ────────────────────────────────────────────

    def _validate_components(self, req: SearchRequest) -> None:
        """Fail fast when the chosen method needs components that are missing."""
        method = req.method
        needs_embedding = method != SearchMethod.KEYWORD
        if needs_embedding and self._embedding is None:
            raise RuntimeError(
                f"method={method.value!r} requires an embedding provider; "
                "configure [embedding] in settings"
            )
        # LLM is only mandatory when the caller explicitly opts into
        # Phase-5 rerank on HYBRID, or always for AGENTIC (sufficiency
        # check + multi-query generation).
        if (
            method == SearchMethod.HYBRID
            and req.enable_llm_rerank
            and self._llm is None
        ):
            raise RuntimeError(
                "method='hybrid' with enable_llm_rerank=true needs an LLM; "
                "configure [llm] in settings or drop the flag"
            )
        if method == SearchMethod.AGENTIC:
            if self._reranker is None:
                raise RuntimeError(
                    "method='agentic' requires a rerank provider; "
                    "configure [rerank] in settings"
                )
            if self._llm is None:
                raise RuntimeError(
                    "method='agentic' requires an LLM client; "
                    "configure [llm] in settings"
                )


def _scored_as_candidate(scored) -> Candidate:  # type: ignore[no-untyped-def]
    """Adapt a single-type ``ScoredItem`` back to a ``Candidate``.

    Adapts ``ScoredItem`` back to ``Candidate`` so the existing
    Candidate-based shapers apply.
    """
    return Candidate(
        id=scored.id,
        score=scored.score,
        source="other",
        metadata=dict(scored.metadata),
    )


def _effective_llm_rerank(req: SearchRequest) -> bool:
    """LLM Phase-5 rerank only kicks in for ``HYBRID`` and only when the
    caller opts in. ``AGENTIC`` runs its own cross-encoder rerank loop
    (via ``rerank_fn``) and intentionally skips Phase-5.
    """
    return req.method == SearchMethod.HYBRID and req.enable_llm_rerank


def _effective_radius(req: SearchRequest) -> float | None:
    """Resolve the cosine-similarity threshold actually applied to dense hits.

    Priority:

    1. Caller-supplied ``req.radius`` always wins (including ``0.0`` when
       they explicitly want everything).
    2. Otherwise, ``top_k == -1`` (unlimited) defaults to
       ``_DEFAULT_UNLIMITED_RADIUS`` so the response keeps a quality
       floor — matches enterprise's auto-default behaviour.
    3. Otherwise (normal ``top_k > 0`` mode), return ``None`` and trust
       truncation to handle tail quality.
    """
    if req.radius is not None:
        return req.radius
    if req.top_k == -1:
        return _DEFAULT_UNLIMITED_RADIUS
    return None


async def _empty_candidates() -> list[Candidate]:
    return []


def _extract_top_level_session_id(filters: FilterNode | None) -> str | None:
    """Return the literal value of a top-level ``session_id`` eq scalar.

    The unprocessed-buffer trigger only fires for the simple shape
    ``filters = {\"session_id\": \"<sid>\"}``. Anything wrapped in ``AND`` /
    ``OR``, nested deeper, or expressed via an operator map (``{\"eq\":
    ...}``, ``{\"in\": ...}``) is treated as \"session not pinned\" — there
    is no defensible buffer-scope mapping for those compound predicates.
    """
    if filters is None:
        return None
    extra = filters.__pydantic_extra__ or {}
    value = extra.get("session_id")
    return value if isinstance(value, str) and value else None


def _unprocessed_buffer_to_dto(row: UnprocessedBuffer) -> UnprocessedMessageDTO:
    """Render one ``unprocessed_buffer`` row as its public DTO.

    Mirrors :class:`MessageItemDTO`'s ``content`` shorthand: a single-item
    ``[{\"type\":\"text\",\"text\":...}]`` payload collapses to the inner string;
    every other shape stays as the opaque ``list[dict]`` so multimodal
    payloads round-trip without lossy flattening.
    """
    content_items = json.loads(row.content_items_json)
    if (
        isinstance(content_items, list)
        and len(content_items) == 1
        and isinstance(content_items[0], dict)
        and content_items[0].get("type") == "text"
        and isinstance(content_items[0].get("text"), str)
    ):
        content: str | list[dict[str, object]] = content_items[0]["text"]
    else:
        content = content_items
    tool_calls = (
        json.loads(row.tool_calls_json) if row.tool_calls_json is not None else None
    )
    return UnprocessedMessageDTO(
        id=row.message_id,
        app_id=row.app_id,
        project_id=row.project_id,
        session_id=row.session_id,
        sender_id=row.sender_id,
        sender_name=row.sender_name,
        role=row.role,  # type: ignore[arg-type]
        content=content,
        timestamp=to_display_tz(row.timestamp),
        tool_calls=tool_calls,
        tool_call_id=row.tool_call_id,
    )


def _merge_by_id_max(
    primary: list[Candidate], extra: list[Candidate]
) -> list[Candidate]:
    """Union by id, keep higher score."""
    by_id: dict[str, Candidate] = {c.id: c for c in primary}
    for c in extra:
        existing = by_id.get(c.id)
        if existing is None or c.score > existing.score:
            by_id[c.id] = c
    return list(by_id.values())


_ = Sequence  # quiet unused-import for the typing-only annotation above
