"""
rag_service.py – Retrieval-Augmented Generation helpers.

Steps:
  1. Split document text into overlapping chunks.
  2. Embed each chunk using a local sentence-transformers model.
  3. On query, embed the question and do cosine-similarity search in SQLite.
  4. Return the top-K most relevant chunks for the LLM prompt.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

from ..config import get_settings
from .. import database as db

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Chunking
# ──────────────────────────────────────────────────────────────────────────────

def split_text_chars(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split *text* into overlapping character-level chunks."""
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        if end >= len(text):
            break
        start += chunk_size - overlap
    return chunks


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split *text* into chunks that respect sentence boundaries."""
    import re
    if not text:
        return []
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks = []
    current_chunk: list[str] = []
    current_len = 0

    for sentence in sentences:
        sentence_len = len(sentence)
        if current_len + sentence_len > chunk_size and current_chunk:
            chunks.append(' '.join(current_chunk))
            overlap_chunk: list[str] = []
            overlap_len = 0
            for s in reversed(current_chunk):
                if overlap_len + len(s) <= overlap:
                    overlap_chunk.insert(0, s)
                    overlap_len += len(s)
                else:
                    break
            current_chunk = overlap_chunk
            current_len = overlap_len
        current_chunk.append(sentence)
        current_len += sentence_len

    if current_chunk:
        chunks.append(' '.join(current_chunk))

    return chunks if chunks else [text]


# ──────────────────────────────────────────────────────────────────────────────
# Embeddings (sentence-transformers)
# ──────────────────────────────────────────────────────────────────────────────

_model = None  # lazy-loaded


def _get_embedding_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            name = get_settings().rag.embedding_model
            logger.info("Loading embedding model: %s", name)
            _model = SentenceTransformer(name)
        except ImportError:
            logger.warning(
                "sentence-transformers not installed. "
                "RAG /ask will fall back to full-document context."
            )
    return _model


def embed_texts(texts: list[str]) -> Optional[list[list[float]]]:
    """Return embeddings for a list of texts, or None if unavailable."""
    model = _get_embedding_model()
    if model is None:
        return None
    embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    return [e.tolist() for e in embeddings]


# ──────────────────────────────────────────────────────────────────────────────
# Cosine similarity
# ──────────────────────────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def index_document(doc_id: str, text: str) -> None:
    """Split, embed, and store chunks for *doc_id*."""
    cfg = get_settings().rag
    from ..utils.token_counter import count_tokens

    chunks = split_text(text, cfg.chunk_size, cfg.chunk_overlap)
    if not chunks:
        return

    token_counts = [count_tokens(c) for c in chunks]
    chunk_ids = db.save_chunks(doc_id, chunks, token_counts)

    # Try to embed; silently skip if sentence-transformers not available
    embeddings = embed_texts(chunks)
    if embeddings:
        db.save_embeddings(chunk_ids, embeddings)


def retrieve_relevant_chunks(doc_id: str, question: str, top_k: int | None = None) -> list[str]:
    """Return the top-K most relevant chunks for *question* from *doc_id*.

    Falls back to the first top_k chunks when embeddings are unavailable.
    """
    cfg = get_settings().rag
    k = top_k or cfg.top_k

    stored = db.get_embeddings_for_doc(doc_id)
    if not stored:
        # No embeddings: return first k chunks by index
        chunks = db.get_document_chunks(doc_id)
        return [c["content"] for c in chunks[:k]]

    q_emb = embed_texts([question])
    if q_emb is None:
        chunks = db.get_document_chunks(doc_id)
        return [c["content"] for c in chunks[:k]]

    q_vec = q_emb[0]
    scored = [
        (content, _cosine(q_vec, emb))
        for (_, content, emb) in stored
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [text for text, _ in scored[:k]]
