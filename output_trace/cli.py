"""Command-line interface for the greenfield output trace analyzer."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from output_trace.engine import analyze_repository
from output_trace.report import write_reports


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="output-trace",
        description="Generate output-oriented dataflow and algorithm documentation.",
    )
    parser.add_argument("repo_path", help="Repository to analyze")
    parser.add_argument("--output", "-o", help="Markdown output path")
    parser.add_argument("--max-files", type=int, default=5000, help="Maximum supported files to scan")
    parser.add_argument("--include-tests", action="store_true", help="Include test files")
    parser.add_argument("--no-json", action="store_true", help="Do not emit companion JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="[%(levelname)s] %(message)s")

    repo_root = Path(args.repo_path).resolve()
    if not repo_root.is_dir():
        raise SystemExit(f"Not a directory: {repo_root}")

    logging.info("Scanning %s", repo_root)
    facts, traces = analyze_repository(repo_root, max_files=args.max_files, include_tests=args.include_tests)
    logging.info(
        "Extracted sources=%d sinks=%d operations=%d traces=%d warnings=%d",
        len(facts.sources), len(facts.sinks), len(facts.operations), len(traces), len(facts.warnings),
    )

    output = Path(args.output).resolve() if args.output else repo_root.parent / f"{repo_root.name}-output-trace-greenfield.md"
    md_path, json_path = write_reports(traces, facts, repo_root.name, output, emit_json=not args.no_json)
    logging.info("Markdown report -> %s", md_path)
    if json_path:
        logging.info("JSON report     -> %s", json_path)

