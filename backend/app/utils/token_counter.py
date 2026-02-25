"""
token_counter.py – lightweight token estimation without external dependencies.
Falls back to simple whitespace splitting when tiktoken is unavailable.
"""
from __future__ import annotations

try:
    import tiktoken

    _enc = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        return len(_enc.encode(text))

except ImportError:
    def count_tokens(text: str) -> int:  # type: ignore[misc]
        # Rough estimate: ~4 chars per token (works for most languages)
        return max(1, len(text) // 4)
