"""
summarize.py – /api/summarize endpoint.

POST /api/summarize
Body: { "document_id": "...", "style": "paragraph|bullets|executive", "language": "en|cs" }

Returns a cached or freshly-generated summary.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import database as db
from ..services import llm_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["summarize"])

MAX_CHARS = 24000  # ~6000 tokens, safe reserve for prompt + response


class SummarizeRequest(BaseModel):
    document_id: str
    style: str = Field("paragraph", pattern="^(paragraph|bullets|executive)$")
    language: str = Field("en", pattern="^(en|cs)$")


@router.post("/summarize")
async def summarize(req: SummarizeRequest):
    """Generate or return a cached summary for a document."""
    doc = db.get_document(req.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc["status"] != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Document is not ready yet (status: {doc['status']})",
        )

    # Cache key includes style and language
    cache_extra = f"{req.style}:{req.language}"
    cached = db.get_cached_result(req.document_id, "summarize", cache_extra)
    if cached:
        logger.debug("Cache hit: summarize/%s/%s", req.document_id, req.style)
        return {**cached, "cached": True}

    text = db.get_full_text(req.document_id)
    if not text:
        raise HTTPException(status_code=422, detail="No text extracted from document")

    # Truncation protection against context window overflow
    truncated = False
    original_len = len(text)
    if len(text) > MAX_CHARS:
        half = MAX_CHARS // 2
        text = text[:half] + "\n\n[... střed dokumentu zkrácen ...]\n\n" + text[-half:]
        truncated = True
        logger.warning("Document truncated for LLM: doc_id=%s, original_len=%d", req.document_id, original_len)

    prompt = llm_service.build_summary_prompt(text, req.style, req.language)
    summary_text = llm_service.generate(prompt)

    result = {
        "document_id": req.document_id,
        "style": req.style,
        "summary": summary_text.strip(),
        "truncated": truncated,
        "cached": False,
    }
    db.save_cached_result(req.document_id, "summarize", result, cache_extra)
    return result
