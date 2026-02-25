"""
summarize.py – /api/summarize endpoint.

POST /api/summarize
Body: { "document_id": "...", "style": "paragraph|bullets|executive" }

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


class SummarizeRequest(BaseModel):
    document_id: str
    style: str = Field("paragraph", pattern="^(paragraph|bullets|executive)$")


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

    # Check cache
    cached = db.get_cached_result(req.document_id, "summarize", req.style)
    if cached:
        logger.debug("Cache hit: summarize/%s/%s", req.document_id, req.style)
        return {**cached, "cached": True}

    text = db.get_full_text(req.document_id)
    if not text:
        raise HTTPException(status_code=422, detail="No text extracted from document")

    prompt = llm_service.build_summary_prompt(text, req.style)
    summary_text = llm_service.generate(prompt)

    result = {
        "document_id": req.document_id,
        "style": req.style,
        "summary": summary_text.strip(),
        "cached": False,
    }
    db.save_cached_result(req.document_id, "summarize", result, req.style)
    return result
