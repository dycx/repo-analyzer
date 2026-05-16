"""Phase 3: Architecture synthesis with self-critique and iterative refinement."""

from __future__ import annotations


import json
import logging
from pathlib import Path

from repo_analyzer.config import Config
from repo_analyzer.llm.client import LLMClient
from repo_analyzer.render.mermaid import fix_mermaid_syntax

logger = logging.getLogger("repo_analyzer.phase3")


def run_phase3(
    cfg: Config,
    llm: LLMClient,
    module_analyses: dict[str, str],
) -> str:
    """Run Phase 3: cross-module architecture synthesis."""
    from repo_analyzer.analysis.cross_validation import (
        build_ground_truth, build_structured_context, build_validation_summary,
        validate_cross_module_calls, build_structured_refinement_prompt,
    )
    from repo_analyzer.phases.cross_flows import _extract_key_sections
    from repo_analyzer.prompts.synthesis import render_synthesis_prompt

    logger.info("[Phase 3] Cross-module synthesis ...")

    analysis_dir = cfg.analysis_dir
    struct_file = analysis_dir / "structure.json"
    call_graph_str = "(no call graph)"
    import_graph_str = "(no import graph)"
    struct_data: dict = {}

    if struct_file.exists():
        with open(struct_file, encoding="utf-8") as f:
            struct_data = json.load(f)

        cg = struct_data.get("call_graph", [])
        if cg:
            cg_lines = []
            for edge in cg[:200]:
                cg_lines.append(f"  {edge['caller']} -> {edge['callee']}  ({edge['file']}:{edge['line']})")
            call_graph_str = "\n".join(cg_lines)

        ig = struct_data.get("import_graph", [])
        if ig:
            ig_lines = []
            for imp in ig[:200]:
                module = imp.get("module", "")
                ig_lines.append(
                    f"  {imp['file']} imports {imp['source']}" + (f" from {module}" if module else "")
                )
            import_graph_str = "\n".join(ig_lines)

    modules_dir = analysis_dir / "modules"
    module_data: list[dict] = []
    if modules_dir.exists():
        for f in sorted(modules_dir.glob("*.json")):
            with open(f, encoding="utf-8") as fh:
                module_data.append(json.load(fh))

    ground_truth = build_ground_truth(struct_data, module_data)
    structured_ctx = build_structured_context(struct_data, module_data, ground_truth)

    summaries = []
    for mod_name, analysis in module_analyses.items():
        summary = _extract_key_sections(analysis, max_chars=2000)
        summaries.append(f"### {mod_name}\n{summary}")
    module_summaries = "\n\n".join(summaries)

    system_prompt, user_prompt = render_synthesis_prompt(
        repo_name=cfg.repo_name,
        module_summaries=module_summaries,
        call_graph=call_graph_str,
        import_graph=import_graph_str,
    )

    user_prompt += (
        "\n\n## Phase 1 Structured Validation Data (Ground Truth)\n"
        + structured_ctx
        + "\n\nThe following data comes from Phase 1's precise structural analysis "
        "(tree-sitter extracted) and represents **verified facts**. "
        "Call relationships and module dependencies in your analysis must be consistent with this data. "
        "If a relationship does not exist in the data below, mark it as 'inferred' rather than confirmed.\n"
    )

    try:
        response = llm.chat(system=system_prompt, user=user_prompt, max_tokens=8192)
        response = fix_mermaid_syntax(response)

        validation = validate_cross_module_calls(response, ground_truth)
        val_summary = build_validation_summary(validation)
        verified = len(validation.verified_calls)
        total = verified + len(validation.unverified_calls)
        logger.info(
            "  Cross-validation: %.0f%% accuracy (%d/%d verified)",
            validation.accuracy_score * 100, verified, total,
        )

        REFINE_THRESHOLD = 0.70
        MAX_REFINEMENTS = 1
        for ri in range(MAX_REFINEMENTS):
            if validation.accuracy_score >= REFINE_THRESHOLD or not validation.unverified_calls:
                break

            logger.info(
                "  [Refine %d] Accuracy %.0f%% < %.0f%%, correcting %d errors ...",
                ri + 1, validation.accuracy_score * 100, REFINE_THRESHOLD * 100,
                len(validation.unverified_calls[:10]),
            )

            refine_prompt = build_structured_refinement_prompt(
                response, validation, structured_ctx,
            )
            try:
                response = llm.chat(system=system_prompt, user=refine_prompt, max_tokens=8192)
                response = fix_mermaid_syntax(response)
                validation = validate_cross_module_calls(response, ground_truth)
                val_summary = build_validation_summary(validation)
                verified = len(validation.verified_calls)
                total = verified + len(validation.unverified_calls)
                logger.info(
                    "  [Refine %d] -> %.0f%% accuracy (%d/%d)",
                    ri + 1, validation.accuracy_score * 100, verified, total,
                )
            except Exception as e:
                logger.error("  [Refine %d] ERROR: %s", ri + 1, e)
                break

        if validation.unverified_calls:
            logger.warning("  %d unverified calls remaining", len(validation.unverified_calls))

        response_with_val = response + "\n\n---\n\n" + val_summary

        out_file = analysis_dir / "synthesis.md"
        out_file.write_text(response_with_val, encoding="utf-8")
        logger.info("  Synthesis complete (%d chars) -> %s", len(response_with_val), out_file)
        return response_with_val
    except Exception as e:
        logger.error("  ERROR: %s", e)
        return f"[synthesis failed: {e}]"
