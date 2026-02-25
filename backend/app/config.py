"""
config.py – loads config.yaml and exposes typed settings throughout the app.

Key change from v1: the `llm` section now uses a `providers` dict with a
`default_provider` key instead of a flat set of per-backend keys.
String values matching ${VAR_NAME} are expanded from environment variables.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


# ──────────────────────────────────────────────────────────────────────────────
# Env-var expansion helper
# ──────────────────────────────────────────────────────────────────────────────

_ENV_VAR_RE = re.compile(r"^\$\{([^}]+)\}$")


def _expand(value: Any) -> Any:
    """Expand '${VAR_NAME}' strings from the process environment."""
    if isinstance(value, str):
        m = _ENV_VAR_RE.match(value)
        if m:
            return os.environ.get(m.group(1), "")
    return value


# ──────────────────────────────────────────────────────────────────────────────
# Provider config (generic – works for every provider)
# ──────────────────────────────────────────────────────────────────────────────

class ProviderConfig(BaseModel):
    enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    default_model: str = ""
    timeout: int = 120
    # OpenAI-only extras (silently ignored by other providers)
    organization: str = ""

    @field_validator("api_key", "base_url", "default_model", "organization", mode="before")
    @classmethod
    def expand_env_vars(cls, v: Any) -> Any:
        return _expand(v)


def _default_providers() -> dict[str, ProviderConfig]:
    return {
        "ollama": ProviderConfig(
            enabled=True,
            base_url="http://localhost:11434",
            default_model="llama3.2:latest",
            timeout=120,
        ),
        "lm_studio": ProviderConfig(
            base_url="http://localhost:1234/v1",
            default_model="local-model",
            timeout=120,
        ),
        "text_generation_webui": ProviderConfig(
            base_url="http://localhost:5000",
            default_model="default",
            timeout=120,
        ),
        "localai": ProviderConfig(
            base_url="http://localhost:8080/v1",
            default_model="gpt-3.5-turbo",
            timeout=120,
        ),
        "openai": ProviderConfig(
            default_model="gpt-4o",
            timeout=60,
        ),
        "anthropic": ProviderConfig(
            default_model="claude-sonnet-4-5-20250514",
            timeout=60,
        ),
    }


# ──────────────────────────────────────────────────────────────────────────────
# LLM top-level config
# ──────────────────────────────────────────────────────────────────────────────

class GenerationConfig(BaseModel):
    temperature: float = 0.2
    max_tokens: int = 4096
    top_p: float = 0.9


class LLMConfig(BaseModel):
    default_provider: str = "ollama"
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    providers: dict[str, ProviderConfig] = Field(default_factory=_default_providers)

    @model_validator(mode="before")
    @classmethod
    def merge_providers(cls, data: Any) -> Any:
        """Merge YAML providers with defaults so omitted keys still work."""
        if not isinstance(data, dict):
            return data
        defaults = _default_providers()
        raw_providers = data.get("providers", {})
        merged: dict[str, Any] = {}
        # Start from defaults, overlay YAML values
        for name, default_cfg in defaults.items():
            yaml_cfg = raw_providers.get(name, {})
            if isinstance(yaml_cfg, dict):
                merged[name] = {**default_cfg.model_dump(), **yaml_cfg}
            else:
                merged[name] = default_cfg.model_dump()
        # Include any extra providers defined only in YAML
        for name, cfg in raw_providers.items():
            if name not in merged:
                merged[name] = cfg
        data["providers"] = merged
        return data


# ──────────────────────────────────────────────────────────────────────────────
# Other config sections (unchanged from v1)
# ──────────────────────────────────────────────────────────────────────────────

class DatabaseConfig(BaseModel):
    engine: str = "sqlite"
    path: str = "./data/knowledge.db"


class StorageConfig(BaseModel):
    upload_dir: str = "./uploads"
    max_file_size_mb: int = 50


class RAGConfig(BaseModel):
    chunk_size: int = 512
    chunk_overlap: int = 64
    top_k: int = 5
    embedding_model: str = "all-MiniLM-L6-v2"


class AppConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


class Settings(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    app: AppConfig = Field(default_factory=AppConfig)


# ──────────────────────────────────────────────────────────────────────────────
# Loader
# ──────────────────────────────────────────────────────────────────────────────

def _find_config() -> Path:
    candidates = [
        Path(os.environ.get("KNOWLEDGE_CONFIG", "")),
        Path(__file__).parent.parent.parent / "config.yaml",  # repo root
        Path(__file__).parent.parent / "config.yaml",          # backend/
    ]
    for c in candidates:
        if c.is_file():
            return c
    return candidates[1]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    cfg_path = _find_config()
    if cfg_path.is_file():
        with open(cfg_path) as f:
            raw = yaml.safe_load(f) or {}
        return Settings(**raw)
    return Settings()


def reload_settings() -> Settings:
    """Clear the cache and reload config.yaml (used after hot-reload)."""
    get_settings.cache_clear()
    return get_settings()
