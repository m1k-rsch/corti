"""PromptSlot — prompt template loading.

External usage:
    from corti.memory.prompt_slots import PromptLoader

Three-layer overlay (defaults → ``~/.corti/prompt_slots/`` → runtime
override) is reserved for a future milestone; this version only resolves
the bundled defaults under ``src/corti/config/prompt_slots/``.
"""

from .loader import PromptLoader as PromptLoader

__all__ = ["PromptLoader"]
