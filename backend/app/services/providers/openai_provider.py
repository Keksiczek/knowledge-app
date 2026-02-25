"""
openai_provider.py – Provider for the official OpenAI API.

Uses the `openai` SDK (>=1.0).  Falls back gracefully when the package is
not installed (returns empty model list; generate raises ImportError).
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from .base import LLMProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        model: str,
        api_key: str,
        organization: str,
        timeout: int,
        generation: Any,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._organization = organization or None
        self._timeout = timeout
        self._gen = generation
        self._client = None       # lazy sync client
        self._async_client = None # lazy async client

    def _get_client(self):
        if self._client is None:
            try:
                import openai
                self._client = openai.OpenAI(
                    api_key=self._api_key,
                    organization=self._organization,
                    timeout=self._timeout,
                )
            except ImportError:
                raise ImportError(
                    "openai package is not installed. "
                    "Run: pip install openai"
                )
        return self._client

    def _get_async_client(self):
        if self._async_client is None:
            try:
                import openai
                self._async_client = openai.AsyncOpenAI(
                    api_key=self._api_key,
                    organization=self._organization,
                    timeout=self._timeout,
                )
            except ImportError:
                raise ImportError("openai package is not installed.")
        return self._async_client

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def active_model(self) -> str:
        return self._model

    # ── Generate ──────────────────────────────────────────────────────────────

    def generate(self, prompt: str, **kwargs) -> str:
        client = self._get_client()
        resp = client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=kwargs.get("temperature", self._gen.temperature),
            max_tokens=kwargs.get("max_tokens", self._gen.max_tokens),
            top_p=kwargs.get("top_p", self._gen.top_p),
        )
        return resp.choices[0].message.content or ""

    # ── Streaming ─────────────────────────────────────────────────────────────

    async def stream_generate(self, prompt: str, **kwargs) -> AsyncIterator[str]:
        client = self._get_async_client()
        stream = await client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=kwargs.get("temperature", self._gen.temperature),
            max_tokens=kwargs.get("max_tokens", self._gen.max_tokens),
            top_p=kwargs.get("top_p", self._gen.top_p),
            stream=True,
        )
        async for chunk in stream:
            token = chunk.choices[0].delta.content
            if token:
                yield token

    # ── Models ────────────────────────────────────────────────────────────────

    def get_models(self) -> list[str]:
        try:
            client = self._get_client()
            models = client.models.list()
            # Filter to chat-capable models only
            names = sorted(
                m.id for m in models.data
                if "gpt" in m.id or "o1" in m.id or "o3" in m.id
            )
            return names
        except Exception as exc:
            logger.debug("OpenAI get_models failed: %s", exc)
            # Return curated list as fallback
            return [
                "gpt-4o",
                "gpt-4o-mini",
                "gpt-4-turbo",
                "gpt-3.5-turbo",
                "o1",
                "o1-mini",
                "o3-mini",
            ]
