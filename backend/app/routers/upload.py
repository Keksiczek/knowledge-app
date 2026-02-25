"""
upload.py – file upload and document management endpoints.

POST /api/upload         – upload one or more files; returns document metadata
GET  /api/documents      – list all documents
GET  /api/documents/{id} – get single document metadata
DELETE /api/documents/{id} – remove document and all derived data
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from ..config import get_settings
from .. import database as db
from ..services.text_extraction import SUPPORTED_EXTENSIONS, extract_text
from ..services.rag_service import index_document
from ..utils.token_counter import count_tokens

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["upload"])


def _upload_dir() -> Path:
    settings = get_settings()
    p = Path(settings.storage.upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _validate_file(file: UploadFile) -> None:
    settings = get_settings()
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{ext}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}",
        )
    # Size check (content_length may be None for chunked uploads)
    max_bytes = settings.storage.max_file_size_mb * 1024 * 1024
    if file.size and file.size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {settings.storage.max_file_size_mb} MB.",
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
        _validate_file(file)
        doc_id = str(uuid.uuid4())
        ext = Path(file.filename or "file").suffix.lower()
        safe_name = f"{doc_id}{ext}"
        dest = upload_dir / safe_name

        # Save raw file
        content = await file.read()
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
