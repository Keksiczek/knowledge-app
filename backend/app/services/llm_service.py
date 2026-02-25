"""
llm_service.py – thin facade over the provider registry.

Public surface used by routers:
  generate(prompt)            – blocking full response
  stream_generate(prompt)     – async generator of token chunks
  get_active_provider()       – current LLMProvider instance
  switch_provider(name, model)
  list_providers()
  build_*_prompt(...)         – prompt template helpers
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Optional

from .providers import (
    get_provider,
    list_providers,
    switch_provider as _switch_provider,
)
from .providers.base import LLMProvider

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Core generation API
# ──────────────────────────────────────────────────────────────────────────────

def generate(prompt: str, **kwargs: Any) -> str:
    """Send *prompt* to the active provider and return the full response."""
    provider = get_provider()
    logger.debug(
        "generate | provider=%s model=%s prompt_len=%d",
        provider.provider_name, provider.active_model, len(prompt),
    )
    response = provider.generate(prompt, **kwargs)
    logger.debug("response length: %d chars", len(response))
    return response


async def stream_generate(prompt: str, **kwargs: Any) -> AsyncIterator[str]:
    """Yield token chunks from the active provider (async generator)."""
    provider = get_provider()
    logger.debug(
        "stream_generate | provider=%s model=%s",
        provider.provider_name, provider.active_model,
    )
    async for token in provider.stream_generate(prompt, **kwargs):
        yield token


# ──────────────────────────────────────────────────────────────────────────────
# Provider management helpers
# ──────────────────────────────────────────────────────────────────────────────

def get_active_provider() -> LLMProvider:
    return get_provider()


def switch_provider(name: str, model: Optional[str] = None) -> LLMProvider:
    return _switch_provider(name, model)


def get_provider_list() -> list[dict]:
    return list_providers()


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
