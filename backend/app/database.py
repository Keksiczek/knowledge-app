"""
database.py – SQLite persistence layer (DuckDB-compatible design).
Creates all tables on startup and exposes helper functions used by the routers.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, Optional

from .config import get_settings

# Thread-local storage so each request gets its own connection
_local = threading.local()


def _db_path() -> Path:
    settings = get_settings()
    p = Path(settings.database.path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Context manager that yields a SQLite connection with row_factory."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(_db_path()), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield _local.conn
    except Exception:
        _local.conn.rollback()
        raise
    else:
        _local.conn.commit()


# ──────────────────────────────────────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────────────────────────────────────

DDL = """
-- Uploaded documents
CREATE TABLE IF NOT EXISTS documents (
    id            TEXT PRIMARY KEY,
    filename      TEXT NOT NULL,
    original_name TEXT NOT NULL,
    file_format   TEXT NOT NULL,
    file_size     INTEGER NOT NULL,       -- bytes
    uploaded_at   TEXT NOT NULL,
    text_length   INTEGER DEFAULT 0,
    token_count   INTEGER DEFAULT 0,
    status        TEXT DEFAULT 'pending'  -- pending | processing | ready | error
);

-- Extracted plain-text chunks (for RAG)
CREATE TABLE IF NOT EXISTS document_chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content     TEXT NOT NULL,
    token_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks(document_id);

-- Simple vector-less similarity store: we keep chunk embeddings as JSON blobs
CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id    INTEGER PRIMARY KEY REFERENCES document_chunks(id) ON DELETE CASCADE,
    embedding   TEXT NOT NULL   -- JSON array of floats
);

-- LLM output cache
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key   TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    task        TEXT NOT NULL,   -- summarize | highlights | presentation | ask
    prompt_hash TEXT NOT NULL,
    result      TEXT NOT NULL,   -- JSON
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cache_doc ON llm_cache(document_id, task);
"""


def init_db() -> None:
    """Create all tables (idempotent)."""
    with get_db() as conn:
        conn.executescript(DDL)


# ──────────────────────────────────────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────────────────────────────────────

def cache_key(document_id: str, task: str, extra: str = "", model: str = "") -> str:
    if not model:
        from .config import get_settings
        model = get_settings().llm.ollama.model
    raw = f"{document_id}:{task}:{model}:{extra}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_cached_result(doc_id: str, task: str, extra: str = "", model: str = "") -> Optional[dict]:
    key = cache_key(doc_id, task, extra, model)
    with get_db() as conn:
        row = conn.execute(
            "SELECT result FROM llm_cache WHERE cache_key = ?", (key,)
        ).fetchone()
    if row:
        return json.loads(row["result"])
    return None


def save_cached_result(doc_id: str, task: str, result: dict, extra: str = "", model: str = "") -> None:
    key = cache_key(doc_id, task, extra, model)
    prompt_hash = hashlib.md5(extra.encode()).hexdigest()
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO llm_cache
               (cache_key, document_id, task, prompt_hash, result, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (key, doc_id, task, prompt_hash, json.dumps(result),
             datetime.utcnow().isoformat()),
        )


def get_document(doc_id: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
    return dict(row) if row else None


def list_documents() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM documents ORDER BY uploaded_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_document_chunks(doc_id: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM document_chunks WHERE document_id = ? ORDER BY chunk_index",
            (doc_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_full_text(doc_id: str) -> str:
    """Reconstruct full text from stored chunks."""
    chunks = get_document_chunks(doc_id)
    return "\n\n".join(c["content"] for c in chunks)


def save_document(doc: dict) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO documents
               (id, filename, original_name, file_format, file_size,
                uploaded_at, text_length, token_count, status)
               VALUES (:id, :filename, :original_name, :file_format, :file_size,
                       :uploaded_at, :text_length, :token_count, :status)""",
            doc,
        )


def update_document_status(doc_id: str, status: str, **kwargs: Any) -> None:
    fields = {"status": status, **kwargs}
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["id"] = doc_id
    with get_db() as conn:
        conn.execute(f"UPDATE documents SET {set_clause} WHERE id = :id", fields)


def save_chunks(doc_id: str, chunks: list[str], token_counts: list[int]) -> list[int]:
    """Insert chunks and return their IDs."""
    ids = []
    with get_db() as conn:
        for i, (text, tc) in enumerate(zip(chunks, token_counts)):
            cur = conn.execute(
                """INSERT INTO document_chunks (document_id, chunk_index, content, token_count)
                   VALUES (?, ?, ?, ?)""",
                (doc_id, i, text, tc),
            )
            ids.append(cur.lastrowid)
    return ids


def save_embeddings(chunk_ids: list[int], embeddings: list[list[float]]) -> None:
    with get_db() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO chunk_embeddings (chunk_id, embedding) VALUES (?, ?)",
            [(cid, json.dumps(emb)) for cid, emb in zip(chunk_ids, embeddings)],
        )


def get_embeddings_for_doc(doc_id: str) -> list[tuple[int, str, list[float]]]:
    """Returns list of (chunk_id, content, embedding)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT dc.id, dc.content, ce.embedding
               FROM document_chunks dc
               JOIN chunk_embeddings ce ON ce.chunk_id = dc.id
               WHERE dc.document_id = ?
               ORDER BY dc.chunk_index""",
            (doc_id,),
        ).fetchall()
    return [(r["id"], r["content"], json.loads(r["embedding"])) for r in rows]


def delete_document(doc_id: str) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    return cur.rowcount > 0
