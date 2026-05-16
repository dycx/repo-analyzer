"""Phase 2: Module-level LLM analysis with parallel execution."""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from repo_analyzer.config import Config
from repo_analyzer.llm.client import LLMClient
from repo_analyzer.render.mermaid import fix_mermaid_syntax

logger = logging.getLogger("repo_analyzer.phase2")


def _load_module_data(analysis_dir: Path) -> list[dict]:
    """Load per-module JSON files from Phase 1 output."""
    modules_dir = analysis_dir / "modules"
    if not modules_dir.exists():
        return []
    result = []
    for f in sorted(modules_dir.glob("*.json")):
        with open(f, encoding="utf-8") as fh:
            result.append(json.load(fh))
    return result


def _build_symbol_index(files: list[dict]) -> str:
    """Build a compact symbol index string for the LLM context."""
    lines = []
    for fa in files:
        if not fa.get("symbols"):
            continue
        lines.append(f"\n### {fa['path']} ({fa['language']})")
        for sym in fa["symbols"]:
            kind = sym["kind"]
            name = sym["name"]
            parent = sym.get("parent", "")
            qual = f"{parent}.{name}" if parent else name
            ret = sym.get("return_type", "")
            params = sym.get("params", [])
            vis = sym.get("visibility", "")
            sig = sym.get("signature", "")

            parts = []
            if vis:
                parts.append(vis)
            parts.append(kind)
            parts.append(qual)
            if ret:
                parts.append(f"-> {ret}")
            if params:
                param_strs = []
                for p in params:
                    ps = p.get("name", "")
                    pt = p.get("type", "")
                    if pt:
                        ps = f"{ps}: {pt}"
                    param_strs.append(ps)
                parts.append(f"({', '.join(param_strs)})")
            elif sig:
                parts.append(f"sig: {sig.split(chr(10))[0].strip()[:200]}")
            lines.append(f"  {' '.join(parts)}")
    return "\n".join(lines) if lines else "(no symbols extracted)"


def _build_source_preview(files: list[dict], repo_path: str, max_tokens: int = 4000) -> str:
    """Build source code preview respecting context limits."""
    max_chars = max_tokens * 4
    parts = []
    total = 0

    for fa in files:
        fpath = os.path.join(repo_path, fa["path"])
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError):
            continue

        header = f"\n{'='*60}\n### {fa['path']} ({fa['language']}, {len(content)} chars)\n{'='*60}\n"

        if len(content) > 8000:
            lines = content.split("\n")
            preview = lines[:30]
            preview.append(f"\n... ({len(lines) - 30} more lines) ...\n")
            for sym in fa.get("symbols", []):
                ln = sym.get("line", 0)
                if 30 < ln <= len(lines):
                    end = min(ln + 5, len(lines))
                    preview.append(f"--- {sym['kind']} {sym['name']} (line {ln}) ---")
                    preview.extend(lines[ln - 1:end])
            content = "\n".join(preview)

        block = header + content
        if total + len(block) > max_chars:
            remaining = max_chars - total
            if remaining > 500:
                parts.append(block[:remaining])
            break
        parts.append(block)
        total += len(block)

    return "\n".join(parts)


def _build_callback_info(mod: dict) -> str:
    """Build callback info string for a module."""
    callbacks = mod.get("callbacks", {})
    lines = []

    tables = callbacks.get("dispatch_tables", [])
    if tables:
        lines.append("Dispatch Tables:")
        for dt in tables:
            struct = dt.get("struct", "")
            fields = dt.get("fields", [])
            lines.append(f"  {struct}: {', '.join(f['name'] for f in fields)}")

    registrations = callbacks.get("callback_registrations", [])
    if registrations:
        lines.append("Callback Registrations:")
        for r in registrations[:20]:
            lines.append(f"  {r['var']}.{r['field']} = {r['func']}")

    indirect = callbacks.get("indirect_calls", [])
    if indirect:
        lines.append("Indirect Calls:")
        for ic in indirect[:15]:
            lines.append(f"  {ic['expression']}()")

    return "\n".join(lines) if lines else "(no callback info)"


def _build_output_points(mod: dict, outputs: list[dict]) -> str:
    """Build output points description for a module."""
    if not outputs:
        return "(no associated outputs)"
    mod_files = {f.get("path", "") for f in mod.get("files", [])}
    related = []
    for out in outputs:
        if out.get("file", "") in mod_files:
            icon = {"high": "[H]", "medium": "[M]", "low": "[L]"}.get(out.get("confidence", ""), "[?]")
            related.append(
                f"  - {icon} `{out['name']}` ({out['output_type']}) @ "
                f"{out['file']}:{out['line']} -- {out.get('evidence', '')}"
            )
    return "\n".join(related) if related else "(no associated outputs)"


def _analyze_single_module(
    i: int,
    total: int,
    mod: dict,
    repo_path: str,
    llm: LLMClient,
    cfg: Config,
    identified_outputs: list[dict],
    modules_out: Path,
) -> tuple[str, str] | None:
    """Analyze a single module. Returns (module_name, analysis) or None."""
    from repo_analyzer.prompts.module import render_module_prompt

    mod_name = mod["module"]
    files = mod["files"]
    safe_name = mod_name.replace("/", "_").replace("\\", "_").replace(".", "_")
    out_file = modules_out / f"{safe_name}.md"

    if out_file.exists() and not cfg.force:
        existing = out_file.read_text(encoding="utf-8")
        if len(existing) > 200:
            logger.info("  [%d/%d] %s -- cached (%d chars)", i, total, mod_name, len(existing))
            return (mod_name, existing)

    if not any(fa.get("symbols") for fa in files):
        logger.info("  [%d/%d] %s -- skipped (no symbols)", i, total, mod_name)
        return None

    symbol_index = _build_symbol_index(files)
    source_code = _build_source_preview(files, repo_path, max_tokens=cfg.context_size)
    callback_info = _build_callback_info(mod)
    output_points = _build_output_points(mod, identified_outputs)

    system_prompt, user_prompt = render_module_prompt(
        repo_name=cfg.repo_name,
        module_path=mod_name,
        file_count=len(files),
        symbol_index=symbol_index,
        source_code=source_code,
        callback_info=callback_info,
        output_points=output_points,
    )

    try:
        start = time.time()
        response = llm.chat(system=system_prompt, user=user_prompt)
        response = fix_mermaid_syntax(response)
        elapsed = time.time() - start
        logger.info("  [%d/%d] %s -- done (%.1fs, %d chars)", i, total, mod_name, elapsed, len(response))
        out_file.write_text(response, encoding="utf-8")
        return (mod_name, response)
    except Exception as e:
        logger.error("  [%d/%d] %s -- ERROR: %s", i, total, mod_name, e)
        error_file = modules_out / f"{safe_name}.error.md"
        error_file.write_text(f"[Analysis failed: {e}]\n", encoding="utf-8")
        return None


def run_phase2(
    cfg: Config,
    llm: LLMClient,
    identified_outputs: list[dict] | None = None,
) -> dict[str, str]:
    """Run Phase 2: module-level LLM analysis."""
    from repo_analyzer.analysis.module_split import auto_split_modules

    logger.info("[Phase 2] Module-level analysis (using %s) ...", llm.model)

    modules = _load_module_data(cfg.analysis_dir)
    if not modules:
        logger.error("No module data found. Run Phase 1 first.")
        return {}

    original_count = len(modules)
    modules = auto_split_modules(modules, max_files=10)
    if len(modules) != original_count:
        logger.info("  Auto-split: %d -> %d modules", original_count, len(modules))
        modules_out_dir = cfg.analysis_dir / "module_analyses"
        if modules_out_dir.exists():
            for old in modules_out_dir.glob("*.md"):
                old.unlink()
            logger.info("  Cleaned stale module files")

    logger.info("  Found %d modules to analyze", len(modules))

    modules_out = cfg.analysis_dir / "module_analyses"
    modules_out.mkdir(exist_ok=True)

    results: dict[str, str] = {}

    max_workers = min(4, len(modules))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _analyze_single_module,
                i + 1, len(modules), mod, str(cfg.repo_path),
                llm, cfg, identified_outputs or [], modules_out,
            ): mod["module"]
            for i, mod in enumerate(modules)
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                mod_name, analysis = result
                results[mod_name] = analysis

    logger.info("  Phase 2 complete: %d modules analyzed", len(results))
    return results
