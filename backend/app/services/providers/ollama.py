"""
ollama.py – Provider for Ollama (http://localhost:11434).

Uses the native Ollama REST API:
  POST /api/generate          – blocking generation
  POST /api/generate          – streaming (stream=True, NDJSON)
  GET  /api/tags              – list local models
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from .base import LLMProvider

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str, model: str, timeout: int, generation: Any) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._gen = generation  # GenerationConfig

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def active_model(self) -> str:
        return self._model

    # ── Generate ──────────────────────────────────────────────────────────────

    def generate(self, prompt: str, **kwargs) -> str:
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", self._gen.temperature),
                "num_predict": kwargs.get("max_tokens", self._gen.max_tokens),
                "top_p":       kwargs.get("top_p",       self._gen.top_p),
            },
        }
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(f"{self._base_url}/api/generate", json=payload)
            resp.raise_for_status()
        return resp.json().get("response", "")

    # ── Streaming ─────────────────────────────────────────────────────────────

    async def stream_generate(self, prompt: str, **kwargs) -> AsyncIterator[str]:
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": kwargs.get("temperature", self._gen.temperature),
                "num_predict": kwargs.get("max_tokens", self._gen.max_tokens),
                "top_p":       kwargs.get("top_p",       self._gen.top_p),
            },
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream("POST", f"{self._base_url}/api/generate", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        token = data.get("response", "")
                        if token:
                            yield token
                        if data.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue

    # ── Models ────────────────────────────────────────────────────────────────

    def get_models(self) -> list[str]:
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
            models = resp.json().get("models", [])
            return [m["name"] for m in models]
        except Exception as exc:
            logger.debug("Ollama get_models failed: %s", exc)
            return []
