"""
main.py – FastAPI application entry point for Knowledge App.

Run locally:
    uvicorn app.main:app --reload --port 8000

Or via Docker:
    docker-compose up
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import init_db, get_db
from .routers import ask, highlights, models, presentation, summarize, upload

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# App factory
# ──────────────────────────────────────────────────────────────────────────────

settings = get_settings()

app = FastAPI(
    title="Knowledge App",
    description=(
        "Offline-first document intelligence: upload files, extract text, "
        "and use a local LLM for summaries, highlights, presentations, and Q&A."
    ),
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS – allow the frontend (served separately during dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.app.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────────────────────────────────────
# API key authentication middleware (optional – disabled when api_key is empty)
# ──────────────────────────────────────────────────────────────────────────────

@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    api_key = settings.security.api_key
    path = request.url.path
    # Only guard /api/v1/ routes; health is always exempt
    if (
        api_key
        and path.startswith("/api/v1/")
        and not path.startswith("/api/v1/health")
    ):
        provided = request.headers.get("X-API-Key", "")
        if provided != api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid API key"},
            )
    return await call_next(request)


# ──────────────────────────────────────────────────────────────────────────────
# Request timing middleware
# ──────────────────────────────────────────────────────────────────────────────

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    response.headers["X-Process-Time"] = f"{duration:.3f}s"
    return response

# ──────────────────────────────────────────────────────────────────────────────
# Startup / shutdown
# ──────────────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    logger.info("Initialising database …")
    init_db()
    _cleanup_stale_documents()
    logger.info("Knowledge App started — LLM backend: %s", settings.llm.backend)


def _cleanup_stale_documents() -> None:
    """Mark documents stuck in pending/processing for >1h as error on startup."""
    cutoff = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    try:
        with get_db() as conn:
            cur = conn.execute(
                """UPDATE documents SET status='error'
                   WHERE status IN ('pending', 'processing')
                   AND uploaded_at < ?""",
                (cutoff,),
            )
        if cur.rowcount:
            logger.warning("Startup cleanup: marked %d stale document(s) as error", cur.rowcount)
    except Exception as exc:
        logger.error("Startup cleanup failed: %s", exc)


# ──────────────────────────────────────────────────────────────────────────────
# Routers
# ──────────────────────────────────────────────────────────────────────────────

app.include_router(upload.router)
app.include_router(summarize.router)
app.include_router(highlights.router)
app.include_router(presentation.router)
app.include_router(ask.router)
app.include_router(models.router)

# ──────────────────────────────────────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/health", tags=["system"])
async def health():
    doc_count = chunk_count = storage_mb = 0
    embeddings_enabled = False
    try:
        with get_db() as conn:
            doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            chunk_count = conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
            size_row = conn.execute(
                "SELECT COALESCE(SUM(file_size), 0) / 1048576.0 FROM documents"
            ).fetchone()
            storage_mb = round(size_row[0], 2) if size_row else 0.0
            emb_row = conn.execute(
                "SELECT EXISTS(SELECT 1 FROM chunk_embeddings LIMIT 1)"
            ).fetchone()
            embeddings_enabled = bool(emb_row[0]) if emb_row else False
    except Exception:
        pass

    return {
        "status": "ok",
        "llm_backend": settings.llm.backend,
        "llm_model": settings.llm.ollama.model,
        "db_engine": settings.database.engine,
        "embeddings_enabled": embeddings_enabled,
        "documents": doc_count,
        "chunks": chunk_count,
        "storage_used_mb": storage_mb,
    }

# ──────────────────────────────────────────────────────────────────────────────
# Serve frontend static files (production build)
# ──────────────────────────────────────────────────────────────────────────────

_FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"

if _FRONTEND_DIR.exists():
    # Serve static assets (JS, CSS, images)
    _PUBLIC_DIR = _FRONTEND_DIR / "public"
    if _PUBLIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_PUBLIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str = ""):
        # Don't intercept API or docs routes
        if full_path.startswith("api/") or full_path.startswith("static/") or full_path.startswith("api/v1/"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        index = _FRONTEND_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse(status_code=404, content={"detail": "Frontend not built"})
