"""POST /api/v1/memory/add and /api/v1/memory/flush.

DTOs follow the v1 API brief (01_v1_api_brief.md §2 / §3). Routes are
thin adapters: validate the DTO, durably persist the raw content,
enqueue the async extraction, and ack — no business logic lives here.

The feedback-loop contract (the reason ``/add`` never blocks on the
LLM):

    POST /add
      → validate DTO
      → ingest_process (normalise; multimodal parse)
      → persist_fresh (INSERT OR IGNORE into unprocessed_buffer — the
        durable "we received it" moment; deterministic message ids make
        blind retries of the same payload a no-op)
      → enqueue_memorize(is_final=False)   # boundary + pipelines, async
      → 200 {message_count, status: "accepted"}

    POST /flush
      → enqueue_memorize(is_final=True)    # force boundary over the buffer
      → 200 {status: "accepted"}

The per-session worker (corti.service._memorize_queue) drains items
strictly FIFO per session_id, so an add followed by a flush processes in
that order and a message can never be carved into two cells.

``/flush`` is OSS-only (the cloud edition decides boundary timing
server-side and does not expose this endpoint).
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Request
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from corti.config import load_settings
from corti.entrypoints.api.utils import extract_request_id
from corti.memory.extract.ingest import process as ingest_process
from corti.service._memorize_queue import MemorizeWorkItem, enqueue_memorize
from corti.service.memorize import persist_fresh

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


# ── Path-safe identifier ────────────────────────────────────────────────────
# ``app_id`` / ``project_id`` / ``sender_id`` all become directory segments
# under the memory root (``sender_id`` flows through to ``owner_id`` and is
# joined into the daily-log write path), so they must reject ``.`` and ``..``
# (path traversal). The basic character whitelist is enforced via ``pattern``
# (pydantic_core uses the Rust regex engine, which does NOT support
# lookaround), and the two reserved tokens are filtered out with a follow-up
# ``AfterValidator``.
#
# ``@`` and ``+`` are admitted so real-world ids survive (email-style
# ``user@example.com``, plus-addressing ``user+tag``); both are legal,
# non-separator filename chars on every target filesystem (incl. NTFS, whose
# reserved set is ``< > : " / \ | ? *``). The genuinely path-dangerous chars
# (``/`` ``\`` NUL) stay out of the whitelist, and ``.``/``..`` stay blocked
# by the token filter; the markdown writer's ``_ensure_within_root`` is the
# final backstop regardless.
_PATH_SAFE_CHARSET = r"^[a-zA-Z0-9_.@+-]+$"
_PATH_TRAVERSAL_TOKENS = frozenset({".", ".."})


_PATH_SAFE_RE = re.compile(_PATH_SAFE_CHARSET)


def _reject_path_traversal(value: str) -> str:
    if value in _PATH_TRAVERSAL_TOKENS:
        raise ValueError("'.' and '..' are reserved (path traversal)")
    if not _PATH_SAFE_RE.match(value):
        raise ValueError(
            "Only alphanumerics, underscore, dot, hyphen, @, and + are allowed"
        )
    return value


PathSafeId = Annotated[str, AfterValidator(_reject_path_traversal)]


# DTOs ────────────────────────────────────────────────────────────────────────


class ToolFunctionDTO(BaseModel):
    name: str
    arguments: str  # JSON string per OpenAI Chat Completions spec


class ToolCallDTO(BaseModel):
    id: str
    type: str = "function"
    function: ToolFunctionDTO


class ContentItemDTO(BaseModel):
    """Content piece (v1 API brief appendix A)."""

    type: Literal["text", "image", "audio", "doc", "pdf", "html", "email"]
    text: str | None = None
    uri: str | None = None
    base64: str | None = None
    ext: str | None = None
    name: str | None = None
    extras: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")


class MessageItemDTO(BaseModel):
    # ``sender_id`` becomes ``owner_id`` and then a directory segment on the
    # episode write path, so it carries the same path-safety guard as
    # ``app_id`` / ``project_id`` (charset whitelist + ``.``/``..`` rejection).
    sender_id: PathSafeId = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=_PATH_SAFE_CHARSET,
    )
    sender_name: str | None = None
    role: Literal["user", "assistant", "tool"]
    timestamp: int = Field(
        ...,
        gt=0,
        description=(
            "Message event time as Unix epoch in **milliseconds** "
            "(v1 API contract; the algo layer auto-detects sec vs ms "
            "for backward compat but the contract is ms)."
        ),
    )
    content: str | list[ContentItemDTO]
    tool_calls: list[ToolCallDTO] | None = None
    tool_call_id: str | None = None


class MemorizeAddRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    app_id: PathSafeId = Field(
        default="default",
        min_length=1,
        max_length=128,
        pattern=_PATH_SAFE_CHARSET,
    )
    project_id: PathSafeId = Field(
        default="default",
        min_length=1,
        max_length=128,
        pattern=_PATH_SAFE_CHARSET,
    )
    messages: list[MessageItemDTO] = Field(..., min_length=1, max_length=500)


class AddResponseData(BaseModel):
    message_count: int
    status: Literal["accepted"]


class MemorizeFlushRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    app_id: PathSafeId = Field(
        default="default",
        min_length=1,
        max_length=128,
        pattern=_PATH_SAFE_CHARSET,
    )
    project_id: PathSafeId = Field(
        default="default",
        min_length=1,
        max_length=128,
        pattern=_PATH_SAFE_CHARSET,
    )


class FlushResponseData(BaseModel):
    status: Literal["accepted"]


class SuccessEnvelope[T](BaseModel):
    """200 wrapper: ``request_id`` sits at the top level, not inside ``data``."""

    request_id: str
    data: T


# Route ──────────────────────────────────────────────────────────────────────


@router.post("/add")
async def add_memory(
    req: Annotated[MemorizeAddRequest, ...],
    request: Request,
) -> SuccessEnvelope[AddResponseData]:
    """Add messages into the user-memory + agent-memory pipelines.

    Feedback loop: persist the raw content durably, enqueue the
    boundary + extraction work, and ack immediately. The caller must
    never wait on LLM latency to learn that its memory was accepted.
    """
    request_id = extract_request_id(request)
    payload = req.model_dump()

    # 1) Normalise (pure CPU except multimodal parse) — mirrors the
    #    worker's own ingest so the persisted rows match what boundary
    #    detection will see.
    ingested = await ingest_process(payload)

    # 2) Durable accept: INSERT OR IGNORE into unprocessed_buffer.
    #    Deterministic message ids (session + ts + idx) make a blind
    #    retry of the same payload a no-op — no duplicate rows, and the
    #    worker can never carve the same message twice.
    await persist_fresh(ingested, mode=load_settings().memorize.mode)

    # 3) Async extraction: boundary detection + user/agent pipelines
    #    run on the per-session worker, strictly FIFO.
    enqueue_memorize(
        MemorizeWorkItem(
            session_id=ingested.session_id,
            app_id=ingested.app_id,
            project_id=ingested.project_id,
            is_final=False,
        )
    )

    # 4) Ack — the caller may continue immediately.
    return SuccessEnvelope(
        request_id=request_id,
        data=AddResponseData(
            message_count=len(payload["messages"]),
            status="accepted",
        ),
    )


@router.post("/flush")
async def flush_memory(
    req: Annotated[MemorizeFlushRequest, ...],
    request: Request,
) -> SuccessEnvelope[FlushResponseData]:
    """Force boundary detection over the current ``session_id`` buffer.

    Also async: enqueues an ``is_final=True`` work item behind any
    pending adds for the session (FIFO), so the flush processes exactly
    what the adds left behind.

    [OSS-only] — cloud edition decides boundary timing server-side and
    does not expose this endpoint.
    """
    request_id = extract_request_id(request)
    enqueue_memorize(
        MemorizeWorkItem(
            session_id=req.session_id,
            app_id=req.app_id,
            project_id=req.project_id,
            is_final=True,
        )
    )
    return SuccessEnvelope(
        request_id=request_id,
        data=FlushResponseData(status="accepted"),
    )
