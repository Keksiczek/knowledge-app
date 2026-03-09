"""
config.py – loads config.yaml and exposes typed settings throughout the app.

Environment variable overrides (all optional):
  KNOWLEDGE_APP_LLM_MODEL   → llm.ollama.model
  KNOWLEDGE_APP_DB_PATH     → database.path  (absolute path overrides BASE_DIR resolution)
  KNOWLEDGE_APP_PORT        → app.port
  KNOWLEDGE_CONFIG          → path to config.yaml (default: repo root)
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

# Repo root – three levels up from this file (backend/app/config.py → repo root)
BASE_DIR: Path = Path(__file__).parent.parent.parent.resolve()


# ──────────────────────────────────────────────────────────────────────────────
# Pydantic models that mirror config.yaml structure
# ──────────────────────────────────────────────────────────────────────────────

class OllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = "llama3.2"
    timeout: int = 120


class LMStudioConfig(BaseModel):
    base_url: str = "http://localhost:1234/v1"
    model: str = "local-model"
    timeout: int = 120


class TextGenConfig(BaseModel):
    base_url: str = "http://localhost:5000"
    model: str = ""
    timeout: int = 120


class GenerationConfig(BaseModel):
    temperature: float = 0.2
    max_tokens: int = 4096
    top_p: float = 0.9


class LLMConfig(BaseModel):
    backend: str = "ollama"
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    lmstudio: LMStudioConfig = Field(default_factory=LMStudioConfig)
    textgen: TextGenConfig = Field(default_factory=TextGenConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)


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


class SecurityConfig(BaseModel):
    api_key: str = ""  # empty = disabled


class Settings(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    app: AppConfig = Field(default_factory=AppConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)


# ──────────────────────────────────────────────────────────────────────────────
# Loader
# ──────────────────────────────────────────────────────────────────────────────

def _find_config() -> Path:
    """Walk up from this file looking for config.yaml."""
    candidates = [
        Path(os.environ.get("KNOWLEDGE_CONFIG", "")),
        BASE_DIR / "config.yaml",                        # repo root
        Path(__file__).parent.parent / "config.yaml",    # backend/
    ]
    for c in candidates:
        if c.is_file():
            return c
    return candidates[1]  # default – may not exist, falls back to defaults


def _resolve_path(raw: str) -> str:
    """If *raw* is a relative path, resolve it against BASE_DIR."""
    p = Path(raw)
    if p.is_absolute():
        return str(p)
    return str(BASE_DIR / p)


def _apply_env_overrides(s: Settings) -> None:
    """Apply KNOWLEDGE_APP_* environment variable overrides in-place."""
    if model := os.environ.get("KNOWLEDGE_APP_LLM_MODEL"):
        s.llm.ollama.model = model
    if db_path := os.environ.get("KNOWLEDGE_APP_DB_PATH"):
        s.database.path = db_path
    if port := os.environ.get("KNOWLEDGE_APP_PORT"):
        s.app.port = int(port)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    cfg_path = _find_config()
    if cfg_path.is_file():
        with open(cfg_path) as f:
            raw = yaml.safe_load(f) or {}
        s = Settings(**raw)
    else:
        s = Settings()

    # Resolve relative paths against BASE_DIR
    s.database.path = _resolve_path(s.database.path)
    s.storage.upload_dir = _resolve_path(s.storage.upload_dir)

    # Apply environment variable overrides last (highest priority)
    _apply_env_overrides(s)

    return s
