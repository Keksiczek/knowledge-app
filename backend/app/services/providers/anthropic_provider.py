"""
anthropic_provider.py – Provider for the Anthropic Claude API.

Uses the `anthropic` SDK (>=0.25).  Falls back gracefully when not installed.
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from .base import LLMProvider

logger = logging.getLogger(__name__)

# Curated list – Anthropic has no public /models endpoint
_ANTHROPIC_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250514",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "claude-3-opus-20240229",
]


class AnthropicProvider(LLMProvider):
    def __init__(
        self,
        model: str,
        api_key: str,
        timeout: int,
        generation: Any,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._timeout = timeout
        self._gen = generation
        self._client = None
        self._async_client = None

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(
                    api_key=self._api_key,
                    timeout=float(self._timeout),
                )
            except ImportError:
                raise ImportError(
                    "anthropic package is not installed. "
                    "Run: pip install anthropic"
                )
        return self._client

    def _get_async_client(self):
        if self._async_client is None:
            try:
                import anthropic
                self._async_client = anthropic.AsyncAnthropic(
                    api_key=self._api_key,
                    timeout=float(self._timeout),
                )
            except ImportError:
                raise ImportError("anthropic package is not installed.")
        return self._async_client

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def active_model(self) -> str:
        return self._model

    # ── Generate ──────────────────────────────────────────────────────────────

    def generate(self, prompt: str, **kwargs) -> str:
        client = self._get_client()
        msg = client.messages.create(
            model=self._model,
            max_tokens=kwargs.get("max_tokens", self._gen.max_tokens),
            messages=[{"role": "user", "content": prompt}],
            temperature=kwargs.get("temperature", self._gen.temperature),
        )
        return msg.content[0].text if msg.content else ""

    # ── Streaming ─────────────────────────────────────────────────────────────

    async def stream_generate(self, prompt: str, **kwargs) -> AsyncIterator[str]:
        client = self._get_async_client()
        async with client.messages.stream(
            model=self._model,
            max_tokens=kwargs.get("max_tokens", self._gen.max_tokens),
            messages=[{"role": "user", "content": prompt}],
            temperature=kwargs.get("temperature", self._gen.temperature),
        ) as stream:
            async for text in stream.text_stream:
                yield text

    # ── Models ────────────────────────────────────────────────────────────────

    def get_models(self) -> list[str]:
        # Anthropic doesn't expose a public /models endpoint; return curated list
        return _ANTHROPIC_MODELS
