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
from .routers import ask, highlights, presentation, providers, summarize, upload
from .services.providers import get_provider

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
        "Offline-first document intelligence. Upload files and use any local or "
        "cloud LLM (Ollama, LM Studio, OpenAI, Anthropic …) for summaries, "
        "highlights, presentations, and RAG Q&A."
    ),
    version="2.0.0",
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
# Startup
# ──────────────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    logger.info("Initialising database …")
    init_db()
    p = get_provider()
    logger.info(
        "Knowledge App v2 started — provider: %s | model: %s | db: %s",
        p.provider_name, p.active_model, settings.database.engine,
    )

# ──────────────────────────────────────────────────────────────────────────────
# Routers
# ──────────────────────────────────────────────────────────────────────────────

app.include_router(upload.router)
app.include_router(summarize.router)
app.include_router(highlights.router)
app.include_router(presentation.router)
app.include_router(ask.router)
app.include_router(providers.router)

# ──────────────────────────────────────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/api/health", tags=["system"])
async def health():
    p = get_provider()
    return {
        "status": "ok",
        "provider": p.provider_name,
        "model":    p.active_model,
        "db_engine": settings.database.engine,
    }

# ──────────────────────────────────────────────────────────────────────────────
# Frontend static files
# ──────────────────────────────────────────────────────────────────────────────

_FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"

if _FRONTEND_DIR.exists():
    _PUBLIC_DIR = _FRONTEND_DIR / "public"
    if _PUBLIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_PUBLIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str = ""):
        if full_path.startswith("api/") or full_path.startswith("static/"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        index = _FRONTEND_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse(status_code=404, content={"detail": "Frontend not built"})
