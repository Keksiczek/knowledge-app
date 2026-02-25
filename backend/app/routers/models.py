"""
models.py – endpoints for managing and switching Ollama LLM models.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..services.llm_service import reset_backend_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/models", tags=["models"])


class SwitchModelRequest(BaseModel):
    model: str


@router.get("/available")
async def get_available_models():
    """Return list of locally available Ollama models plus current config."""
    settings = get_settings()
    base_url = settings.llm.ollama.base_url.rstrip("/")
    current_model = settings.llm.ollama.model
    current_backend = settings.llm.backend

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{base_url}/api/tags")
            resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Ollama is not reachable at {base_url}. Make sure Ollama is running. ({exc})",
        )

    models = []
    for m in data.get("models", []):
        name = m.get("name", "")
        size_bytes = m.get("size", 0)
        size_mb = round(size_bytes / (1024 * 1024)) if size_bytes else 0
        family = m.get("details", {}).get("family", name.split(":")[0])
        models.append({"name": name, "size_mb": size_mb, "family": family})

    return {
        "current_backend": current_backend,
        "current_model": current_model,
        "available": models,
    }


@router.post("/switch")
async def switch_model(body: SwitchModelRequest):
    """Switch the active Ollama model at runtime without restarting the server."""
    settings = get_settings()
    base_url = settings.llm.ollama.base_url.rstrip("/")
    new_model = body.model.strip()

    # Verify the model actually exists in Ollama
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{base_url}/api/tags")
            resp.raise_for_status()
        available_names = [m.get("name", "") for m in resp.json().get("models", [])]
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Ollama is not reachable at {base_url}. ({exc})",
        )

    if new_model not in available_names:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{new_model}' is not available in Ollama. "
                   f"Run 'ollama pull {new_model}' first. "
                   f"Available: {available_names}",
        )

    # Update the in-memory setting and invalidate cache
    settings.llm.ollama.model = new_model
    reset_backend_cache()
    logger.info("LLM model switched to: %s", new_model)

    return {"message": f"Model přepnut na {new_model}", "model": new_model}


@router.get("/status")
async def get_status():
    """Ping Ollama and return current model/backend info. Never raises 5xx."""
    settings = get_settings()
    base_url = settings.llm.ollama.base_url.rstrip("/")
    current_model = settings.llm.ollama.model
    current_backend = settings.llm.backend

    ollama_running = False
    try:
        with httpx.Client(timeout=5) as client:
            resp = client.get(f"{base_url}/api/tags")
            ollama_running = resp.status_code == 200
    except Exception:
        ollama_running = False

    return {
        "ollama_running": ollama_running,
        "current_model": current_model,
        "current_backend": current_backend,
    }
