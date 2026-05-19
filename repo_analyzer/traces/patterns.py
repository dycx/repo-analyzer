"""Small parsing helpers shared by trace extractors."""

from __future__ import annotations

import re
from pathlib import Path


STRING_RE = re.compile(r"""["']([^"']+)["']""")
IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")

STOP_WORDS = {
    "and", "as", "case", "class", "def", "else", "false", "for", "from",
    "if", "import", "in", "is", "new", "none", "null", "or", "return",
    "then", "true", "val", "var", "when", "while", "with",
}


def line_at(source: str, line_no: int) -> str:
    lines = source.splitlines()
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1].strip()
    return ""


def string_literals(text: str) -> list[str]:
    return [m.group(1) for m in STRING_RE.finditer(text)]


def first_string_literal(text: str, fallback: str = "") -> str:
    values = string_literals(text)
    return values[0] if values else fallback


def identifiers(text: str) -> list[str]:
    result: list[str] = []
    for match in IDENT_RE.finditer(text):
        name = match.group(0)
        if name.lower() not in STOP_WORDS and not name[0].isdigit():
            result.append(name)
    return result


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def safe_ref(prefix: str, file_path: str, line: int, name: str = "") -> str:
    stem = Path(file_path).as_posix().replace("/", "_").replace(".", "_")
    suffix = re.sub(r"\W+", "_", name).strip("_")
    return f"{prefix}:{stem}:{line}" + (f":{suffix}" if suffix else "")


def classify_path_format(text: str) -> str:
    lowered = text.lower()
    for fmt in ("parquet", "csv", "json", "orc", "avro", "xml", "xlsx", "txt"):
        if fmt in lowered:
            return fmt
    return ""


def summarize_expression(expr: str, limit: int = 220) -> str:
    cleaned = " ".join(expr.strip().split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."

