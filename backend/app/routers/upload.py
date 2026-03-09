"""
upload.py – file upload and document management endpoints.

POST   /api/v1/upload                     – upload one or more files
GET    /api/v1/documents                  – list all documents
GET    /api/v1/documents/{id}             – get single document metadata
DELETE /api/v1/documents/{id}             – remove document and all derived data
POST   /api/v1/documents/{id}/reprocess   – reprocess a failed/stale document
POST   /api/v1/ingest_text                – ingest raw text directly (no file upload)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..config import get_settings
from .. import database as db
from ..services.text_extraction import SUPPORTED_EXTENSIONS, extract_text
from ..services.rag_service import index_document
from ..utils.token_counter import count_tokens

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["upload"])


def _upload_dir() -> Path:
    settings = get_settings()
    p = Path(settings.storage.upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _validate_extension(file: UploadFile) -> None:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{ext}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}",
        )


def _validate_size(content: bytes) -> None:
    settings = get_settings()
    max_bytes = settings.storage.max_file_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content) // (1024*1024)} MB). Max {settings.storage.max_file_size_mb} MB.",
        )


async def _process_document(doc_id: str, file_path: Path) -> None:
    """Background task: extract text, chunk, embed, and update document status."""
    try:
        db.update_document_status(doc_id, "processing")
        text = extract_text(file_path)
        tc = count_tokens(text)
        db.update_document_status(doc_id, "ready", text_length=len(text), token_count=tc)
        index_document(doc_id, text)
        logger.info("Document %s processed: %d chars / %d tokens", doc_id, len(text), tc)
    except Exception as exc:
        logger.error("Processing failed for %s: %s", doc_id, exc)
        db.update_document_status(doc_id, "error")


@router.post("/upload")
async def upload_files(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
):
    """Upload one or more documents for processing."""
    results = []
    upload_dir = _upload_dir()

    for file in files:
        _validate_extension(file)
        doc_id = str(uuid.uuid4())
        ext = Path(file.filename or "file").suffix.lower()
        safe_name = f"{doc_id}{ext}"
        dest = upload_dir / safe_name

        # Read content first, then validate size (content_length unreliable for chunked uploads)
        content = await file.read()
        _validate_size(content)
        dest.write_bytes(content)

        doc = {
            "id": doc_id,
            "filename": safe_name,
            "original_name": file.filename or "unknown",
            "file_format": ext.lstrip("."),
            "file_size": len(content),
            "uploaded_at": datetime.utcnow().isoformat(),
            "text_length": 0,
            "token_count": 0,
            "status": "pending",
        }
        db.save_document(doc)
        background_tasks.add_task(_process_document, doc_id, dest)

        results.append(doc)
        logger.info("Uploaded: %s -> %s", file.filename, doc_id)

    return JSONResponse(status_code=202, content={"documents": results})


@router.get("/documents")
async def list_documents():
    """Return all documents ordered by upload time."""
    return {"documents": db.list_documents()}


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    """Return metadata for a single document."""
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    """Delete a document and all its derived data."""
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove uploaded file
    upload_dir = _upload_dir()
    file_path = upload_dir / doc["filename"]
    if file_path.exists():
        file_path.unlink()

    db.delete_document(doc_id)
    return {"deleted": doc_id}


@router.post("/documents/{doc_id}/reprocess", status_code=202)
async def reprocess_document(doc_id: str, background_tasks: BackgroundTasks):
    """Reset a failed/stale document back to pending and reprocess it."""
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    upload_dir = _upload_dir()
    file_path = upload_dir / doc["filename"]
    if not file_path.exists():
        raise HTTPException(
            status_code=409,
            detail="Original file not found on disk; cannot reprocess",
        )

    db.update_document_status(doc_id, "pending")
    background_tasks.add_task(_process_document, doc_id, file_path)
    logger.info("Reprocessing document %s", doc_id)
    return {"id": doc_id, "status": "pending"}


class IngestTextRequest(BaseModel):
    text: str
    title: str = "Untitled"
    external_id: str | None = None
    source: str | None = None   # teams | email | hub | etc.
    language: str = "auto"      # cs | en | auto (informational only)


@router.post("/ingest_text", status_code=200)
async def ingest_text(req: IngestTextRequest):
    """Directly ingest plain text (no file upload).

    Creates a document record, indexes it for RAG, and returns immediately
    with status='ready'.  Suitable for hub/email/Teams integrations.
    """
    if not req.text.strip():
        raise HTTPException(status_code=422, detail="'text' must not be empty")

    doc_id = str(uuid.uuid4())
    text = req.text
    tc = count_tokens(text)

    doc = {
        "id": doc_id,
        "filename": f"{doc_id}.txt",
        "original_name": req.title,
        "file_format": "txt",
        "file_size": len(text.encode("utf-8")),
        "uploaded_at": datetime.utcnow().isoformat(),
        "text_length": len(text),
        "token_count": tc,
        "status": "ready",
        "external_id": req.external_id,
        "source": req.source,
        "tags": None,
        "language": req.language,
    }
    db.save_document(doc)

    # Index synchronously – text is already in memory, no I/O needed
    try:
        index_document(doc_id, text)
    except Exception as exc:
        logger.error("RAG indexing failed for ingest_text doc %s: %s", doc_id, exc)
        db.update_document_status(doc_id, "error")
        raise HTTPException(status_code=500, detail=f"Indexing failed: {exc}")

    logger.info("Ingested text doc %s (%d chars / %d tokens)", doc_id, len(text), tc)
    return {"id": doc_id, "status": "ready"}
