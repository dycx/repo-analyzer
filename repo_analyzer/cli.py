"""CLI entry point and pipeline orchestration."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from repo_analyzer.config import Config
from repo_analyzer.logging_config import setup_logging

logger = logging.getLogger("repo_analyzer")


def parse_args(argv: list[str] | None = None) -> Config:
    """Parse CLI arguments into a Config object."""
    parser = argparse.ArgumentParser(
        prog="repo-analyzer",
        description="Code Repository Reverse Engineering Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("repo_path", help="Path to the repository to analyze")
    parser.add_argument("--output", "-o", help="Output document path (default: <repo>-analysis.md)")
    parser.add_argument(
        "--phase", "-p", default="all",
        help="Phase range: 0, 0-1, 2-4, all (default: all)",
    )
    parser.add_argument(
        "--base-url", default="http://127.0.0.1:1234/v1",
        help="LLM API base URL (default: LM Studio local)",
    )
    parser.add_argument("--api-key", default=None, help="API key (or LLM_API_KEY env var)")
    parser.add_argument("--model", "-m", default="qwen3.5-35b-a3b", help="Model name")
    parser.add_argument("--max-files", type=int, default=5000, help="Max source files (Phase 1)")
    parser.add_argument("--timeout", "-t", type=float, default=300.0, help="LLM timeout seconds")
    parser.add_argument("--retry", type=int, default=3, help="Max retries on LLM failure")
    parser.add_argument("--context-size", type=int, default=4000, help="Source preview tokens per module")
    parser.add_argument("--skip-tests", action="store_true", help="Skip test files")
    parser.add_argument("--skip-synthesis", action="store_true", help="Skip Phase 3")
    parser.add_argument("--force", action="store_true", help="Force regeneration (ignore cache)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args(argv)

    if args.phase == "all":
        phase_start, phase_end = 0, 4
    elif "-" in args.phase:
        s, e = args.phase.split("-", 1)
        phase_start, phase_end = int(s), int(e)
    else:
        phase_start = phase_end = int(args.phase)

    api_key = args.api_key or os.environ.get("LLM_API_KEY")

    return Config(
        repo_path=Path(args.repo_path).resolve(),
        output=Path(args.output).resolve() if args.output else None,
        phase_start=phase_start,
        phase_end=phase_end,
        base_url=args.base_url,
        api_key=api_key,
        model=args.model,
        max_files=args.max_files,
        timeout=args.timeout,
        max_retries=args.retry,
        context_size=args.context_size,
        skip_tests=args.skip_tests,
        skip_synthesis=args.skip_synthesis,
        force=args.force,
        verbose=args.verbose,
    )


def run_pipeline(cfg: Config) -> None:
    """Execute the analysis pipeline based on config."""
    setup_logging(verbose=cfg.verbose)

    if not cfg.repo_path.is_dir():
        logger.error("Not a directory: %s", cfg.repo_path)
        sys.exit(1)

    analysis_dir = cfg.analysis_dir
    analysis_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("  repo-analyzer v2.0 — Code Reverse Engineering Pipeline")
    logger.info("=" * 60)
    logger.info("  Repository: %s", cfg.repo_path)
    logger.info("  Phases:     %d -> %d", cfg.phase_start, cfg.phase_end)
    logger.info("  LLM:        %s @ %s", cfg.model, cfg.base_url)

    t_start = time.time()

    # Phase 0: Reconnaissance
    metadata = {}
    if cfg.phase_in_range(0):
        from repo_analyzer.phases.recon import run_phase0
        metadata = run_phase0(cfg)
    elif (analysis_dir / "metadata.json").exists():
        import json
        with open(analysis_dir / "metadata.json", encoding="utf-8") as f:
            metadata = json.load(f)

    # Phase 1: Structure extraction
    if cfg.phase_in_range(1):
        from repo_analyzer.phases.structure import run_phase1
        run_phase1(cfg)

    # Phase 1.5: Output identification
    identified_outputs = []
    if cfg.phase_in_range(1) and cfg.phase_end >= 2:
        from repo_analyzer.phases.output_id import run_phase15
        identified_outputs = run_phase15(cfg)
    elif (analysis_dir / "outputs.json").exists():
        import json
        with open(analysis_dir / "outputs.json", encoding="utf-8") as f:
            identified_outputs = json.load(f)

    # Phases 2-4 need LLM
    if cfg.phase_end >= 2:
        from repo_analyzer.llm.client import LLMClient
        with LLMClient(
            base_url=cfg.base_url,
            model=cfg.model,
            api_key=cfg.api_key,
            timeout=cfg.timeout,
            max_retries=cfg.max_retries,
        ) as llm:
            reachable = llm.health_check()
            logger.info("  LLM health: %s", "OK" if reachable else "not reachable")

            module_analyses: dict[str, str] = {}

            # Phase 2: Module analysis
            if cfg.phase_in_range(2):
                from repo_analyzer.phases.module_analysis import run_phase2
                module_analyses = run_phase2(cfg, llm, identified_outputs)
            else:
                module_analyses = _load_existing_analyses(analysis_dir)

            # Phase 2.5: Cross-module flows
            cross_flows = ""
            if cfg.phase_in_range(2) and cfg.phase_end >= 3:
                from repo_analyzer.phases.cross_flows import run_phase25
                cross_flows = run_phase25(cfg, llm, module_analyses)
            elif (analysis_dir / "cross_flows.md").exists():
                cross_flows = (analysis_dir / "cross_flows.md").read_text(encoding="utf-8")

            # Phase 3: Synthesis
            architecture = ""
            if cfg.phase_in_range(3) and not cfg.skip_synthesis:
                from repo_analyzer.phases.synthesis import run_phase3
                architecture = run_phase3(cfg, llm, module_analyses)
            elif (analysis_dir / "synthesis.md").exists():
                architecture = (analysis_dir / "synthesis.md").read_text(encoding="utf-8")

            # Phase 4: Assembly
            if cfg.phase_in_range(4):
                from repo_analyzer.phases.assembly import run_phase4
                run_phase4(cfg, llm, module_analyses, architecture, cross_flows)

    elapsed = time.time() - t_start
    logger.info("=" * 60)
    logger.info("  Total time: %.0fs (%.1f min)", elapsed, elapsed / 60)
    logger.info("  Analysis data: %s", analysis_dir)
    logger.info("=" * 60)


def _load_existing_analyses(analysis_dir: Path) -> dict[str, str]:
    """Load previously generated module analyses from disk."""
    modules_out = analysis_dir / "module_analyses"
    result: dict[str, str] = {}
    if modules_out.exists():
        for f in sorted(modules_out.glob("*.md")):
            result[f.stem.replace("_", "/")] = f.read_text(encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "trace":
        setup_logging(verbose=False)
        from repo_analyzer.traces.pipeline import run_trace_command
        run_trace_command(argv[1:])
        return

    cfg = parse_args(argv)
    run_pipeline(cfg)
