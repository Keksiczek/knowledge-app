"""
providers/__init__.py – Provider registry and factory.

Exports:
  get_provider()      – return the currently active LLMProvider instance
  switch_provider()   – change the active provider (and optionally model)
  list_providers()    – return status of all configured providers
  PROVIDER_NAMES      – set of all known provider keys
"""
from __future__ import annotations

import logging
from typing import Optional

from ...config import get_settings
from .base import LLMProvider
from .ollama import OllamaProvider
from .openai_compatible import OpenAICompatibleProvider
from .openai_provider import OpenAIProvider
from .anthropic_provider import AnthropicProvider
from .text_generation_webui import TextGenWebUIProvider

logger = logging.getLogger(__name__)

# All recognised provider keys
PROVIDER_NAMES = {
    "ollama",
    "lm_studio",
    "localai",
    "text_generation_webui",
    "openai",
    "anthropic",
}

# ── Runtime state (module-level singletons) ───────────────────────────────────
_active_name: Optional[str] = None    # current provider key
_active_model: Optional[str] = None   # model override (None = use default)
_instance_cache: dict[str, LLMProvider] = {}


def _build_provider(name: str, model_override: Optional[str] = None) -> LLMProvider:
    """Instantiate the requested provider from current config."""
    settings = get_settings()
    gen = settings.llm.generation
    providers = settings.llm.providers

    cfg = providers.get(name)
    if cfg is None:
        raise ValueError(f"Provider '{name}' is not configured in config.yaml")

    model = model_override or cfg.default_model

    if name == "ollama":
        return OllamaProvider(
            base_url=cfg.base_url, model=model, timeout=cfg.timeout, generation=gen
        )

    if name in ("lm_studio", "localai"):
        return OpenAICompatibleProvider(
            provider_key=name,
            base_url=cfg.base_url,
            model=model,
            api_key=cfg.api_key,
            timeout=cfg.timeout,
            generation=gen,
        )

    if name == "openai":
        return OpenAIProvider(
            model=model,
            api_key=cfg.api_key,
            organization=cfg.organization,
            timeout=cfg.timeout,
            generation=gen,
        )

    if name == "anthropic":
        return AnthropicProvider(
            model=model,
            api_key=cfg.api_key,
            timeout=cfg.timeout,
            generation=gen,
        )

    if name == "text_generation_webui":
        return TextGenWebUIProvider(
            base_url=cfg.base_url, model=model, timeout=cfg.timeout, generation=gen
        )

    raise ValueError(
        f"Unknown provider '{name}'. Known: {sorted(PROVIDER_NAMES)}"
    )


def get_provider() -> LLMProvider:
    """Return the currently active provider instance (created lazily)."""
    global _active_name, _active_model

    # Initialise from config on first call
    if _active_name is None:
        _active_name = get_settings().llm.default_provider

    cache_key = f"{_active_name}:{_active_model or ''}"
    if cache_key not in _instance_cache:
        logger.info("Initialising LLM provider: %s (model=%s)", _active_name, _active_model or "default")
        _instance_cache[cache_key] = _build_provider(_active_name, _active_model)

    return _instance_cache[cache_key]


def switch_provider(name: str, model: Optional[str] = None) -> LLMProvider:
    """Switch to a different provider (and optionally model).

    The new provider is instantiated immediately so any connection errors
    surface at switch time rather than at the next generate() call.
    """
    global _active_name, _active_model

    if name not in PROVIDER_NAMES and name not in get_settings().llm.providers:
        raise ValueError(f"Unknown provider: '{name}'")

    cache_key = f"{name}:{model or ''}"
    if cache_key not in _instance_cache:
        _instance_cache[cache_key] = _build_provider(name, model)

    _active_name = name
    _active_model = model
    logger.info("Switched provider to: %s (model=%s)", name, model or "default")
    return _instance_cache[cache_key]


def list_providers() -> list[dict]:
    """Return status dicts for all configured providers."""
    settings = get_settings()
    active = _active_name or settings.llm.default_provider
    rows = []
    for name, cfg in settings.llm.providers.items():
        rows.append({
            "name": name,
            "enabled": cfg.enabled,
            "base_url": cfg.base_url,
            "default_model": cfg.default_model,
            "has_api_key": bool(cfg.api_key),
            "active": name == active,
        })
    return rows
