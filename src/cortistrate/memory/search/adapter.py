"""Method → hybrid pipeline selector.

Translates the public 4-method enum into cortistrate's internal pipeline routing signal.
``AGENTIC`` is intercepted by the manager before this function is called.
Passing ``AGENTIC`` here is a caller contract violation and raises
``ValueError`` as a defensive guard.

* ``KEYWORD`` / ``VECTOR`` → ``None`` → manager skips ``everalgo.rank``.
* ``HYBRID``  → ``\"hierarchy\"`` (episode / atomic_fact) — heap-expand
  pipeline (RRF-ordered expansion → LR-calibrated global top-N competition).
"""

from __future__ import annotations

from typing import Literal

from .dto import SearchMethod

KindName = Literal["episode", "atomic_fact"]


def resolve_pipeline(
    method: SearchMethod,
    kind: KindName,
) -> tuple[str | None, None]:
    """Return ``(pipeline_signal, None)`` for a ``(method, kind)`` pair.

    ``pipeline_signal`` of ``None`` means \"do not call ``everalgo.rank.arank``;
    the manager runs single-route recall and returns directly\".
    ``\"hierarchy\"`` routes to the heap-expand episode pipeline in
    ``memory.search.hierarchy`` (RRF → LR → heap expansion → eviction).
    """
    if method in (SearchMethod.KEYWORD, SearchMethod.VECTOR):
        return None, None

    if method == SearchMethod.HYBRID:
        if kind in ("episode", "atomic_fact"):
            return "hierarchy", None

    raise ValueError(f"unsupported method: {method!r}")
