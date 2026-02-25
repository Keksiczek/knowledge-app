"""
ask.py – /api/ask endpoint (RAG-powered Q&A).

POST /api/ask
Body: { "document_id": "...", "question": "What is ...?" }

Uses RAG: retrieves relevant chunks → builds prompt → calls LLM.
Answers are cached per (document_id, question).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import database as db
from ..services import llm_service
from ..services.rag_service import retrieve_relevant_chunks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["ask"])


class AskRequest(BaseModel):
    document_id: str
    question: str = Field(..., min_length=3, max_length=2000)


@router.post("/ask")
async def ask(req: AskRequest):
    """Answer a question about a document using RAG."""
    doc = db.get_document(req.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc["status"] != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Document is not ready yet (status: {doc['status']})",
        )

    # Cache key = hash of the question
    cached = db.get_cached_result(req.document_id, "ask", req.question)
    if cached:
        logger.debug("Cache hit: ask/%s", req.document_id)
        return {**cached, "cached": True}

    # Retrieve relevant chunks via semantic search
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
