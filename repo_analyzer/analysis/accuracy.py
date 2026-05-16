"""Accuracy techniques for LLM-based code analysis.

Documents and provides constants for the 7 accuracy-improvement techniques
used throughout the pipeline to maximise the quality of LLM-generated
documentation.
"""

from __future__ import annotations


import logging

logger = logging.getLogger("repo_analyzer.analysis.accuracy")

ACCURACY_TECHNIQUES: dict[str, str] = {
    "chain_of_thought": (
        "Chain-of-Thought (CoT) Prompting\n"
        "\n"
        "Break complex analysis into explicit reasoning steps. Instead of asking\n"
        "the LLM to produce a final answer directly, the prompt instructs it to:\n"
        "  1. List the symbols/functions found in the source.\n"
        "  2. Identify call relationships between them.\n"
        "  3. Infer the module's responsibility from those relationships.\n"
        "  4. Synthesize a summary.\n"
        "\n"
        "By making intermediate reasoning visible, CoT reduces hallucination and\n"
        "makes it possible to audit each step independently."
    ),
    "evidence_grounding": (
        "Evidence Grounding\n"
        "\n"
        "Every factual claim in the LLM output must be tied to specific evidence\n"
        "from the extracted data (AST symbols, file paths, line numbers). The\n"
        "prompt includes a structured context block with known symbols, call\n"
        "edges, and table references, and instructs the LLM to cite them.\n"
        "\n"
        "This prevents the model from inventing functions, classes, or data\n"
        "flows that do not exist in the actual codebase."
    ),
    "self_critique": (
        "Self-Critique / Self-Consistency\n"
        "\n"
        "After generating an initial analysis, the LLM is asked to review its\n"
        "own output and identify potential errors:\n"
        "  - Are there function names that don't appear in the symbol list?\n"
        "  - Are call edges bidirectional when they should be unidirectional?\n"
        "  - Are table references actually present in the codebase?\n"
        "\n"
        "The critique pass produces a corrected version, improving accuracy\n"
        "by 10-20% on cross-module flow analysis tasks."
    ),
    "confidence_scoring": (
        "Confidence Scoring\n"
        "\n"
        "Each section of the LLM output includes a self-assigned confidence\n"
        "level (high / medium / low). The scoring criteria are:\n"
        "  - HIGH:  Every claim backed by extracted symbols or call edges.\n"
        "  - MEDIUM: Most claims grounded, some inference involved.\n"
        "  - LOW:   Significant inference or speculation required.\n"
        "\n"
        "Downstream consumers (cross-validation, assembly) use these scores\n"
        "to weight or flag sections for human review."
    ),
    "iterative_refinement": (
        "Iterative Refinement\n"
        "\n"
        "For complex modules, the analysis is performed in multiple passes:\n"
        "  Pass 1: High-level module purpose and main entry points.\n"
        "  Pass 2: Internal function-level detail, guided by Pass 1 output.\n"
        "  Pass 3: Cross-module interactions, guided by Pass 1+2 output.\n"
        "\n"
        "Each pass uses the previous output as additional context, allowing\n"
        "the LLM to build a progressively more accurate understanding."
    ),
    "decomposition": (
        "Decomposition\n"
        "\n"
        "Large modules that exceed the context window are split into logical\n"
        "sub-components before analysis. Each sub-component is analyzed\n"
        "independently, then results are merged.\n"
        "\n"
        "The split strategy follows directory boundaries first, then falls\n"
        "back to file-count chunks. This prevents context overflow and\n"
        "ensures every file gets adequate analytical attention."
    ),
    "structured_output": (
        "Structured Output\n"
        "\n"
        "The LLM is instructed to produce output in a defined schema\n"
        "(JSON or markdown with fixed headings) rather than free-form text.\n"
        "This enables:\n"
        "  - Programmatic extraction and validation of individual fields.\n"
        "  - Consistent formatting across modules and runs.\n"
        "  - Automated cross-referencing between analysis sections.\n"
        "\n"
        "The schema includes: purpose, entry_points, internal_functions,\n"
        "external_dependencies, data_flows, and confidence."
    ),
}
"""Mapping of technique name to multi-line description."""


def get_technique(name: str) -> str:
    """Retrieve the description for a named accuracy technique.

    Parameters
    ----------
    name : str
        One of the keys in :data:`ACCURACY_TECHNIQUES`.

    Returns
    -------
    str
        Technique description.

    Raises
    ------
    KeyError
        If *name* is not a known technique.
    """
    if name not in ACCURACY_TECHNIQUES:
        raise KeyError(
            f"Unknown accuracy technique '{name}'. "
            f"Known: {', '.join(sorted(ACCURACY_TECHNIQUES))}"
        )
    return ACCURACY_TECHNIQUES[name]


def list_techniques() -> list[str]:
    """Return sorted list of available technique names."""
    return sorted(ACCURACY_TECHNIQUES.keys())


def build_techniques_prompt_section() -> str:
    """Build a formatted section describing all techniques for LLM prompts."""
    lines: list[str] = []
    lines.append("# Accuracy Techniques\n")
    lines.append(
        "Apply the following techniques to maximize analysis accuracy:\n"
    )
    for i, (name, desc) in enumerate(sorted(ACCURACY_TECHNIQUES.items()), 1):
        lines.append(f"## {i}. {name.replace('_', ' ').title()}\n")
        lines.append(desc)
        lines.append("")
    return "\n".join(lines)
