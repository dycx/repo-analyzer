"""Java/Scala Spark analyzer based on data-processing idioms."""

from __future__ import annotations

import re

from output_trace.ir import FactStore, Location, Operation, Sink, Source
from output_trace.sql import analyze_sql
from output_trace.text import compact, first_string, path_format, slug_ref, string_literals, unique


ASSIGN_RE = re.compile(
    r"^\s*(?:(?:val|var)\s+|(?:final\s+)?[A-Za-z_][\w<>\[\], ?]*\s+)([A-Za-z_]\w*)\s*=\s*(.+?);?\s*$"
)
SPARK_SQL_RE = re.compile(
    r"(?:spark|sqlContext|hiveContext)\.sql\s*\(\s*(?:\"\"\"(.*?)\"\"\"|\"(.*?)\"|'(.*?)')\s*\)",
    re.DOTALL,
)
WRITE_BASE_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\.\s*write\b")
SAVE_TABLE_RE = re.compile(r"\.(?:saveAsTable|insertInto)\s*\(\s*[\"']([^\"']+)[\"']")
METHOD_RE = re.compile(r"\.([A-Za-z_]\w*)\s*\(")
TRANSFORM_METHODS = {
    "filter", "where", "select", "selectExpr", "withColumn", "withColumnRenamed",
    "join", "groupBy", "agg", "drop", "dropDuplicates", "distinct", "orderBy",
    "sort", "union", "map", "flatMap",
}


def analyze_jvm(path: str, rel_path: str, repo_root: str) -> FactStore:
    with open(path, encoding="utf-8", errors="ignore") as handle:
        source = handle.read()
    facts = FactStore(repo_root=repo_root)
    _extract_spark_sql(source, rel_path, repo_root, facts)
    for statement, line in _statements(source):
        _analyze_statement(statement, line, rel_path, facts)
    return facts


def _extract_spark_sql(source: str, rel_path: str, repo_root: str, facts: FactStore) -> None:
    for match in SPARK_SQL_RE.finditer(source):
        sql = next((value for value in match.groups() if value), "")
        if sql:
            line = source[: match.start()].count("\n") + 1
            facts.extend(analyze_sql(sql, rel_path, line, repo_root))


def _analyze_statement(statement: str, line: int, rel_path: str, facts: FactStore) -> None:
    loc = Location(file=rel_path, line=line)
    match = ASSIGN_RE.match(statement)
    if match:
        target = match.group(1)
        target_ref = _ref(rel_path, target)
        expr = match.group(2)
        if _is_input(expr):
            name = first_string(expr, target)
            facts.sources.append(Source(
                id=target_ref,
                name=name,
                kind="table" if ".table" in expr or "spark.table" in expr else "file",
                format=path_format(expr),
                location=loc,
                evidence=compact(expr),
            ))
            return
        methods = [method for method in METHOD_RE.findall(expr) if method in TRANSFORM_METHODS]
        if methods:
            inputs = _input_refs(expr, target, rel_path)
            for index, method in enumerate(methods):
                fields, conditions, formulas, notes = _method_semantics(method, expr)
                facts.operations.append(Operation(
                    id=slug_ref("jvm_op", rel_path, line, f"{target}_{index}_{method}"),
                    kind=_method_kind(method),
                    output=target_ref,
                    inputs=inputs,
                    location=loc,
                    evidence=compact(expr),
                    expression=compact(expr),
                    fields=fields,
                    conditions=conditions,
                    formulas=formulas,
                    notes=notes,
                ))
            return

    if _is_output(statement):
        base = WRITE_BASE_RE.search(statement)
        table = SAVE_TABLE_RE.search(statement)
        name = table.group(1) if table else first_string(statement, "output")
        facts.sinks.append(Sink(
            id=slug_ref("jvm_sink", rel_path, line, name),
            name=name,
            kind="table" if table else "file",
            format=path_format(statement),
            depends_on=[_ref(rel_path, base.group(1))] if base else [],
            location=loc,
            evidence=compact(statement),
        ))


def _statements(source: str) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    current = ""
    start_line = 1
    for line_no, raw in enumerate(source.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("//"):
            continue
        if current:
            current += " " + stripped
        else:
            current = stripped
            start_line = line_no
        if _complete(current):
            result.append((current, start_line))
            current = ""
    if current:
        result.append((current, start_line))
    return result


def _complete(statement: str) -> bool:
    return statement.endswith(";") or statement.count("(") <= statement.count(")")


def _is_input(expr: str) -> bool:
    return any(marker in expr for marker in ("spark.read", ".read", ".load(", ".parquet(", ".csv(", ".json(", ".orc(", "spark.table(", ".table("))


def _is_output(statement: str) -> bool:
    return ".write" in statement or ".saveAsTable(" in statement or ".insertInto(" in statement


def _input_refs(expr: str, target: str, rel_path: str) -> list[str]:
    refs: list[str] = []
    base = re.match(r"\s*([A-Za-z_]\w*)\s*\.", expr)
    if base:
        refs.append(base.group(1))
    for pattern in (r"\.join\s*\(\s*([A-Za-z_]\w*)", r"\.union\s*\(\s*([A-Za-z_]\w*)"):
        refs.extend(re.findall(pattern, expr))
    return [_ref(rel_path, ref) for ref in unique([ref for ref in refs if ref != target and ref not in {"spark", "sqlContext", "hiveContext"}])]


def _method_kind(method: str) -> str:
    return {
        "filter": "filter",
        "where": "filter",
        "select": "select",
        "selectExpr": "select",
        "withColumn": "derive",
        "withColumnRenamed": "rename",
        "join": "join",
        "groupBy": "group",
        "agg": "aggregate",
        "dropDuplicates": "dedupe",
        "distinct": "dedupe",
    }.get(method, "transform")


def _method_semantics(method: str, expr: str) -> tuple[list[str], list[str], list[str], list[str]]:
    args = _call_args(expr, method) or expr
    strings = string_literals(args)
    fields: list[str] = []
    conditions: list[str] = []
    formulas: list[str] = []
    notes: list[str] = []
    if method in {"filter", "where"}:
        conditions.append(args)
    elif method in {"select", "selectExpr"}:
        fields.extend(strings)
    elif method == "withColumn":
        if strings:
            fields.append(strings[0])
        formulas.append(args)
    elif method == "join":
        fields.extend(strings)
        formulas.append(args)
    elif method == "groupBy":
        fields.extend(strings)
        notes.append("grouping keys define aggregation grain")
    elif method == "agg":
        fields.extend(strings)
        formulas.append(args)
    return unique(fields), unique(conditions), unique(formulas), unique(notes)


def _call_args(expr: str, method: str) -> str:
    marker = f".{method}("
    start = expr.find(marker)
    if start < 0:
        return ""
    index = start + len(marker)
    depth = 0
    quote = ""
    chars: list[str] = []
    for char in expr[index:]:
        if quote:
            chars.append(char)
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            chars.append(char)
        elif char == "(":
            depth += 1
            chars.append(char)
        elif char == ")":
            if depth == 0:
                break
            depth -= 1
            chars.append(char)
        else:
            chars.append(char)
    return compact("".join(chars), 500)


def _ref(rel_path: str, name: str) -> str:
    return f"jvm:{rel_path}:<scope>:{name}"

