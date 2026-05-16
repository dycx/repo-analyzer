"""Phase 1.5: Output Identification.

Identifies system outputs using a 5-layer strategy:
  1. Regex pattern matching
  2. AST structural analysis (placeholder)
  3. SQL output analysis
  4. Data flow tracing (simplified)
  5. LLM-assisted (placeholder)
"""

from __future__ import annotations


import json
import logging
import os
import re
from pathlib import Path

from repo_analyzer.config import Config

logger = logging.getLogger("repo_analyzer.output_id")

# ---------------------------------------------------------------------------
# Regex patterns: (compiled_regex, output_type, default_confidence)
# ---------------------------------------------------------------------------
_REGEX_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # SQL
    (re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE), "sql", "high"),
    (re.compile(r"\bCREATE\s+TABLE\b", re.IGNORECASE), "sql", "high"),
    (re.compile(r"\bMERGE\s+INTO\b", re.IGNORECASE), "sql", "high"),
    (re.compile(r"\bUPDATE\s+\w+\s+SET\b", re.IGNORECASE), "sql", "medium"),
    (re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE), "sql", "medium"),
    # Spark / big-data writes
    (re.compile(r"\.write\.parquet\b"), "spark_write", "high"),
    (re.compile(r"\.saveAsTable\b"), "spark_write", "high"),
    (re.compile(r"\.insertInto\b"), "spark_write", "high"),
    (re.compile(r"\.write\.mode\b"), "spark_write", "medium"),
    (
        re.compile(
            r'\.format\s*\(\s*["\'](?:parquet|csv|json|orc|avro)["\']\s*\)',
            re.IGNORECASE,
        ),
        "spark_write",
        "medium",
    ),
    # File I/O
    (re.compile(r"""open\s*\([^)]*["'][wa]b?["']"""), "file_write", "medium"),
    (re.compile(r"\.to_csv\s*\("), "file_write", "high"),
    (re.compile(r"\.to_json\s*\("), "file_write", "high"),
    (re.compile(r"\.to_parquet\s*\("), "file_write", "high"),
    (re.compile(r"\.savefig\s*\("), "file_write", "high"),
    (re.compile(r"\.save\s*\("), "file_write", "low"),
    # API endpoints
    (re.compile(r"@GetMapping"), "api_endpoint", "high"),
    (re.compile(r"@PostMapping"), "api_endpoint", "high"),
    (re.compile(r"@PutMapping"), "api_endpoint", "high"),
    (re.compile(r"@DeleteMapping"), "api_endpoint", "high"),
    (re.compile(r"@RequestMapping"), "api_endpoint", "medium"),
    (re.compile(r"@app\.route\s*\("), "api_endpoint", "high"),
    (re.compile(r"@router\."), "api_endpoint", "high"),
    # Message queues / event emitters
    (re.compile(r"\.send\s*\("), "message", "low"),
    (re.compile(r"\.publish\s*\("), "message", "medium"),
    (re.compile(r"\.emit\s*\("), "message", "low"),
    # Console / stdout
    (re.compile(r"\bprint\s*\("), "console", "low"),
    (re.compile(r"\bprintln\s*\("), "console", "low"),
    (re.compile(r"\bSystem\.out\b"), "console", "low"),
    (re.compile(r"\bconsole\.log\s*\("), "console", "low"),
]


# ---------------------------------------------------------------------------
# Layer 1 -- Regex pattern matching
# ---------------------------------------------------------------------------


def identify_outputs_regex(source_text: str, filepath: str) -> list[dict]:
    """Identify outputs by scanning *source_text* with regex patterns."""
    results: list[dict] = []
    lines = source_text.splitlines()

    for line_idx, line in enumerate(lines, start=1):
        for pattern, output_type, default_confidence in _REGEX_PATTERNS:
            match = pattern.search(line)
            if match is None:
                continue
            name = _extract_output_name(line, match, output_type)
            context_lines: list[str] = []
            if line_idx >= 2:
                context_lines.append(lines[line_idx - 2])
            context_lines.append(line)
            if line_idx < len(lines):
                context_lines.append(lines[line_idx])
            context = "\n".join(context_lines[:3])

            results.append(
                {
                    "name": name,
                    "output_type": output_type,
                    "file": filepath,
                    "line": line_idx,
                    "confidence": default_confidence,
                    "detection_layer": "regex",
                    "evidence": match.group(0),
                    "context": context,
                }
            )
    return results


def _extract_output_name(line: str, match: re.Match, output_type: str) -> str:
    """Derive a human-readable name from the matched line."""
    matched_text = match.group(0)

    if output_type == "sql":
        table_match = re.search(
            r"(?:INSERT\s+INTO|CREATE\s+TABLE|MERGE\s+INTO|UPDATE|DELETE\s+FROM)"
            r"\s+[`\"']?(\w+)",
            line,
            re.IGNORECASE,
        )
        if table_match:
            return table_match.group(1)

    if output_type == "api_endpoint":
        path_match = re.search(r'["\']([^"\']+)["\']', line)
        if path_match:
            return f"{matched_text} {path_match.group(1)}"

    if output_type == "file_write":
        fname_match = re.search(r'["\']([^"\']+\.\w+)["\']', line)
        if fname_match:
            return fname_match.group(1)

    return matched_text.strip()[:80]


# ---------------------------------------------------------------------------
# Layer 2 -- AST structural analysis (placeholder)
# ---------------------------------------------------------------------------


def identify_outputs_ast(struct_data: dict) -> list[dict]:
    """Analyze function names and annotations for output hints.

    Lightweight structural pass -- inspects function/method names in
    *struct_data* for patterns suggesting output behaviour (e.g.
    ``save_*``, ``write_*``, ``export_*``, ``send_*``).
    """
    results: list[dict] = []
    _OUTPUT_NAME_RE = re.compile(
        r"(?:save|write|export|send|publish|emit|output|flush|dump|"
        r"persist|store|commit|push|upload)",
        re.IGNORECASE,
    )

    for file_path, file_info in (struct_data.get("files") or {}).items():
        for func in file_info.get("functions", []):
            func_name = func.get("name", "")
            if _OUTPUT_NAME_RE.search(func_name):
                results.append(
                    {
                        "name": func_name,
                        "output_type": "function_output",
                        "file": file_path,
                        "line": func.get("line", 0),
                        "confidence": "medium",
                        "detection_layer": "ast",
                        "evidence": f"Function name '{func_name}' suggests output",
                        "context": "",
                    }
                )

        for cls in file_info.get("classes", []):
            for method in cls.get("methods", []):
                annotations = method.get("annotations", [])
                for ann in annotations:
                    if any(
                        kw in ann
                        for kw in ("Mapping", "Controller", "RestController", "Route")
                    ):
                        results.append(
                            {
                                "name": method.get("name", ""),
                                "output_type": "api_endpoint",
                                "file": file_path,
                                "line": method.get("line", 0),
                                "confidence": "medium",
                                "detection_layer": "ast",
                                "evidence": f"Annotation: {ann}",
                                "context": "",
                            }
                        )
    return results


# ---------------------------------------------------------------------------
# Layer 3 -- SQL output analysis
# ---------------------------------------------------------------------------


def analyze_sql_outputs(sql_stmts: list[dict]) -> list[dict]:
    """Find INSERT / CREATE TABLE / MERGE statements in extracted SQL."""
    results: list[dict] = []
    _SQL_OUTPUT_RE = re.compile(
        r"\b(INSERT\s+INTO|CREATE\s+(?:OR\s+REPLACE\s+)?TABLE|MERGE\s+INTO)"
        r"\s+[`\"']?(\w+)",
        re.IGNORECASE,
    )

    for stmt in sql_stmts:
        sql_text = stmt.get("sql", "")
        source_file = stmt.get("file", "<unknown>")
        base_line = stmt.get("line", 0)

        for m in _SQL_OUTPUT_RE.finditer(sql_text):
            keyword = m.group(1).upper()
            table_name = m.group(2)
            if "INSERT" in keyword:
                stmt_type = "sql_insert"
            elif "CREATE" in keyword:
                stmt_type = "sql_create_table"
            elif "MERGE" in keyword:
                stmt_type = "sql_merge"
            else:
                stmt_type = "sql"

            results.append(
                {
                    "name": table_name,
                    "output_type": stmt_type,
                    "file": source_file,
                    "line": base_line,
                    "confidence": "high",
                    "detection_layer": "sql",
                    "evidence": f"{keyword} {table_name}",
                    "context": sql_text[:200],
                }
            )
    return results


# ---------------------------------------------------------------------------
# Layer 4 -- Data flow tracing (simplified)
# ---------------------------------------------------------------------------


def trace_data_flow(struct_data: dict) -> list[dict]:
    """Follow call chains from output functions backward.

    Simplified version: looks for functions that *call* known output
    functions and reports the caller as an indirect output.
    """
    results: list[dict] = []
    _KNOWN_OUTPUT_CALLS = {
        "save",
        "write",
        "publish",
        "emit",
        "send",
        "dump",
        "to_csv",
        "to_json",
        "to_parquet",
        "savefig",
        "insertInto",
        "saveAsTable",
    }

    files = struct_data.get("files") or {}

    for file_path, file_info in files.items():
        for func in file_info.get("functions", []):
            calls = func.get("calls", [])
            for callee in calls:
                callee_base = callee.split(".")[-1] if "." in callee else callee
                if callee_base in _KNOWN_OUTPUT_CALLS:
                    results.append(
                        {
                            "name": func.get("name", ""),
                            "output_type": "data_flow",
                            "file": file_path,
                            "line": func.get("line", 0),
                            "confidence": "medium",
                            "detection_layer": "data_flow",
                            "evidence": f"calls {callee}",
                            "context": "",
                        }
                    )
    return results


# ---------------------------------------------------------------------------
# Layer 5 -- LLM-assisted (placeholder)
# ---------------------------------------------------------------------------


def identify_outputs_llm() -> list[dict]:
    """Placeholder for LLM-assisted output identification."""
    return []


# ---------------------------------------------------------------------------
# Library detection
# ---------------------------------------------------------------------------


def detect_library_outputs(repo_path: str, struct_data: dict) -> list[dict]:
    """Detect whether the repository exposes a library (headers, build targets)."""
    results: list[dict] = []
    root = Path(repo_path)

    # Public header directories
    _HEADER_DIRS = ("include", "inc", "api", "public")
    for hdr_dir in _HEADER_DIRS:
        hdr_path = root / hdr_dir
        if hdr_path.is_dir():
            header_files = list(hdr_path.rglob("*.h")) + list(hdr_path.rglob("*.hpp"))
            if header_files:
                results.append(
                    {
                        "name": f"library_headers ({hdr_dir}/)",
                        "output_type": "library_header",
                        "file": str(hdr_path),
                        "line": 0,
                        "confidence": "high",
                        "detection_layer": "library_detection",
                        "evidence": f"{len(header_files)} header files in {hdr_dir}/",
                        "context": ", ".join(
                            str(h.relative_to(root)) for h in header_files[:10]
                        ),
                    }
                )

    # Build files for library targets
    _BUILD_PATTERNS: list[tuple[str, re.Pattern]] = [
        ("CMakeLists.txt", re.compile(r"\badd_library\s*\(", re.IGNORECASE)),
        ("Makefile", re.compile(r"\bLIBRARY\b")),
        ("Cargo.toml", re.compile(r'crate-type\s*=.*"lib"')),
        ("build.gradle", re.compile(r"\blibrary\b")),
        ("build.gradle.kts", re.compile(r"\blibrary\b")),
        ("pyproject.toml", re.compile(r"\[project\]")),
        ("package.json", re.compile(r'"main"\s*:')),
    ]

    for build_file, pattern in _BUILD_PATTERNS:
        build_path = root / build_file
        if build_path.is_file():
            try:
                text = build_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if pattern.search(text):
                results.append(
                    {
                        "name": f"library_target ({build_file})",
                        "output_type": "library_target",
                        "file": str(build_path),
                        "line": 0,
                        "confidence": "high",
                        "detection_layer": "library_detection",
                        "evidence": (
                            f"Pattern '{pattern.pattern}' matched in {build_file}"
                        ),
                        "context": "",
                    }
                )

    return results


# ---------------------------------------------------------------------------
# IO flow document generation
# ---------------------------------------------------------------------------


def generate_io_flow_document(
    outputs: list[dict],
    module_analyses: dict[str, str],
    repo_name: str,
) -> str:
    """Generate a markdown IO-flow document from identified outputs."""
    lines: list[str] = []
    lines.append(f"# IO Flow Document -- {repo_name}\n")
    lines.append(f"**Total outputs identified:** {len(outputs)}\n")

    # Summary table
    lines.append("## Output Summary\n")
    lines.append(
        "| # | Name | Type | File | Line | Confidence | Input Count |"
    )
    lines.append(
        "|---|------|------|------|------|------------|-------------|"
    )
    for idx, out in enumerate(outputs, start=1):
        name = out.get("name", "")
        otype = out.get("output_type", "")
        ofile = out.get("file", "")
        oline = out.get("line", "")
        conf = out.get("confidence", "")
        input_count = out.get("input_count", "N/A")
        lines.append(
            f"| {idx} | {name} | {otype} | {ofile} | {oline} | {conf} | {input_count} |"
        )

    lines.append("")

    # Per-output details
    lines.append("## Output Details\n")
    for idx, out in enumerate(outputs, start=1):
        lines.append(f"### {idx}. {out.get('name', '')}\n")
        lines.append(f"- **Type:** {out.get('output_type', '')}")
        lines.append(f"- **File:** `{out.get('file', '')}`")
        lines.append(f"- **Line:** {out.get('line', '')}")
        lines.append(f"- **Confidence:** {out.get('confidence', '')}")
        lines.append(f"- **Detection layer:** {out.get('detection_layer', '')}")
        lines.append(f"- **Evidence:** `{out.get('evidence', '')}`")
        context = out.get("context", "")
        if context:
            lines.append(f"- **Context:**\n```\n{context}\n```")
        lines.append("")

    # Statistics
    lines.append("## Statistics\n")
    type_counts: dict[str, int] = {}
    layer_counts: dict[str, int] = {}
    conf_counts: dict[str, int] = {}
    for out in outputs:
        otype = out.get("output_type", "unknown")
        type_counts[otype] = type_counts.get(otype, 0) + 1
        layer = out.get("detection_layer", "unknown")
        layer_counts[layer] = layer_counts.get(layer, 0) + 1
        conf = out.get("confidence", "unknown")
        conf_counts[conf] = conf_counts.get(conf, 0) + 1

    lines.append("### By Output Type\n")
    for otype, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- **{otype}:** {cnt}")

    lines.append("\n### By Detection Layer\n")
    for layer, cnt in sorted(layer_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- **{layer}:** {cnt}")

    lines.append("\n### By Confidence\n")
    for conf in ("high", "medium", "low"):
        if conf in conf_counts:
            lines.append(f"- **{conf}:** {conf_counts[conf]}")

    # Module analyses references
    if module_analyses:
        lines.append("\n## Module Analyses\n")
        for module_path, summary in module_analyses.items():
            lines.append(f"### {module_path}\n")
            lines.append(summary)
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _deduplicate_outputs(outputs: list[dict]) -> list[dict]:
    """Remove exact duplicates (same file + line + evidence)."""
    seen: set[tuple[str, int, str]] = set()
    unique: list[dict] = []
    for out in outputs:
        key = (out.get("file", ""), out.get("line", 0), out.get("evidence", ""))
        if key not in seen:
            seen.add(key)
            unique.append(out)
    return unique


def _load_source_text(filepath: str) -> str:
    """Safely read a source file, returning empty string on failure."""
    try:
        return Path(filepath).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_phase15(cfg: Config) -> list[dict]:
    """Run Phase 1.5 -- Output Identification.

    Loads structure and module data from *cfg.analysis_dir*, runs all five
    detection layers, deduplicates results, and saves to ``outputs.json``.
    """
    analysis_dir = cfg.analysis_dir
    repo_path = str(cfg.repo_path)
    repo_name = cfg.repo_name

    logger.info("[Phase 1.5] Output identification for %s ...", repo_name)

    # Load structure.json
    structure_file = analysis_dir / "structure.json"
    struct_data: dict = {}
    if structure_file.is_file():
        try:
            with open(structure_file, encoding="utf-8") as f:
                struct_data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load structure.json: %s", exc)
    else:
        logger.warning(
            "structure.json not found at %s -- AST/flow layers will be limited.",
            structure_file,
        )

    # Load module analyses (if available)
    module_analyses: dict[str, str] = {}
    modules_dir = analysis_dir / "modules"
    if modules_dir.is_dir():
        for mod_file in sorted(modules_dir.glob("*.md")):
            try:
                module_analyses[mod_file.stem] = mod_file.read_text(
                    encoding="utf-8", errors="ignore"
                )
            except OSError:
                pass

    # Collect SQL statements from structure data
    sql_stmts: list[dict] = struct_data.get("sql_statements", [])

    # Layer 1: Regex over source files
    all_outputs: list[dict] = []
    files_map = struct_data.get("files") or {}
    if files_map:
        for filepath in files_map:
            full_path = os.path.join(repo_path, filepath)
            source_text = _load_source_text(full_path)
            if source_text:
                all_outputs.extend(identify_outputs_regex(source_text, filepath))
    else:
        logger.info("No file list in structure.json; walking repo for regex scan.")
        _SOURCE_EXTS = {
            ".py", ".java", ".scala", ".sql", ".js", ".ts",
            ".go", ".rs", ".rb", ".c", ".cpp", ".cc", ".h", ".hpp",
        }
        _SKIP = {
            ".git", "node_modules", "__pycache__", ".venv", "venv",
            "build", "dist", "target", ".code-analysis",
        }
        for dirpath, dirnames, filenames in os.walk(repo_path):
            dirnames[:] = [d for d in dirnames if d not in _SKIP]
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in _SOURCE_EXTS:
                    continue
                fpath = os.path.join(dirpath, fname)
                rel = os.path.relpath(fpath, repo_path)
                source_text = _load_source_text(fpath)
                if source_text:
                    all_outputs.extend(identify_outputs_regex(source_text, rel))

    logger.info("  Layer 1 (regex): %d candidates", len(all_outputs))

    # Layer 2: AST
    ast_outputs = identify_outputs_ast(struct_data)
    all_outputs.extend(ast_outputs)
    logger.info("  Layer 2 (ast): %d candidates", len(ast_outputs))

    # Layer 3: SQL
    sql_outputs = analyze_sql_outputs(sql_stmts)
    all_outputs.extend(sql_outputs)
    logger.info("  Layer 3 (sql): %d candidates", len(sql_outputs))

    # Layer 4: Data flow
    flow_outputs = trace_data_flow(struct_data)
    all_outputs.extend(flow_outputs)
    logger.info("  Layer 4 (data_flow): %d candidates", len(flow_outputs))

    # Layer 5: LLM (placeholder)
    llm_outputs = identify_outputs_llm()
    all_outputs.extend(llm_outputs)
    logger.info("  Layer 5 (llm): %d candidates", len(llm_outputs))

    # Deduplicate
    all_outputs = _deduplicate_outputs(all_outputs)

    # If nothing found, try library detection
    if not all_outputs:
        logger.info("  No outputs found; trying library detection ...")
        lib_outputs = detect_library_outputs(repo_path, struct_data)
        all_outputs.extend(lib_outputs)
        logger.info("  Library detection: %d candidates", len(lib_outputs))

    # Generate IO flow document
    io_doc = generate_io_flow_document(all_outputs, module_analyses, repo_name)
    io_doc_path = analysis_dir / "io_flow.md"
    try:
        with open(io_doc_path, "w", encoding="utf-8") as f:
            f.write(io_doc)
        logger.info("  IO flow document -> %s", io_doc_path)
    except OSError as exc:
        logger.warning("Could not write io_flow.md: %s", exc)

    # Save outputs.json
    out_file = analysis_dir / "outputs.json"
    try:
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(all_outputs, f, indent=2, ensure_ascii=False)
        logger.info("  -> Saved %d outputs to %s", len(all_outputs), out_file)
    except OSError as exc:
        logger.error("Could not write outputs.json: %s", exc)

    return all_outputs
