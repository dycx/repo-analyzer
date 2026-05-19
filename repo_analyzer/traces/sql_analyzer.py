"""SQL input/output and computation semantics extraction."""

from __future__ import annotations

import re

from repo_analyzer.traces.models import (
    AnalysisFacts,
    CodeLocation,
    InputSource,
    OutputSink,
    TransformStep,
)
from repo_analyzer.traces.patterns import safe_ref, summarize_expression, unique_preserve_order


_OUTPUT_RE = re.compile(
    r"\b("
    r"INSERT\s+(?:OVERWRITE\s+)?INTO|"
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?TABLE|"
    r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW|"
    r"MERGE\s+INTO"
    r")\s+[`\"']?([A-Za-z_][\w.:-]*)",
    re.IGNORECASE,
)
_INPUT_RE = re.compile(
    r"\b(?:FROM|JOIN|USING)\s+[`\"']?([A-Za-z_][\w.:-]*)",
    re.IGNORECASE,
)
_WHERE_RE = re.compile(r"\bWHERE\b(.+?)(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bHAVING\b|$)", re.IGNORECASE | re.DOTALL)
_GROUP_RE = re.compile(r"\bGROUP\s+BY\b(.+?)(?:\bORDER\s+BY\b|\bHAVING\b|$)", re.IGNORECASE | re.DOTALL)
_SELECT_RE = re.compile(r"\bSELECT\b(.+?)\bFROM\b", re.IGNORECASE | re.DOTALL)


def analyze_sql_text(
    sql_text: str,
    file_path: str,
    start_line: int,
    repo_path: str,
    ref_prefix: str = "sql",
    step_type: str = "sql",
) -> AnalysisFacts:
    """Analyze a SQL snippet and return trace facts."""
    facts = AnalysisFacts(repo_path=repo_path)
    cleaned = _clean_sql(sql_text)
    if not cleaned:
        return facts

    loc = CodeLocation(file=file_path, line=start_line, end_line=start_line + sql_text.count("\n"))
    input_tables = unique_preserve_order(_INPUT_RE.findall(cleaned))
    input_refs = [f"table:{table}" for table in input_tables]

    for table in input_tables:
        facts.inputs.append(InputSource(
            name=table,
            source_type="table",
            ref=f"table:{table}",
            location=loc,
            evidence=f"SQL references table {table}",
            format="sql",
        ))

    outputs = list(_OUTPUT_RE.finditer(cleaned))
    if outputs:
        for match in outputs:
            keyword = " ".join(match.group(1).upper().split())
            table = match.group(2)
            out_ref = f"table:{table}"
            facts.outputs.append(OutputSink(
                name=table,
                sink_type="table",
                input_refs=input_refs,
                location=loc,
                evidence=summarize_expression(cleaned),
                format="sql",
            ))
            facts.steps.append(_sql_step(
                file_path=file_path,
                loc=loc,
                ref_prefix=ref_prefix,
                output_ref=out_ref,
                input_refs=input_refs,
                expression=cleaned,
                step_type=step_type,
                keyword=keyword,
            ))
    elif input_refs:
        output_ref = safe_ref(ref_prefix, file_path, start_line, "query")
        facts.steps.append(_sql_step(
            file_path=file_path,
            loc=loc,
            ref_prefix=ref_prefix,
            output_ref=output_ref,
            input_refs=input_refs,
            expression=cleaned,
            step_type=step_type,
            keyword="SELECT",
        ))

    return facts


def analyze_sql_file(path: str, repo_root: str) -> AnalysisFacts:
    with open(path, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    import os

    rel = os.path.relpath(path, repo_root)
    return analyze_sql_text(text, rel, 1, repo_root, ref_prefix="sql_file")


def _sql_step(
    file_path: str,
    loc: CodeLocation,
    ref_prefix: str,
    output_ref: str,
    input_refs: list[str],
    expression: str,
    step_type: str,
    keyword: str,
) -> TransformStep:
    fields = _select_fields(expression)
    conditions = _where_conditions(expression)
    formulas = []
    group = _group_fields(expression)
    if group:
        formulas.append(f"GROUP BY {', '.join(group)}")
    if fields:
        formulas.extend(fields)
    notes = [f"SQL operation: {keyword}"]
    return TransformStep(
        step_id=safe_ref(ref_prefix, file_path, loc.line, keyword.lower().replace(" ", "_")),
        step_type=step_type,
        input_refs=input_refs,
        output_ref=output_ref,
        expression=summarize_expression(expression, limit=800),
        location=loc,
        evidence=summarize_expression(expression, limit=800),
        fields=fields,
        conditions=conditions,
        formulas=formulas,
        notes=notes,
    )


def _clean_sql(sql_text: str) -> str:
    text = re.sub(r"--.*?$", "", sql_text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return " ".join(text.strip().split())


def _select_fields(sql_text: str) -> list[str]:
    match = _SELECT_RE.search(sql_text)
    if not match:
        return []
    raw = match.group(1)
    fields = [_clean_field(part) for part in _split_csv(raw)]
    return [f for f in fields if f and f != "*"][:80]


def _where_conditions(sql_text: str) -> list[str]:
    match = _WHERE_RE.search(sql_text)
    if not match:
        return []
    return [" ".join(match.group(1).split())]


def _group_fields(sql_text: str) -> list[str]:
    match = _GROUP_RE.search(sql_text)
    if not match:
        return []
    return [_clean_field(part) for part in _split_csv(match.group(1)) if _clean_field(part)]


def _split_csv(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    quote = ""
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in {"'", '"', "`"}:
            quote = ch
            current.append(ch)
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return parts


def _clean_field(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().strip("`"))

