"""LLM lifespan provider — eagerly resolves the LLM singleton at startup.

The framework's core value (memory extraction) is meaningless without
an LLM, so misconfiguration must surface as a startup failure instead
of N silent skips per request downstream. Ordered before the storage
stack so we fail before paying to bring sqlite / postgres / cascade up.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from corti.component.llm import get_llm_client
from corti.core.lifespan import LifespanProvider
from corti.core.observability.logging import get_logger

logger = get_logger(__name__)


class LLMLifespanProvider(LifespanProvider):
    """Resolve the LLM client at startup; warn (do not crash) on failure.

    Missing or misconfigured credentials must not take down the entire
    process — memory storage, health checks, and other subsystems stay
    alive.  Downstream callers that actually invoke the LLM will surface
    errors at call time via their own exception handling.
    """

    def __init__(self, order: int = 8) -> None:
        super().__init__(name="llm", order=order)

    async def startup(self, app: FastAPI) -> Any:
        try:
            client = get_llm_client()
            logger.info("llm_lifespan_ready")
            return client
        except Exception:
            logger.warning(
                "llm_lifespan_degraded",
                msg="LLM client could not be built — "
                "memory extraction and search will be unavailable. "
                "Check [llm] in corti.toml.",
            )
            return None

    async def shutdown(self, app: FastAPI) -> None:
        # The client is stateless (algo facade over openai.AsyncOpenAI);
        # nothing to tear down.
        return None
