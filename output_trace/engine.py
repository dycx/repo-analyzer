"""Top-level greenfield analysis engine."""

from __future__ import annotations

from pathlib import Path

from output_trace.analyzers.jvm import analyze_jvm
from output_trace.analyzers.python import analyze_python
from output_trace.analyzers.xml import analyze_xml
from output_trace.graph import build_traces
from output_trace.ir import FactStore, OutputTrace
from output_trace.scanner import iter_supported_files
from output_trace.sql import analyze_sql_file


def analyze_repository(repo_root: Path, max_files: int = 5000, include_tests: bool = False) -> tuple[FactStore, list[OutputTrace]]:
    facts = FactStore(repo_root=str(repo_root))
    files = iter_supported_files(repo_root, include_tests=include_tests)
    if len(files) > max_files:
        facts.warnings.append(f"File count capped at {max_files}; skipped {len(files) - max_files} supported files")
        files = files[:max_files]

    for path in files:
        rel_path = path.relative_to(repo_root).as_posix()
        try:
            suffix = path.suffix.lower()
            if suffix == ".py":
                facts.extend(analyze_python(str(path), rel_path, str(repo_root)))
            elif suffix in {".java", ".scala"}:
                facts.extend(analyze_jvm(str(path), rel_path, str(repo_root)))
            elif suffix == ".sql":
                facts.extend(analyze_sql_file(str(path), str(repo_root), rel_path))
            elif suffix == ".xml":
                facts.extend(analyze_xml(str(path), rel_path, str(repo_root)))
        except Exception as exc:
            facts.warnings.append(f"Failed to analyze {rel_path}: {exc}")

    _dedupe(facts)
    return facts, build_traces(facts)


def _dedupe(facts: FactStore) -> None:
    facts.sources = _dedupe_items(facts.sources, lambda item: (item.id, item.location.file, item.location.line, item.evidence))
    facts.sinks = _dedupe_items(facts.sinks, lambda item: (item.name, item.location.file, item.location.line, item.evidence))
    facts.operations = _dedupe_items(facts.operations, lambda item: (item.output, item.location.file, item.location.line, item.kind, item.evidence))


def _dedupe_items(items, key_fn):
    seen = set()
    result = []
    for item in items:
        key = key_fn(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result

