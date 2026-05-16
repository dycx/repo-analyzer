"""Markdown utilities for heading normalization and TOC generation.

Provides functions to shift heading levels, generate table of contents,
and create GitHub-compatible anchor IDs (with CJK support).
"""

from __future__ import annotations


import html
import re

# Pattern to match fenced code blocks (to protect them from heading processing)
_FENCED_CODE_RE = re.compile(r"^(`{3,})", re.MULTILINE)

# Pattern to match Markdown headings
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def normalize_headings(content: str, base_level: int = 2) -> str:
    """Shift all heading levels so the minimum heading becomes base_level.

    Protects content inside fenced code blocks from modification.
    Removes empty headings (heading with no text after stripping).

    Args:
        content: Markdown content.
        base_level: The desired minimum heading level (e.g., 2 for h2).

    Returns:
        Content with normalized heading levels.
    """
    # Split content into code blocks and non-code segments
    segments = _split_by_code_blocks(content)

    result_parts: list[str] = []
    for segment, is_code in segments:
        if is_code:
            result_parts.append(segment)
        else:
            result_parts.append(_shift_headings(segment, base_level))

    return "".join(result_parts)


def _split_by_code_blocks(content: str) -> list[tuple[str, bool]]:
    """Split content into alternating (text, is_code) segments.

    Args:
        content: Full markdown content.

    Returns:
        List of (segment_text, is_code_block) tuples.
    """
    segments: list[tuple[str, bool]] = []
    in_code = False
    current_start = 0
    fence_char = ""

    for m in _FENCED_CODE_RE.finditer(content):
        fence = m.group(1)
        pos = m.start()

        if not in_code:
            # Everything before this fence is text
            if pos > current_start:
                segments.append((content[current_start:pos], False))
            in_code = True
            fence_char = fence
            current_start = pos
        elif fence == fence_char:
            # Closing fence -- include everything from open to close as code
            segments.append((content[current_start:m.end()], True))
            in_code = False
            current_start = m.end()
            fence_char = ""

    # Remaining content
    if current_start < len(content):
        remaining = content[current_start:]
        segments.append((remaining, in_code))

    return segments


def _shift_headings(text: str, base_level: int) -> str:
    """Shift heading levels in a text segment.

    Finds the minimum heading level and shifts all headings so that
    the minimum becomes base_level. Removes headings that would exceed h6
    or that are empty after stripping.

    Args:
        text: Text segment (not inside code blocks).
        base_level: Target minimum heading level.

    Returns:
        Text with shifted headings.
    """
    headings: list[tuple[int, str, str]] = []  # (level, text, full_match)
    for m in _HEADING_RE.finditer(text):
        level = len(m.group(1))
        heading_text = m.group(2).strip()
        headings.append((level, heading_text, m.group(0)))

    if not headings:
        return text

    # Find minimum heading level
    min_level = min(h[0] for h in headings)
    shift = base_level - min_level

    result = text
    for level, heading_text, full_match in headings:
        new_level = level + shift
        # Skip headings that would be invalid
        if new_level > 6 or new_level < 1 or not heading_text:
            # Remove empty or out-of-range headings
            result = result.replace(full_match, "", 1)
            continue
        new_heading = f'{"#" * new_level} {heading_text}'
        result = result.replace(full_match, new_heading, 1)

    return result


def generate_toc(content: str) -> str:
    """Generate a Markdown table of contents from headings.

    Skips headings inside fenced code blocks.
    Uses GitHub-compatible anchor format.

    Args:
        content: Markdown content.

    Returns:
        TOC as a Markdown nested list.
    """
    segments = _split_by_code_blocks(content)
    headings: list[tuple[int, str]] = []

    for segment, is_code in segments:
        if is_code:
            continue
        for m in _HEADING_RE.finditer(segment):
            level = len(m.group(1))
            text = m.group(2).strip()
            if text:
                headings.append((level, text))

    if not headings:
        return ""

    # Find minimum level for indentation
    min_level = min(h[0] for h in headings)

    toc_lines: list[str] = []
    for level, text in headings:
        indent = "  " * (level - min_level)
        anchor = _make_anchor(text)
        safe_text = html.escape(text)
        toc_lines.append(f'{indent}- [{safe_text}](#{anchor})')

    return "\n".join(toc_lines)


def _make_anchor(text: str) -> str:
    """Generate a GitHub-compatible anchor from heading text.

    Rules:
    - Convert to lowercase
    - Replace spaces with hyphens
    - Remove characters that are not alphanumeric, hyphens, or CJK
    - Preserve CJK characters (Chinese, Japanese, Korean)
    - Strip leading/trailing hyphens

    Args:
        text: Heading text.

    Returns:
        Anchor string safe for use in URL fragments and HTML id attributes.
    """
    # Lowercase
    anchor = text.lower()

    # Remove backtick wrappers (inline code in headings)
    anchor = anchor.replace("`", "")

    # Replace spaces with hyphens
    anchor = anchor.replace(" ", "-")

    # Remove characters that are not: alphanumeric, hyphen, underscore, or CJK
    anchor = re.sub(r"[^\w一-鿿㐀-䶿豈-﫿　-〿＀-￯-]", "", anchor)

    # Collapse multiple hyphens
    anchor = re.sub(r"-{2,}", "-", anchor)

    # Strip leading/trailing hyphens
    anchor = anchor.strip("-")

    return anchor
