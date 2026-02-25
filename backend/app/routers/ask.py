"""
ask.py – RAG-powered Q&A endpoints.

POST /api/ask        – blocking, cached JSON response
POST /api/ask/stream – Server-Sent Events stream (token-by-token, not cached)
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import database as db
from ..services import llm_service
from ..services.rag_service import retrieve_relevant_chunks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["ask"])


class AskRequest(BaseModel):
    document_id: str
    question: str = Field(..., min_length=3, max_length=2000)


def _get_ready_doc(doc_id: str) -> dict:
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc["status"] != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Document is not ready yet (status: {doc['status']})",
        )
    return doc


# ── Blocking endpoint (cached) ────────────────────────────────────────────────

@router.post("/ask")
async def ask(req: AskRequest):
    """Answer a question about a document using RAG (result is cached)."""
    _get_ready_doc(req.document_id)

    cached = db.get_cached_result(req.document_id, "ask", req.question)
    if cached:
        logger.debug("Cache hit: ask/%s", req.document_id)
        return {**cached, "cached": True}

    chunks = retrieve_relevant_chunks(req.document_id, req.question)
    if not chunks:
        raise HTTPException(status_code=422, detail="No text chunks available for this document")

    prompt = llm_service.build_qa_prompt(chunks, req.question)
    answer = llm_service.generate(prompt)

    result = {
        "document_id": req.document_id,
        "question": req.question,
        "answer": answer.strip(),
        "sources_used": len(chunks),
        "cached": False,
    }
    db.save_cached_result(req.document_id, "ask", result, req.question)
    return result


# ── Streaming endpoint (SSE, not cached) ──────────────────────────────────────

@router.post("/ask/stream")
async def ask_stream(req: AskRequest):
    """Stream the LLM answer token-by-token via Server-Sent Events.

    The frontend connects with fetch() + ReadableStream and renders tokens
    as they arrive. Streamed answers are NOT stored in the cache.
    """
    _get_ready_doc(req.document_id)

    chunks = retrieve_relevant_chunks(req.document_id, req.question)
    if not chunks:
        raise HTTPException(status_code=422, detail="No text chunks available for this document")

    prompt = llm_service.build_qa_prompt(chunks, req.question)

    async def event_generator():
        # Send metadata first so the client knows sources_used
        meta = json.dumps({"type": "meta", "sources_used": len(chunks)})
        yield f"data: {meta}\n\n"

        full_answer: list[str] = []
        try:
            async for token in llm_service.stream_generate(prompt):
                full_answer.append(token)
                payload = json.dumps({"type": "token", "text": token})
                yield f"data: {payload}\n\n"
        except Exception as exc:
            err = json.dumps({"type": "error", "message": str(exc)})
            yield f"data: {err}\n\n"
            return

        # Send done event with the accumulated full answer
        done = json.dumps({"type": "done", "answer": "".join(full_answer)})
        yield f"data: {done}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering
        },
    )
