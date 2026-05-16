"""Cross-validation: ground truth building and LLM output verification.

Builds a factual index from Phase 1 structured data, then validates
LLM-generated analysis against that ground truth using regex extraction
and name matching.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from repo_analyzer.analysis.fuzzy_match import fuzzy_match_name

logger = logging.getLogger("repo_analyzer.analysis.cross_validation")


@dataclass
class ValidationResult:
    """Outcome of cross-validating LLM output against ground truth."""

    verified_calls: list[tuple[str, str]] = field(default_factory=list)
    """(source_func, target_func) pairs confirmed by ground truth."""

    unverified_calls: list[tuple[str, str]] = field(default_factory=list)
    """(source_func, target_func) pairs NOT found in ground truth."""

    accuracy_score: float = 0.0
    """Ratio of verified to total extracted calls (0.0 - 1.0)."""


# ---------------------------------------------------------------------------
# Ground truth construction
# ---------------------------------------------------------------------------

def build_ground_truth(
    struct_data: dict,
    module_data: list[dict],
) -> dict:
    """Build a fact index from Phase 1 structured extraction.

    Parameters
    ----------
    struct_data : dict
        Per-file structured extraction results (symbols, call graph, etc.).
    module_data : list[dict]
        Module definitions with ``files`` and ``callbacks`` keys.

    Returns
    -------
    dict
        Index with keys: ``symbols``, ``call_edges_by_name``, ``tables``,
        ``udfs``, ``xml_loaders``.
    """
    symbols: set[str] = set()
    call_edges_by_name: dict[str, set[str]] = {}
    tables: set[str] = set()
    udfs: set[str] = set()
    xml_loaders: set[str] = set()

    # ---- Symbols and call edges from struct_data ----
    if isinstance(struct_data, dict):
        # structure.json has "files" (list of per-file dicts) and "call_graph" (list of edges)
        files_list = struct_data.get("files", [])
        call_graph = struct_data.get("call_graph", [])

        for file_info in files_list:
            if not isinstance(file_info, dict):
                continue

            for sym in file_info.get("symbols", []):
                if isinstance(sym, dict):
                    name = sym.get("name", "")
                    if name:
                        symbols.add(name)
                elif isinstance(sym, str):
                    symbols.add(sym)

            for edge in file_info.get("calls", []):
                if isinstance(edge, dict):
                    caller = edge.get("caller", "")
                    callee = edge.get("callee", "")
                    if caller and callee:
                        call_edges_by_name.setdefault(caller, set()).add(callee)
                        symbols.add(caller)
                        symbols.add(callee)

            for sql in file_info.get("sql_stmts", []):
                if isinstance(sql, str):
                    for m in re.finditer(
                        r"(?:FROM|INTO|UPDATE|JOIN|TABLE)\s+[`\"']?([A-Za-z_][\w.]*)",
                        sql, re.IGNORECASE,
                    ):
                        tables.add(m.group(1))

        for edge in call_graph:
            if isinstance(edge, dict):
                caller = edge.get("caller", "")
                callee = edge.get("callee", "")
                if caller and callee:
                    call_edges_by_name.setdefault(caller, set()).add(callee)
                    symbols.add(caller)
                    symbols.add(callee)

    # ---- Merge module-level callbacks ----
    for mod in module_data:
        if not isinstance(mod, dict):
            continue
        for cb in mod.get("callbacks", []):
            if isinstance(cb, str):
                symbols.add(cb)
            elif isinstance(cb, dict):
                name = cb.get("name", "")
                if name:
                    symbols.add(name)

    # Remove empty strings
    symbols.discard("")
    tables.discard("")
    udfs.discard("")
    xml_loaders.discard("")

    logger.debug(
        "Ground truth built: %d symbols, %d call edges, %d tables, %d UDFs, %d XML loaders",
        len(symbols), sum(len(v) for v in call_edges_by_name.values()),
        len(tables), len(udfs), len(xml_loaders),
    )

    return {
        "symbols": symbols,
        "call_edges_by_name": call_edges_by_name,
        "tables": tables,
        "udfs": udfs,
        "xml_loaders": xml_loaders,
    }


def build_structured_context(
    struct_data: dict,
    module_data: list[dict],
    ground_truth: dict,
) -> str:
    """Build a text summary of ground truth for inclusion in LLM prompts.

    Returns a concise, human-readable string that can be injected into a
    system or user prompt so the LLM has factual grounding.
    """
    parts: list[str] = []

    symbols: set[str] = ground_truth.get("symbols", set())
    call_edges: dict[str, set[str]] = ground_truth.get("call_edges_by_name", {})
    tables: set[str] = ground_truth.get("tables", set())
    udfs: set[str] = ground_truth.get("udfs", set())
    xml_loaders: set[str] = ground_truth.get("xml_loaders", set())

    # Symbols summary (limit to 200 for prompt size)
    sym_list = sorted(symbols)[:200]
    parts.append(f"## Known Symbols ({len(symbols)} total)")
    parts.append(", ".join(sym_list))
    if len(symbols) > 200:
        parts.append(f"... and {len(symbols) - 200} more")

    # Call edges summary (limit to 150)
    edge_count = 0
    if call_edges:
        parts.append(f"\n## Known Call Edges")
        for caller, callees in sorted(call_edges.items()):
            for callee in sorted(callees):
                if edge_count >= 150:
                    parts.append(f"... and more edges omitted")
                    break
                parts.append(f"  {caller} -> {callee}")
                edge_count += 1
            if edge_count >= 150:
                break

    # Tables
    if tables:
        tbl_list = sorted(tables)[:100]
        parts.append(f"\n## Known Tables ({len(tables)} total)")
        parts.append(", ".join(tbl_list))

    # UDFs
    if udfs:
        udf_list = sorted(udfs)[:50]
        parts.append(f"\n## Known UDFs ({len(udfs)} total)")
        parts.append(", ".join(udf_list))

    # XML loaders
    if xml_loaders:
        loader_list = sorted(xml_loaders)[:50]
        parts.append(f"\n## Known XML Loaders ({len(xml_loaders)} total)")
        parts.append(", ".join(loader_list))

    # Module summary
    if module_data:
        parts.append(f"\n## Modules ({len(module_data)} total)")
        for mod in module_data[:30]:
            name = mod.get("module", "unknown")
            n_files = len(mod.get("files", []))
            parts.append(f"  {name}: {n_files} files")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# LLM output validation
# ---------------------------------------------------------------------------

# Patterns to extract function/method calls from LLM text
_CALL_PATTERN = re.compile(
    r"\b([A-Za-z_][\w.]*)\s*(?:\(|->|::)\s*([A-Za-z_][\w.]*)"
)
# Patterns like "calls foo_bar()" or "invokes Baz.quux"
_INVOKE_PATTERN = re.compile(
    r"(?:calls?|invokes?|uses?|runs?|executes?)\s+"
    r"([A-Za-z_][\w.]*)(?:\s*\(|\s*::|\s*\.|\s*$)",
    re.IGNORECASE,
)
# Table references like "table orders" or "FROM users"
_TABLE_PATTERN = re.compile(
    r"(?:FROM|INTO|UPDATE|JOIN|TABLE|table)\s+[`\"']?([A-Za-z_][\w.]*)[`\"']?",
    re.IGNORECASE,
)


def _extract_calls_from_text(text: str) -> list[tuple[str, str]]:
    """Extract (source, target) function call pairs from LLM output text."""
    calls: list[tuple[str, str]] = []

    # Pattern 1: a -> b, a::b, a.b()
    for m in _CALL_PATTERN.finditer(text):
        src, tgt = m.group(1), m.group(2)
        calls.append((src, tgt))

    # Pattern 2: "calls foo_bar" style
    for m in _INVOKE_PATTERN.finditer(text):
        tgt = m.group(1)
        calls.append(("", tgt))

    return calls


def _extract_table_refs_from_text(text: str) -> list[str]:
    """Extract table name references from LLM output text."""
    return [m.group(1) for m in _TABLE_PATTERN.finditer(text)]


def _name_matches(name: str, ground_truth_set: set[str], threshold: float = 0.7) -> bool:
    """Check if *name* matches any entry in *ground_truth_set*."""
    if name in ground_truth_set:
        return True
    matches = fuzzy_match_name(name, ground_truth_set, threshold=threshold)
    return len(matches) > 0


def validate_cross_module_calls(
    llm_output: str,
    ground_truth: dict,
) -> ValidationResult:
    """Validate LLM-generated cross-module call analysis against ground truth.

    Extracts function call pairs and table references from *llm_output* using
    regex, then checks each against the ground truth index built by
    :func:`build_ground_truth`.

    Parameters
    ----------
    llm_output : str
        Free-form text produced by the LLM describing cross-module flows.
    ground_truth : dict
        Fact index from :func:`build_ground_truth`.

    Returns
    -------
    ValidationResult
        Verified vs unverified calls and overall accuracy.
    """
    symbols: set[str] = ground_truth.get("symbols", set())
    call_edges: dict[str, set[str]] = ground_truth.get("call_edges_by_name", {})
    tables: set[str] = ground_truth.get("tables", set())

    # Flatten all known callees for quick lookup
    all_callees: set[str] = set()
    for callees in call_edges.values():
        all_callees.update(callees)

    extracted_calls = _extract_calls_from_text(llm_output)
    extracted_tables = _extract_table_refs_from_text(llm_output)

    verified: list[tuple[str, str]] = []
    unverified: list[tuple[str, str]] = []

    for src, tgt in extracted_calls:
        # Check if the call edge exists or both symbols exist
        is_verified = False

        if src and tgt:
            # Direct edge check
            if src in call_edges and tgt in call_edges[src]:
                is_verified = True
            # Both symbols known
            elif _name_matches(src, symbols) and _name_matches(tgt, symbols):
                is_verified = True
            # Target is a known callee
            elif _name_matches(tgt, all_callees):
                is_verified = True
        elif tgt:
            # Only target extracted (from "calls X" pattern)
            if _name_matches(tgt, symbols) or _name_matches(tgt, all_callees):
                is_verified = True

        if is_verified:
            verified.append((src, tgt))
        else:
            unverified.append((src, tgt))

    # Validate table references
    for tbl in extracted_tables:
        if _name_matches(tbl, tables):
            # Count table verification as a verified "call" for scoring
            verified.append(("", f"TABLE:{tbl}"))
        else:
            unverified.append(("", f"TABLE:{tbl}"))

    total = len(verified) + len(unverified)
    accuracy = len(verified) / total if total > 0 else 0.0

    result = ValidationResult(
        verified_calls=verified,
        unverified_calls=unverified,
        accuracy_score=round(accuracy, 4),
    )

    logger.info(
        "Cross-validation: %d verified, %d unverified, accuracy=%.2f%%",
        len(verified), len(unverified), accuracy * 100,
    )

    return result


def build_validation_summary(result: ValidationResult) -> str:
    """Build a markdown summary of a :class:`ValidationResult`."""
    lines: list[str] = []
    lines.append("# Cross-Validation Report\n")

    total = len(result.verified_calls) + len(result.unverified_calls)
    lines.append(f"- **Total extracted references**: {total}")
    lines.append(f"- **Verified**: {len(result.verified_calls)}")
    lines.append(f"- **Unverified**: {len(result.unverified_calls)}")
    lines.append(f"- **Accuracy**: {result.accuracy_score:.1%}")
    lines.append("")

    if result.verified_calls:
        lines.append("## Verified Calls\n")
        lines.append("| Source | Target |")
        lines.append("|--------|--------|")
        for src, tgt in result.verified_calls[:50]:
            lines.append(f"| `{src}` | `{tgt}` |")
        if len(result.verified_calls) > 50:
            lines.append(f"| ... | *({len(result.verified_calls) - 50} more)* |")
        lines.append("")

    if result.unverified_calls:
        lines.append("## Unverified Calls\n")
        lines.append("| Source | Target |")
        lines.append("|--------|--------|")
        for src, tgt in result.unverified_calls[:50]:
            lines.append(f"| `{src}` | `{tgt}` |")
        if len(result.unverified_calls) > 50:
            lines.append(f"| ... | *({len(result.unverified_calls) - 50} more)* |")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Refinement prompt generation
# ---------------------------------------------------------------------------


def build_structured_refinement_prompt(
    original_output: str,
    validation_result: ValidationResult,
    ground_truth_context: str,
) -> str:
    """Build a structured refinement prompt with specific, actionable corrections.

    For each unverified call, provides the original reference and instructs
    the LLM to either correct it using verified names or mark it as inferred.
    """
    corrections: list[str] = []

    for i, (src, tgt) in enumerate(validation_result.unverified_calls[:15], 1):
        ref = f"{src} -> {tgt}" if src else tgt
        corrections.append(
            f"  {i}. `{ref}` -- not found in call graph or symbol table.\n"
            f"     Action: verify against source code, correct the name, "
            f"or mark as [inferred] with reasoning."
        )

    if not corrections:
        return original_output

    corrections_text = "\n".join(corrections)

    return f"""## Correction Required

Cross-validation found the following issues.  Please correct them:

{corrections_text}

## Rules
1. For calls not found in the verified data, mark them as [inferred] and explain your reasoning.
2. Keep all verified relationships unchanged.
3. If a function exists under a different name in the data, use the verified name.
4. Add a confidence summary at the end.

## Ground Truth Reference
{ground_truth_context}

## Original Analysis
{original_output}

## Please output the corrected, complete analysis
"""
