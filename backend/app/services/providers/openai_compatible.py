"""
openai_compatible.py – Provider for any OpenAI-compatible REST endpoint.

Covers: LM Studio, LocalAI, vLLM, Ollama's /v1 endpoint, etc.
Uses the /v1/chat/completions endpoint with SSE streaming.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from .base import LLMProvider

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """Generic OpenAI-API-compatible provider (LM Studio, LocalAI, vLLM …)."""

    # Subclasses override this to distinguish themselves in logs / API responses
    _provider_key: str = "openai_compatible"

    def __init__(
        self,
        provider_key: str,
        base_url: str,
        model: str,
        api_key: str,
        timeout: int,
        generation: Any,
    ) -> None:
        self._provider_key = provider_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout
        self._gen = generation

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return self._provider_key

    @property
    def active_model(self) -> str:
        return self._model

    # ── Generate ──────────────────────────────────────────────────────────────

    def generate(self, prompt: str, **kwargs) -> str:
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", self._gen.temperature),
            "max_tokens":  kwargs.get("max_tokens",  self._gen.max_tokens),
            "top_p":       kwargs.get("top_p",        self._gen.top_p),
            "stream": False,
        }
        with httpx.Client(timeout=self._timeout, headers=self._headers()) as client:
            resp = client.post(f"{self._base_url}/chat/completions", json=payload)
            resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    # ── Streaming (SSE) ───────────────────────────────────────────────────────

    async def stream_generate(self, prompt: str, **kwargs) -> AsyncIterator[str]:
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", self._gen.temperature),
            "max_tokens":  kwargs.get("max_tokens",  self._gen.max_tokens),
            "top_p":       kwargs.get("top_p",        self._gen.top_p),
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers()) as client:
            async with client.stream("POST", f"{self._base_url}/chat/completions", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        token = delta.get("content", "")
                        if token:
                            yield token
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    # ── Models ────────────────────────────────────────────────────────────────

    def get_models(self) -> list[str]:
        try:
            with httpx.Client(timeout=5, headers=self._headers()) as client:
                resp = client.get(f"{self._base_url}/models")
                resp.raise_for_status()
            data = resp.json()
            models = data.get("data", data) if isinstance(data, dict) else data
            return [m["id"] for m in models if isinstance(m, dict) and "id" in m]
        except Exception as exc:
            logger.debug("%s get_models failed: %s", self._provider_key, exc)
            return []
