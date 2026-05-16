"""Phase 2.5: Cross-module end-to-end flow extraction."""

from __future__ import annotations


import json
import logging
from pathlib import Path

from repo_analyzer.config import Config
from repo_analyzer.llm.client import LLMClient
from repo_analyzer.render.mermaid import fix_mermaid_syntax

logger = logging.getLogger("repo_analyzer.phase25")


def _build_callback_summary(module_data: list[dict]) -> str:
    """Build a summary of callback/dispatch table information."""
    lines = []
    for mod in module_data:
        callbacks = mod.get("callbacks", {})
        tables = callbacks.get("dispatch_tables", [])
        registrations = callbacks.get("callback_registrations", [])
        indirect = callbacks.get("indirect_calls", [])

        if not tables and not registrations and not indirect:
            continue

        lines.append(f"\n### {mod['module']}")

        if tables:
            lines.append("**Dispatch Tables:**")
            for dt in tables:
                struct = dt.get("struct", "")
                fields = dt.get("fields", [])
                lines.append(f"- `{struct}` ({len(fields)} fields)")
                for f in fields[:10]:
                    lines.append(f"  - `{f['name']}` -> {f.get('type', '?')}")

        if registrations:
            lines.append("**Callback Registrations:**")
            for r in registrations[:20]:
                lines.append(f"  - `{r['var']}.{r['field']}` = `{r['func']}` @ {r['file']}:{r['line']}")

        if indirect:
            lines.append("**Indirect Calls:**")
            for ic in indirect[:15]:
                lines.append(f"  - `{ic['expression']}()` @ {ic['file']}:{ic['line']}")

    return "\n".join(lines) if lines else "(no callback info)"


def _extract_key_sections(analysis: str, max_chars: int = 2000) -> str:
    """Extract key sections from module analysis for context building."""
    lines = analysis.split("\n")
    sections = []
    current_section = []
    current_header = ""
    priority_headers = [
        "module responsibility", "public interface", "core flow", "core algorithm",
    ]

    for line in lines:
        if line.strip().startswith("#"):
            if current_section and current_header:
                is_priority = any(p in current_header.lower() for p in priority_headers)
                sections.append((current_header, "\n".join(current_section), is_priority))
            current_header = line.strip()
            current_section = [line]
        else:
            current_section.append(line)

    if current_section and current_header:
        is_priority = any(p in current_header.lower() for p in priority_headers)
        sections.append((current_header, "\n".join(current_section), is_priority))

    sections.sort(key=lambda x: (0 if x[2] else 1))

    result = []
    total = 0
    for _, content, _ in sections:
        if total + len(content) > max_chars:
            remaining = max_chars - total
            if remaining > 200:
                result.append(content[:remaining] + "...")
            break
        result.append(content)
        total += len(content)

    return "\n".join(result) if result else analysis[:max_chars]


def run_phase25(
    cfg: Config,
    llm: LLMClient,
    module_analyses: dict[str, str],
) -> str:
    """Run Phase 2.5: cross-module flow extraction."""
    from repo_analyzer.analysis.cross_validation import (
        build_ground_truth, build_structured_context, build_validation_summary,
        validate_cross_module_calls, build_structured_refinement_prompt,
    )
    from repo_analyzer.prompts.cross_flows import render_cross_flow_prompt

    logger.info("[Phase 2.5] Cross-module flow extraction ...")

    analysis_dir = cfg.analysis_dir
    struct_file = analysis_dir / "structure.json"
    call_graph_str = "(no call graph)"
    dispatch_str = "(no dispatch tables)"
    struct_data: dict = {}

    if struct_file.exists():
        with open(struct_file, encoding="utf-8") as f:
            struct_data = json.load(f)

        cg = struct_data.get("call_graph", [])
        if cg:
            cg_lines = []
            for edge in cg[:300]:
                if edge.get("type") == "indirect":
                    cg_lines.append(
                        f"  {edge['caller']} --> {edge['callee']} "
                        f"[indirect via {edge.get('field', '?')}] ({edge['file']}:{edge['line']})"
                    )
                else:
                    cg_lines.append(
                        f"  {edge['caller']} --> {edge['callee']}  ({edge['file']}:{edge['line']})"
                    )
            call_graph_str = "\n".join(cg_lines)

        callback_data = struct_data.get("callback_data", {})
        tables = callback_data.get("dispatch_tables", [])
        if tables:
            dt_lines = []
            for dt in tables:
                struct = dt.get("struct", "")
                fields = dt.get("fields", [])
                dt_lines.append(f"\n**{struct}** ({len(fields)} fields):")
                for f in fields:
                    dt_lines.append(f"  - {f['name']}: {f.get('type', '?')}")
            dispatch_str = "\n".join(dt_lines)

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

    callback_summary = _build_callback_summary(module_data)

    system_prompt, user_prompt = render_cross_flow_prompt(
        repo_name=cfg.repo_name,
        call_graph=call_graph_str,
        module_summaries=module_summaries,
        dispatch_tables=dispatch_str + "\n\n" + callback_summary,
        structured_context=structured_ctx,
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

        out_file = analysis_dir / "cross_flows.md"
        out_file.write_text(response_with_val, encoding="utf-8")
        logger.info("  Cross-module flows -> %s (%d chars)", out_file, len(response_with_val))
        return response_with_val
    except Exception as e:
        logger.error("  ERROR: %s", e)
        return f"[cross-flow extraction failed: {e}]"
