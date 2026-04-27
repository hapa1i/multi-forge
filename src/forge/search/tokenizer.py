"""Shared tokenization for BM25 indexing and search.

Used by both extractor (token caching at extraction time) and engine
(query tokenization + snippet anchoring at search time).
"""

from __future__ import annotations

import re

# Matches word-like tokens (letters, digits, underscores).
# Case-insensitive so _best_snippet() can iterate raw mixed-case content
# and match against lowercased query tokens.
TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")

MIN_TOKEN_LENGTH = 2


def tokenize(text: str) -> list[str]:
    """Simple word tokenizer for BM25.

    Lowercase, extract alphanumeric+underscore tokens, filter short tokens.
    """
    return [m for m in TOKEN_RE.findall(text.lower()) if len(m) >= MIN_TOKEN_LENGTH]
