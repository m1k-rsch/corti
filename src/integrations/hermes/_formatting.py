"""Hermes-agnostic formatting helpers for the Cortistrate plugin.

Turns ``SearchData`` and other API shapes into the strings the Hermes agent
sees (prefetch block, system prompt block, tool-result JSON, mirror messages).
Stdlib + local ``_constants`` / ``_types`` only.
"""

from __future__ import annotations

import json
import logging

from ._constants import _MAX_PREFETCH_CHARS
from ._types import (
    GetEpisodeItem,
    GetProfileItem,
    MessageItem,
    SearchData,
    SearchEpisodeItem,
    SearchProfileItem,
)

logger = logging.getLogger(__name__)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 0:
        return " …"
    budget = max_chars - len(" …")
    if budget <= 0:
        return " …"
    slice_end = budget
    boundary = text.rfind(" ", 0, slice_end)
    if boundary > 0:
        slice_end = boundary
    return text[:slice_end].rstrip() + " …"


def _profile_one_line(profile: SearchProfileItem) -> str:
    data = profile.get("profile_data") or {}
    if isinstance(data, dict) and data:
        for key in ("name", "summary", "bio", "description", "title"):
            if data.get(key):
                return str(data[key]).replace("\n", " ").strip()
        first_key = next(iter(data))
        return f"{first_key}: {data[first_key]}".replace("\n", " ").strip()
    uid = profile.get("user_id") or profile.get("id") or "user"
    return f"profile for {uid}"


def _format_episode(ep: SearchEpisodeItem) -> str:
    subject = ep.get("subject") or "(no subject)"
    episode_text = (ep.get("episode") or "").strip()
    facts = ep.get("atomic_facts") or []

    lines = [f"- **Episode**: {subject}"]
    if episode_text:
        lines.append(episode_text)
    for fact in facts:
        content = (fact.get("content") or "").strip()
        if content:
            lines.append(f"  - {content}")
    return "\n".join(lines)


def format_prefetch(
    query: str,
    search_data: SearchData,
    *,
    max_chars: int = _MAX_PREFETCH_CHARS,
) -> str:
    episodes = list(search_data.get("episodes") or [])
    profiles = list(search_data.get("profiles") or [])

    if not episodes and not profiles:
        return ""

    header = "## Cortistrate Memory"
    sections: list[str] = [header]

    if profiles:
        ranked = sorted(
            profiles,
            key=lambda p: p.get("score") if p.get("score") is not None else -1.0,
            reverse=True,
        )
        sections.append(f"- **Profile**: {_profile_one_line(ranked[0])}")

    for ep in sorted(episodes, key=lambda e: e.get("score", 0.0), reverse=True):
        sections.append(_format_episode(ep))

    body = "\n".join(sections)
    truncated = _truncate(body, max_chars)
    logger.debug("format_prefetch query=%r len=%d", query, len(truncated))
    return truncated


def format_tool_result(data: object) -> str:
    """Serialize a tool result payload as JSON (the inner serializer)."""
    return json.dumps(data, ensure_ascii=False)


def _format_profile_block(profile: GetProfileItem) -> str:
    """Render profile data for the system prompt block."""
    data = profile.get("profile_data") or {}
    if not isinstance(data, dict) or not data:
        return ""
    lines = []
    summary = data.get("summary")
    if isinstance(summary, str) and summary.strip():
        lines.append(f"- **Profile summary**: {summary.strip()}")
    explicit = data.get("explicit_info")
    if isinstance(explicit, list):
        for item in explicit:
            if isinstance(item, str) and item.strip():
                lines.append(f"  - {item.strip()}")
    implicit = data.get("implicit_traits")
    if isinstance(implicit, list):
        for item in implicit:
            if isinstance(item, str) and item.strip():
                lines.append(f"  - {item.strip()}")
    return "\n".join(lines)


def format_system_prompt(
    profile: GetProfileItem | None,
    episodes: list[GetEpisodeItem],
) -> str:
    """Build the system prompt memory block: profile + recent episode subjects."""
    sections = ["## Cortistrate Memory"]
    if profile is not None:
        prof = _format_profile_block(profile)
        if prof:
            sections.append(prof)
    if episodes:
        sections.append(f"- **Recent activity** ({len(episodes)} most recent sessions):")
        for ep in episodes:
            subject = (ep.get("subject") or "").strip()
            ts = (ep.get("timestamp") or "")[:10]
            sender_ids = ep.get("sender_ids") or []
            agent_label = ""
            for sid in sender_ids:
                if sid not in ("default", ""):
                    agent_label = f" ({sid})"
                    break
            if subject:
                sections.append(f"  - [{ts}]{agent_label} {subject}")
    return "\n".join(sections)


def format_memory_write_message(
    content: str, user_id: str, timestamp_ms: int
) -> MessageItem:
    """Build a user-role ``MessageItem`` for mirroring into Cortistrate."""
    item: MessageItem = {
        "sender_id": user_id,
        "role": "user",
        "timestamp": timestamp_ms,
        "content": content,
    }
    return item
