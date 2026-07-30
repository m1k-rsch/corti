"""PromptSlot — prompt template loading.

External usage:
    from cortistrate.memory.prompt_slots import PromptLoader

Three-layer overlay (defaults → ``~/.cortistrate/prompt_slots/`` → runtime
override) is reserved for a future milestone; this version only resolves
the bundled defaults under ``src/cortistrate/config/prompt_slots/``.
"""

from .loader import PromptLoader as PromptLoader

__all__ = ["PromptLoader"]
