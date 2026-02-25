"""
llm_service.py – unified interface to local LLM backends.

Supported backends (configured in config.yaml):
  • ollama        – native Ollama REST API
  • lmstudio      – OpenAI-compatible endpoint (LM Studio)
  • textgen       – text-generation-webui API
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Backend implementations
# ──────────────────────────────────────────────────────────────────────────────

class _OllamaBackend:
    def __init__(self) -> None:
        cfg = get_settings().llm.ollama
        self.base_url = cfg.base_url.rstrip("/")
        self.model = cfg.model
        self.timeout = cfg.timeout

    def generate(self, prompt: str, **gen_kwargs: Any) -> str:
        settings = get_settings().llm.generation
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": gen_kwargs.get("temperature", settings.temperature),
                "num_predict": gen_kwargs.get("max_tokens", settings.max_tokens),
                "top_p": gen_kwargs.get("top_p", settings.top_p),
            },
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(f"{self.base_url}/api/generate", json=payload)
            resp.raise_for_status()
        return resp.json().get("response", "")


class _LMStudioBackend:
    """Uses the OpenAI-compatible /v1/chat/completions endpoint."""

    def __init__(self) -> None:
        cfg = get_settings().llm.lmstudio
        self.base_url = cfg.base_url.rstrip("/")
        self.model = cfg.model
        self.timeout = cfg.timeout

    def generate(self, prompt: str, **gen_kwargs: Any) -> str:
        settings = get_settings().llm.generation
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": gen_kwargs.get("temperature", settings.temperature),
            "max_tokens": gen_kwargs.get("max_tokens", settings.max_tokens),
            "top_p": gen_kwargs.get("top_p", settings.top_p),
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(f"{self.base_url}/chat/completions", json=payload)
            resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


class _TextGenBackend:
    """text-generation-webui API (blocking /api/v1/generate)."""

    def __init__(self) -> None:
        cfg = get_settings().llm.textgen
        self.base_url = cfg.base_url.rstrip("/")
        self.timeout = cfg.timeout

    def generate(self, prompt: str, **gen_kwargs: Any) -> str:
        settings = get_settings().llm.generation
        payload = {
            "prompt": prompt,
            "max_new_tokens": gen_kwargs.get("max_tokens", settings.max_tokens),
            "temperature": gen_kwargs.get("temperature", settings.temperature),
            "top_p": gen_kwargs.get("top_p", settings.top_p),
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(f"{self.base_url}/api/v1/generate", json=payload)
            resp.raise_for_status()
        return resp.json()["results"][0]["text"]


# ──────────────────────────────────────────────────────────────────────────────
# Public interface
# ──────────────────────────────────────────────────────────────────────────────

_BACKENDS = {
    "ollama":    _OllamaBackend,
    "lmstudio":  _LMStudioBackend,
    "textgen":   _TextGenBackend,
}

_backend_instance = None


def _get_backend():
    global _backend_instance
    if _backend_instance is None:
        name = get_settings().llm.backend
        cls = _BACKENDS.get(name)
        if cls is None:
            raise ValueError(f"Unknown LLM backend: {name!r}. Choose from {list(_BACKENDS)}")
        _backend_instance = cls()
    return _backend_instance


def generate(prompt: str, **kwargs: Any) -> str:
    """Send *prompt* to the configured local LLM and return the response text."""
    backend = _get_backend()
    logger.debug("LLM generate | backend=%s | prompt_len=%d", type(backend).__name__, len(prompt))
    response = backend.generate(prompt, **kwargs)
    logger.debug("LLM response length: %d chars", len(response))
    return response


# ──────────────────────────────────────────────────────────────────────────────
# Prompt templates
# ──────────────────────────────────────────────────────────────────────────────

def build_summary_prompt(text: str, style: str = "paragraph") -> str:
    styles = {
        "paragraph": "Write a concise 3–5 paragraph executive summary of the following document.",
        "bullets":   "Summarize the following document as 7–10 bullet points. Be specific.",
        "executive": (
            "Write a 1-page executive summary suitable for C-level readers. "
            "Include: Purpose, Key Findings, Recommendations, and Next Steps."
        ),
    }
    instruction = styles.get(style, styles["paragraph"])
    return f"""{instruction}

DOCUMENT:
\"\"\"
{text}
\"\"\"

SUMMARY:"""


def build_highlights_prompt(text: str) -> str:
    return f"""Analyze the following document and extract:
1. The 5 most important key concepts (as a numbered list).
2. The 5 most significant key sentences verbatim from the text (as a numbered list).
3. The main topics covered (as a comma-separated list).

DOCUMENT:
\"\"\"
{text}
\"\"\"

Respond in valid JSON with keys: "key_concepts", "key_sentences", "topics".
JSON:"""


def build_presentation_prompt(text: str) -> str:
    return f"""Create a structured presentation outline from the following document.
Return a JSON object with:
- "title": the presentation title
- "slides": an array of objects, each with:
    - "title": slide title
    - "bullets": list of 3–5 bullet points
    - "notes": optional speaker notes (1–2 sentences)

Aim for 6–10 slides total.

DOCUMENT:
\"\"\"
{text}
\"\"\"

JSON:"""


def build_qa_prompt(context_chunks: list[str], question: str) -> str:
    context = "\n\n---\n\n".join(context_chunks)
    return f"""Answer the user's question using ONLY the information from the provided context.
If the answer is not in the context, say "I don't have enough information to answer that."

CONTEXT:
\"\"\"
{context}
\"\"\"

QUESTION: {question}

ANSWER:"""
