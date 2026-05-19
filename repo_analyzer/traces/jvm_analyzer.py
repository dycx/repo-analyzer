"""Java/Scala Spark and SQL trace extraction using domain rules."""

from __future__ import annotations

import os
import re

from repo_analyzer.traces.models import (
    AnalysisFacts,
    CodeLocation,
    InputSource,
    OutputSink,
    TransformStep,
)
from repo_analyzer.traces.patterns import (
    classify_path_format,
    first_string_literal,
    safe_ref,
    summarize_expression,
    unique_preserve_order,
)
from repo_analyzer.traces.semantics import (
    TRANSFORM_METHODS,
    extract_method_names,
    infer_transform_semantics,
    method_to_step_type,
)
from repo_analyzer.traces.sql_analyzer import analyze_sql_text


_ASSIGN_RE = re.compile(
    r"^\s*(?:(?:val|var)\s+|(?:final\s+)?[A-Za-z_][\w<>\[\], ?]*\s+)([A-Za-z_]\w*)\s*=\s*(.+?);?\s*$"
)
_WRITE_BASE_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\.\s*write\b")
_SAVE_TABLE_RE = re.compile(r"\.(?:saveAsTable|insertInto)\s*\(\s*[\"']([^\"']+)[\"']")
_SPARK_SQL_RE = re.compile(
    r"(?:spark|sqlContext|hiveContext)\.sql\s*\(\s*(?:\"\"\"(.*?)\"\"\"|\"(.*?)\"|'(.*?)')\s*\)",
    re.DOTALL,
)


def analyze_jvm_file(path: str, repo_root: str) -> AnalysisFacts:
    with open(path, encoding="utf-8", errors="ignore") as f:
        source = f.read()
    rel = os.path.relpath(path, repo_root)
    facts = AnalysisFacts(repo_path=repo_root)

    _extract_spark_sql_calls(source, rel, repo_root, facts)

    pending = ""
    start_line = 1
    for line_no, raw_line in enumerate(source.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        if pending:
            pending += " " + stripped
        else:
            pending = stripped
            start_line = line_no
        if _is_statement_complete(pending):
            _analyze_statement(pending, rel, start_line, repo_root, facts)
            pending = ""

    if pending:
        _analyze_statement(pending, rel, start_line, repo_root, facts)

    return facts


def _analyze_statement(stmt: str, file_path: str, line: int, repo_root: str, facts: AnalysisFacts) -> None:
    loc = CodeLocation(file=file_path, line=line)
    assign = _ASSIGN_RE.match(stmt)
    if assign:
        target = assign.group(1)
        target_ref = _ref(file_path, target)
        expr = assign.group(2)
        if _looks_like_input(expr):
            name = first_string_literal(expr, fallback=target)
            source_type = "table" if ".table" in expr or "saveAsTable" in expr else "file"
            facts.inputs.append(InputSource(
                name=name,
                source_type=source_type,
                ref=target_ref,
                location=loc,
                evidence=summarize_expression(expr),
                format=classify_path_format(expr),
            ))
            return
        methods = [m for m in extract_method_names(expr) if m in TRANSFORM_METHODS]
        if methods:
            input_refs = _input_refs(expr, target, file_path)
            for index, method in enumerate(methods):
                fields, conditions, formulas, notes = infer_transform_semantics(method, expr)
                facts.steps.append(TransformStep(
                    step_id=safe_ref("jvm_step", file_path, line, f"{target}_{index}_{method}"),
                    step_type=method_to_step_type(method),
                    input_refs=input_refs,
                    output_ref=target_ref,
                    expression=summarize_expression(expr),
                    location=loc,
                    evidence=summarize_expression(expr),
                    fields=fields,
                    conditions=conditions,
                    formulas=formulas,
                    notes=notes,
                ))
            return

    if _looks_like_output(stmt):
        base_match = _WRITE_BASE_RE.search(stmt)
        input_refs = [_ref(file_path, base_match.group(1))] if base_match else _input_refs(stmt, "", file_path)
        table_match = _SAVE_TABLE_RE.search(stmt)
        name = table_match.group(1) if table_match else first_string_literal(stmt, fallback="output")
        sink_type = "table" if table_match or "insertInto" in stmt or "saveAsTable" in stmt else "file"
        facts.outputs.append(OutputSink(
            name=name,
            sink_type=sink_type,
            input_refs=unique_preserve_order(input_refs),
            location=loc,
            evidence=summarize_expression(stmt),
            format=classify_path_format(stmt),
        ))


def _extract_spark_sql_calls(source: str, file_path: str, repo_root: str, facts: AnalysisFacts) -> None:
    for match in _SPARK_SQL_RE.finditer(source):
        sql = next((group for group in match.groups() if group), "")
        if not sql:
            continue
        line = source[: match.start()].count("\n") + 1
        facts.merge(analyze_sql_text(
            sql,
            file_path,
            line,
            repo_root,
            ref_prefix="jvm_sql",
            step_type="sql",
        ))


def _looks_like_input(expr: str) -> bool:
    markers = (
        "spark.read", "sqlContext.read", "read.", ".read", ".load(",
        ".parquet(", ".csv(", ".json(", ".orc(", ".table(", "spark.table(",
    )
    return any(marker in expr for marker in markers)


def _looks_like_output(stmt: str) -> bool:
    return ".write" in stmt or ".saveAsTable(" in stmt or ".insertInto(" in stmt


def _input_refs(expr: str, target: str, file_path: str = "") -> list[str]:
    refs: list[str] = []
    base = re.match(r"\s*([A-Za-z_]\w*)\s*\.", expr)
    if base:
        refs.append(base.group(1))
    for pattern in (
        r"\.join\s*\(\s*([A-Za-z_]\w*)",
        r"\.merge\s*\(\s*([A-Za-z_]\w*)",
        r"\.union\s*\(\s*([A-Za-z_]\w*)",
    ):
        refs.extend(re.findall(pattern, expr))
    refs = [
        ref for ref in refs
        if ref != target and ref not in {"spark", "sqlContext", "hiveContext"}
    ]
    refs = unique_preserve_order(refs)
    return [_ref(file_path, ref) for ref in refs] if file_path else refs


def _ref(file_path: str, name: str) -> str:
    return f"jvm:{file_path}:<scope>:{name}"


def _is_statement_complete(stmt: str) -> bool:
    if stmt.endswith(";"):
        return True
    open_parens = stmt.count("(") - stmt.count(")")
    open_braces = stmt.count("{") - stmt.count("}")
    return open_parens <= 0 and open_braces <= 0
