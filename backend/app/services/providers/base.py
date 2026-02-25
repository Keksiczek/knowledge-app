"""
base.py – Abstract LLMProvider interface.

Every concrete provider must implement:
  generate()       – blocking, returns the full response string
  stream_generate() – async generator, yields token chunks
  get_models()     – returns available model names (empty list on failure)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator


class LLMProvider(ABC):
    """Abstract base class for all LLM provider backends."""

    # ── Required overrides ────────────────────────────────────────────────────

    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str:
        """Send *prompt* and return the full generated text (blocking)."""
        ...

    @abstractmethod
    def get_models(self) -> list[str]:
        """Return a list of model identifiers available from this provider.

        Should return an empty list rather than raising on network failure.
        """
        ...

    # ── Optional streaming override ───────────────────────────────────────────

    async def stream_generate(self, prompt: str, **kwargs) -> AsyncIterator[str]:
        """Yield generated text token-by-token.

        Default implementation calls generate() and yields the result as one
        chunk.  Providers should override this for true streaming.
        """
        result = self.generate(prompt, **kwargs)
        yield result

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Machine-readable provider key (e.g. 'ollama', 'openai')."""
        ...

    @property
    @abstractmethod
    def active_model(self) -> str:
        """The model currently in use."""
        ...
