"""
providers.py – LLM provider management endpoints.

GET  /api/providers               – list all configured providers + active status
GET  /api/providers/active        – current provider name, model, and metadata
POST /api/providers/switch        – switch active provider (and optionally model)
GET  /api/providers/{name}/models – list available models for a provider
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import llm_service
from ..services.providers import PROVIDER_NAMES, get_provider, list_providers, switch_provider

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/providers", tags=["providers"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class SwitchRequest(BaseModel):
    provider: str
    model: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
async def get_providers():
    """Return configuration status for all known providers."""
    return {"providers": list_providers()}


@router.get("/active")
async def get_active_provider():
    """Return the currently active provider and its active model."""
    p = get_provider()
    return {
        "provider": p.provider_name,
        "model":    p.active_model,
    }


@router.post("/switch")
async def switch_active_provider(req: SwitchRequest):
    """Switch to a different provider (and optionally a specific model).

    The provider must be listed in config.yaml providers section.
    If *model* is omitted the provider's `default_model` is used.
    """
    all_providers = {row["name"] for row in list_providers()}
    if req.provider not in all_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{req.provider}'. Available: {sorted(all_providers)}",
        )
    try:
        p = switch_provider(req.provider, req.model)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to initialise provider: {exc}")

    return {
        "switched_to": p.provider_name,
        "model":       p.active_model,
    }


@router.get("/{name}/models")
async def get_provider_models(name: str):
    """Return available model names for the given provider.

    For local providers this makes a live request to the running service.
    For cloud providers it returns a curated list.
    """
    all_providers = {row["name"] for row in list_providers()}
    if name not in all_providers:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{name}' not found. Available: {sorted(all_providers)}",
        )
    try:
        from ..services.providers import _build_provider
        p = _build_provider(name)
        models = p.get_models()
    except Exception as exc:
        logger.warning("Could not fetch models for %s: %s", name, exc)
        models = []

    return {"provider": name, "models": models}
