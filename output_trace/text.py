"""Text helpers used by the greenfield analyzer."""

from __future__ import annotations

import re
from pathlib import Path


STRING_RE = re.compile(r"""["']([^"']+)["']""")
IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")


def compact(text: str, limit: int = 260) -> str:
    value = " ".join(str(text).strip().split())
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def string_literals(text: str) -> list[str]:
    return [match.group(1) for match in STRING_RE.finditer(text)]


def first_string(text: str, fallback: str = "") -> str:
    values = string_literals(text)
    return values[0] if values else fallback


def identifiers(text: str) -> list[str]:
    return [match.group(0) for match in IDENT_RE.finditer(text)]


def unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def slug_ref(prefix: str, file_path: str, line: int, name: str = "") -> str:
    safe_file = Path(file_path).as_posix().replace("/", "_").replace(".", "_")
    safe_name = re.sub(r"\W+", "_", name).strip("_")
    ref = f"{prefix}:{safe_file}:{line}"
    return f"{ref}:{safe_name}" if safe_name else ref


def path_format(text: str) -> str:
    lowered = text.lower()
    for fmt in ("parquet", "csv", "json", "orc", "avro", "xml", "xlsx", "xls", "txt"):
        if fmt in lowered:
            return fmt
    return ""


def line_for_offset(text: str, offset: int) -> int:
    return text[:offset].count("\n") + 1

