"""CLI-facing pipeline for output-oriented dataflow tracing."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from repo_analyzer.traces.dataflow import build_output_traces
from repo_analyzer.traces.jvm_analyzer import analyze_jvm_file
from repo_analyzer.traces.models import AnalysisFacts
from repo_analyzer.traces.python_analyzer import analyze_python_file
from repo_analyzer.traces.report import write_trace_outputs
from repo_analyzer.traces.sql_analyzer import analyze_sql_file
from repo_analyzer.traces.xml_analyzer import analyze_xml_file

logger = logging.getLogger("repo_analyzer.trace")

SUPPORTED_EXTS = {".py", ".java", ".scala", ".sql", ".xml"}
SKIP_DIRS = {
    ".git", ".svn", ".hg", ".venv", "venv", "env", ".env", "__pycache__",
    "node_modules", "dist", "build", "target", ".gradle", ".idea",
    ".vscode", ".cache", ".code-analysis",
}
TEST_HINTS = {
    "/test/", "/tests/", "/src/test/", "_test.", "test_", "Test.java",
    "Tests.java", "Spec.scala", "Suite.scala",
}


def parse_trace_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="repo-analyzer trace",
        description="Generate output-oriented dataflow and algorithm documentation.",
    )
    parser.add_argument("repo_path", help="Path to the repository to trace")
    parser.add_argument("--output", "-o", help="Markdown output path")
    parser.add_argument("--max-files", type=int, default=5000, help="Maximum source files to scan")
    parser.add_argument("--include-tests", action="store_true", help="Include test files")
    parser.add_argument("--no-json", action="store_true", help="Do not emit companion JSON")
    return parser.parse_args(argv)


def run_trace_command(argv: list[str] | None = None) -> tuple[Path, Path | None]:
    args = parse_trace_args(argv)
    repo_path = Path(args.repo_path).resolve()
    if not repo_path.is_dir():
        raise SystemExit(f"Not a directory: {repo_path}")

    output = Path(args.output).resolve() if args.output else repo_path.parent / f"{repo_path.name}-output-trace.md"
    facts = collect_trace_facts(repo_path, max_files=args.max_files, include_tests=args.include_tests)
    traces = build_output_traces(facts)
    md_path, json_path = write_trace_outputs(
        traces=traces,
        facts=facts,
        output_path=output,
        repo_name=repo_path.name,
        emit_json=not args.no_json,
    )
    logger.info("Trace report -> %s", md_path)
    if json_path:
        logger.info("Trace JSON   -> %s", json_path)
    return md_path, json_path


def collect_trace_facts(
    repo_path: Path,
    max_files: int = 5000,
    include_tests: bool = False,
) -> AnalysisFacts:
    facts = AnalysisFacts(repo_path=str(repo_path))
    files = list(_iter_source_files(repo_path, include_tests=include_tests))
    if len(files) > max_files:
        facts.warnings.append(f"File count capped at {max_files}; {len(files) - max_files} files skipped")
        files = files[:max_files]

    logger.info("[Trace] Scanning %d source/config files", len(files))
    for idx, path in enumerate(files, start=1):
        if idx % 200 == 0:
            logger.info("  Progress: %d/%d", idx, len(files))
        try:
            ext = path.suffix.lower()
            if ext == ".py":
                facts.merge(analyze_python_file(str(path), str(repo_path)))
            elif ext in {".java", ".scala"}:
                facts.merge(analyze_jvm_file(str(path), str(repo_path)))
            elif ext == ".sql":
                facts.merge(analyze_sql_file(str(path), str(repo_path)))
            elif ext == ".xml":
                facts.merge(analyze_xml_file(str(path), str(repo_path)))
        except Exception as exc:
            rel = path.relative_to(repo_path)
            facts.warnings.append(f"Failed to analyze {rel}: {exc}")

    _dedupe_facts(facts)
    logger.info(
        "[Trace] Inputs=%d Outputs=%d Steps=%d Warnings=%d",
        len(facts.inputs), len(facts.outputs), len(facts.steps), len(facts.warnings),
    )
    return facts


def _iter_source_files(repo_path: Path, include_tests: bool) -> list[Path]:
    result: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".")
        ]
        for fname in filenames:
            path = Path(dirpath) / fname
            if path.suffix.lower() not in SUPPORTED_EXTS:
                continue
            rel = "/" + path.relative_to(repo_path).as_posix()
            if not include_tests and any(hint in rel for hint in TEST_HINTS):
                continue
            result.append(path)
    return sorted(result)


def _dedupe_facts(facts: AnalysisFacts) -> None:
    seen_inputs: set[tuple[str, str, int, str]] = set()
    unique_inputs = []
    for item in facts.inputs:
        key = (item.ref, item.location.file, item.location.line, item.evidence)
        if key not in seen_inputs:
            seen_inputs.add(key)
            unique_inputs.append(item)
    facts.inputs = unique_inputs

    seen_outputs: set[tuple[str, str, int, str]] = set()
    unique_outputs = []
    for item in facts.outputs:
        key = (item.name, item.location.file, item.location.line, item.evidence)
        if key not in seen_outputs:
            seen_outputs.add(key)
            unique_outputs.append(item)
    facts.outputs = unique_outputs

    seen_steps: set[tuple[str, str, int, str, str]] = set()
    unique_steps = []
    for item in facts.steps:
        key = (item.output_ref, item.location.file, item.location.line, item.step_type, item.evidence)
        if key not in seen_steps:
            seen_steps.add(key)
            unique_steps.append(item)
    facts.steps = unique_steps
