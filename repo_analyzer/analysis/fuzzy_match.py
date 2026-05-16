"""Fuzzy name matching for cross-validation.

Matches identifiers across naming conventions (camelCase, snake_case,
namespaced, qualified) using token overlap and similarity scoring.
"""

from __future__ import annotations


import logging
import re
from difflib import SequenceMatcher

logger = logging.getLogger("repo_analyzer.analysis.fuzzy_match")

# Pre-compiled patterns for identifier splitting
_CAMEL_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)")
_SNAKE_RE = re.compile(r"[^a-zA-Z0-9]+")
_NAMESPACE_RE = re.compile(r"::|\.|/")
_QUALIFIER_RE = re.compile(r"::")


def _split_identifier(name: str) -> list[str]:
    """Split an identifier into lowercase tokens.

    Handles:
    - camelCase / PascalCase  -> ["camel", "case"]
    - snake_case              -> ["snake", "case"]
    - kebab-case              -> ["kebab", "case"]
    - Mixed                   -> all tokens

    Parameters
    ----------
    name : str
        Identifier to split.

    Returns
    -------
    list[str]
        Lowercase tokens extracted from the identifier.
    """
    if not name:
        return []

    # First, split on namespace/qualifier separators
    parts = _NAMESPACE_RE.split(name)

    tokens: list[str] = []
    for part in parts:
        if not part:
            continue
        # Try camelCase splitting
        camel_tokens = _CAMEL_RE.findall(part)
        if camel_tokens:
            tokens.extend(t.lower() for t in camel_tokens)
        else:
            # Fallback: split on non-alphanumeric
            snake_tokens = _SNAKE_RE.split(part)
            tokens.extend(t.lower() for t in snake_tokens if t)

    return tokens


def _strip_namespace(name: str) -> str:
    """Remove namespace prefixes, keeping the last segment.

    Examples:
    - ``ngx::http::process_request`` -> ``process_request``
    - ``com.example.MyClass``        -> ``MyClass``
    - ``std::vector``                -> ``vector``
    """
    parts = _NAMESPACE_RE.split(name)
    return parts[-1] if parts else name


def _token_overlap(tokens_a: list[str], tokens_b: list[str]) -> float:
    """Compute Jaccard-like overlap between two token lists.

    Returns a score between 0.0 and 1.0 based on shared tokens.
    """
    if not tokens_a or not tokens_b:
        return 0.0

    set_a = set(tokens_a)
    set_b = set(tokens_b)

    intersection = set_a & set_b
    union = set_a | set_b

    if not union:
        return 0.0

    return len(intersection) / len(union)


def _sequence_similarity(a: str, b: str) -> float:
    """Compute sequence matcher ratio between two strings."""
    return SequenceMatcher(None, a, b).ratio()


def fuzzy_match_name(
    name: str,
    candidates: set[str],
    threshold: float = 0.7,
) -> list[str]:
    """Match *name* against *candidates* using multi-strategy fuzzy matching.

    Strategies applied in order:
    1. **Exact match** after namespace stripping.
    2. **Method qualifier splitting**: ``Class::method`` matches ``method``.
    3. **Token overlap**: split both sides into tokens, compute Jaccard overlap.
    4. **Sequence similarity**: fallback on SequenceMatcher ratio.

    Parameters
    ----------
    name : str
        Identifier to look up.
    candidates : set[str]
        Known identifiers to match against.
    threshold : float
        Minimum similarity score to accept (0.0 - 1.0).

    Returns
    -------
    list[str]
        Matching candidate names, sorted by relevance (best first).
    """
    if not name or not candidates:
        return []

    # Normalize the search name
    name_lower = name.strip().lower()
    name_stripped = _strip_namespace(name_lower)
    name_tokens = _split_identifier(name)

    scored: list[tuple[str, float]] = []

    for candidate in candidates:
        cand_lower = candidate.strip().lower()
        cand_stripped = _strip_namespace(cand_lower)
        cand_tokens = _split_identifier(candidate)

        # Strategy 1: Exact match (or after namespace strip)
        if name_lower == cand_lower or name_stripped == cand_stripped:
            scored.append((candidate, 1.0))
            continue

        # Strategy 2: Method qualifier splitting
        # e.g. "Class::method" should match "method"
        name_parts = set(_QUALIFIER_RE.split(name_lower))
        cand_parts = set(_QUALIFIER_RE.split(cand_lower))
        if name_parts & cand_parts:
            # At least one qualifier segment matches
            overlap = len(name_parts & cand_parts) / len(name_parts | cand_parts)
            if overlap >= threshold:
                scored.append((candidate, overlap))
                continue

        # Strategy 3: Token overlap
        tok_score = _token_overlap(name_tokens, cand_tokens)
        if tok_score >= threshold:
            scored.append((candidate, tok_score))
            continue

        # Strategy 4: Sequence similarity on stripped names
        seq_score = _sequence_similarity(name_stripped, cand_stripped)
        if seq_score >= threshold:
            scored.append((candidate, seq_score))

    # Sort by score descending, then alphabetically
    scored.sort(key=lambda x: (-x[1], x[0]))

    matches = [name for name, _ in scored]

    if matches:
        logger.debug(
            "Fuzzy match '%s': found %d candidates (best=%s, score=%.2f)",
            name, len(matches), scored[0][0], scored[0][1],
        )

    return matches
