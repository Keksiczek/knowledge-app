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
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import init_db
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
    logger.info("Knowledge App started — LLM backend: %s", settings.llm.backend)


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

@app.get("/api/health", tags=["system"])
async def health():
    return {
        "status": "ok",
        "llm_backend": settings.llm.backend,
        "db_engine": settings.database.engine,
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
        if full_path.startswith("api/") or full_path.startswith("static/"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        index = _FRONTEND_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse(status_code=404, content={"detail": "Frontend not built"})
