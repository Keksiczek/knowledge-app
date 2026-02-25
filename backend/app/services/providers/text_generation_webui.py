"""
text_generation_webui.py – Provider for oobabooga/text-generation-webui.

Supports two API styles:
  • Legacy blocking: POST /api/v1/generate
  • Streaming:       POST /api/v1/generate with stream=True (Server-Sent Events)
  • Model info:      GET  /api/v1/model
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from .base import LLMProvider

logger = logging.getLogger(__name__)


class TextGenWebUIProvider(LLMProvider):
    def __init__(self, base_url: str, model: str, timeout: int, generation: Any) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._gen = generation

    @property
    def provider_name(self) -> str:
        return "text_generation_webui"

    @property
    def active_model(self) -> str:
        return self._model

    # ── Generate ──────────────────────────────────────────────────────────────

    def generate(self, prompt: str, **kwargs) -> str:
        payload = {
            "prompt": prompt,
            "max_new_tokens":    kwargs.get("max_tokens",  self._gen.max_tokens),
            "temperature":       kwargs.get("temperature", self._gen.temperature),
            "top_p":             kwargs.get("top_p",       self._gen.top_p),
            "do_sample":         True,
            "stream":            False,
        }
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(f"{self._base_url}/api/v1/generate", json=payload)
            resp.raise_for_status()
        return resp.json()["results"][0]["text"]

    # ── Streaming ─────────────────────────────────────────────────────────────

    async def stream_generate(self, prompt: str, **kwargs) -> AsyncIterator[str]:
        """text-generation-webui returns SSE lines when stream=True."""
        payload = {
            "prompt": prompt,
            "max_new_tokens": kwargs.get("max_tokens",  self._gen.max_tokens),
            "temperature":    kwargs.get("temperature", self._gen.temperature),
            "top_p":          kwargs.get("top_p",       self._gen.top_p),
            "do_sample":      True,
            "stream":         True,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream("POST", f"{self._base_url}/api/v1/generate", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str:
                        continue
                    try:
                        data = json.loads(data_str)
                        token = data.get("token", {}).get("text", "")
                        if token:
                            yield token
                    except json.JSONDecodeError:
                        continue

    # ── Models ────────────────────────────────────────────────────────────────

    def get_models(self) -> list[str]:
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{self._base_url}/api/v1/model")
                resp.raise_for_status()
            return [resp.json().get("result", "default")]
        except Exception as exc:
            logger.debug("TextGenWebUI get_models failed: %s", exc)
            return []
