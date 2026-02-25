"""
highlights.py – /api/highlights endpoint.

POST /api/highlights
Body: { "document_id": "...", "language": "en|cs" }

Returns key concepts, key sentences, and main topics extracted by the LLM.
"""
from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import database as db
from ..services import llm_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["highlights"])

MAX_CHARS = 24000  # ~6000 tokens, safe reserve for prompt + response


class HighlightsRequest(BaseModel):
    document_id: str
    language: str = Field("en", pattern="^(en|cs)$")


def _parse_json_response(raw: str) -> dict:
    """Try to parse JSON from the LLM response, stripping markdown code fences."""
    # Strip ```json ... ``` wrapper if present
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract the first {...} block
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group())
        logger.warning("Could not parse JSON from LLM response, returning raw")
        return {"raw": raw}


@router.post("/highlights")
async def highlights(req: HighlightsRequest):
    """Extract key concepts, key sentences, and topics from a document."""
    doc = db.get_document(req.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc["status"] != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Document is not ready yet (status: {doc['status']})",
        )

    cache_extra = req.language
    cached = db.get_cached_result(req.document_id, "highlights", cache_extra)
    if cached:
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

    prompt = llm_service.build_highlights_prompt(text, req.language)
    raw = llm_service.generate(prompt)
    parsed = _parse_json_response(raw)

    result = {
        "document_id": req.document_id,
        "key_concepts": parsed.get("key_concepts", []),
        "key_sentences": parsed.get("key_sentences", []),
        "topics": parsed.get("topics", []),
        "truncated": truncated,
        "cached": False,
    }
    db.save_cached_result(req.document_id, "highlights", result, cache_extra)
    return result
