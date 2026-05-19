"""SQL semantics extraction for output-driven traces."""

from __future__ import annotations

import re

from output_trace.ir import FactStore, Location, Operation, Sink, Source
from output_trace.text import compact, slug_ref, unique


OUTPUT_RE = re.compile(
    r"\b("
    r"INSERT\s+(?:OVERWRITE\s+)?INTO|"
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?TABLE|"
    r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW|"
    r"MERGE\s+INTO"
    r")\s+[`\"']?([A-Za-z_][\w.:-]*)",
    re.IGNORECASE,
)
INPUT_RE = re.compile(r"\b(?:FROM|JOIN|USING)\s+[`\"']?([A-Za-z_][\w.:-]*)", re.IGNORECASE)
SELECT_RE = re.compile(r"\bSELECT\b(.+?)\bFROM\b", re.IGNORECASE | re.DOTALL)
WHERE_RE = re.compile(
    r"\bWHERE\b(.+?)(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bHAVING\b|$)",
    re.IGNORECASE | re.DOTALL,
)
GROUP_RE = re.compile(r"\bGROUP\s+BY\b(.+?)(?:\bORDER\s+BY\b|\bHAVING\b|$)", re.IGNORECASE | re.DOTALL)


def analyze_sql(sql_text: str, file_path: str, line: int, repo_root: str, kind: str = "sql") -> FactStore:
    """Extract SQL sources, sinks and computation operations from one SQL text."""
    facts = FactStore(repo_root=repo_root)
    sql = normalize_sql(sql_text)
    if not sql:
        return facts

    loc = Location(file=file_path, line=line, end_line=line + sql_text.count("\n"))
    input_tables = unique(INPUT_RE.findall(sql))
    input_refs = [table_ref(name) for name in input_tables]
    for table in input_tables:
        facts.sources.append(Source(
            id=table_ref(table),
            name=table,
            kind="table",
            format="sql",
            location=loc,
            evidence=f"SQL reads table {table}",
        ))

    fields = select_fields(sql)
    conditions = where_conditions(sql)
    formulas = []
    groups = group_fields(sql)
    if groups:
        formulas.append("GROUP BY " + ", ".join(groups))
    formulas.extend(fields)

    outputs = list(OUTPUT_RE.finditer(sql))
    if outputs:
        for match in outputs:
            keyword = " ".join(match.group(1).upper().split())
            table = match.group(2)
            out_ref = table_ref(table)
            facts.sinks.append(Sink(
                id=slug_ref("sql_sink", file_path, loc.line, table),
                name=table,
                kind="table",
                format="sql",
                depends_on=[out_ref],
                location=loc,
                evidence=compact(sql, 800),
            ))
            facts.operations.append(Operation(
                id=slug_ref("sql_op", file_path, loc.line, table),
                kind=kind,
                output=out_ref,
                inputs=input_refs,
                location=loc,
                evidence=compact(sql, 800),
                expression=compact(sql, 800),
                fields=fields,
                conditions=conditions,
                formulas=formulas,
                notes=[f"SQL output operation: {keyword}"],
            ))
    elif input_refs:
        facts.operations.append(Operation(
            id=slug_ref("sql_query", file_path, loc.line, "query"),
            kind=kind,
            output=slug_ref("query", file_path, loc.line),
            inputs=input_refs,
            location=loc,
            evidence=compact(sql, 800),
            expression=compact(sql, 800),
            fields=fields,
            conditions=conditions,
            formulas=formulas,
            notes=["SQL query without direct output sink"],
        ))

    return facts


def analyze_sql_file(path: str, repo_root: str, rel_path: str) -> FactStore:
    with open(path, encoding="utf-8", errors="ignore") as handle:
        text = handle.read()
    return analyze_sql(text, rel_path, 1, repo_root)


def table_ref(name: str) -> str:
    return f"table:{name}"


def normalize_sql(sql_text: str) -> str:
    text = re.sub(r"--.*?$", "", sql_text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = text.replace("<![CDATA[", "").replace("]]>", "")
    return " ".join(text.strip().split())


def select_fields(sql: str) -> list[str]:
    match = SELECT_RE.search(sql)
    if not match:
        return []
    return [clean_field(part) for part in split_top_level_commas(match.group(1)) if clean_field(part) and clean_field(part) != "*"]


def where_conditions(sql: str) -> list[str]:
    match = WHERE_RE.search(sql)
    if not match:
        return []
    return [compact(match.group(1), 500)]


def group_fields(sql: str) -> list[str]:
    match = GROUP_RE.search(sql)
    if not match:
        return []
    return [clean_field(part) for part in split_top_level_commas(match.group(1)) if clean_field(part)]


def split_top_level_commas(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    quote = ""
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"', "`"}:
            quote = char
            current.append(char)
        elif char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current).strip())
    return parts


def clean_field(text: str) -> str:
    return compact(text.strip().strip("`"))

