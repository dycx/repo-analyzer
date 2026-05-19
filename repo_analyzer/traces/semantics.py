"""Computation-semantics extraction helpers."""

from __future__ import annotations

import re

from repo_analyzer.traces.models import CodeLocation, FieldLineage, TransformStep
from repo_analyzer.traces.patterns import identifiers, string_literals, unique_preserve_order


TRANSFORM_METHODS = {
    "agg", "aggregate", "alias", "assign", "cast", "coalesce", "distinct",
    "drop", "dropDuplicates", "explode", "filter", "flatMap", "groupBy",
    "groupby", "join", "map", "merge", "orderBy", "rename", "select",
    "selectExpr", "sort", "union", "where", "withColumn", "withColumnRenamed",
}

INPUT_METHODS = {
    "read_csv", "read_json", "read_parquet", "read_excel", "read_table",
    "read_sql", "load", "csv", "json", "parquet", "orc", "table", "text",
}

OUTPUT_METHODS = {
    "to_csv", "to_json", "to_parquet", "to_excel", "save", "saveAsTable",
    "insertInto", "parquet", "csv", "json", "orc", "text", "write_text",
    "write_bytes",
}


def method_to_step_type(method: str) -> str:
    mapping = {
        "where": "filter",
        "filter": "filter",
        "select": "select",
        "selectExpr": "select",
        "withColumn": "derive_field",
        "withColumnRenamed": "rename_field",
        "assign": "derive_field",
        "rename": "rename_field",
        "join": "join",
        "merge": "join",
        "groupBy": "groupby",
        "groupby": "groupby",
        "agg": "aggregate",
        "aggregate": "aggregate",
        "dropDuplicates": "deduplicate",
        "distinct": "deduplicate",
        "drop": "drop_field",
        "cast": "type_cast",
        "coalesce": "null_handling",
        "map": "map",
        "flatMap": "flat_map",
        "union": "union",
        "orderBy": "sort",
        "sort": "sort",
        "explode": "explode",
    }
    return mapping.get(method, "transform")


def extract_method_names(expr: str) -> list[str]:
    return re.findall(r"\.([A-Za-z_][A-Za-z0-9_]*)\s*\(", expr)


def infer_transform_semantics(method: str, expr: str) -> tuple[list[str], list[str], list[str], list[str]]:
    """Return (fields, conditions, formulas, notes) for a transform expression."""
    fields: list[str] = []
    conditions: list[str] = []
    formulas: list[str] = []
    notes: list[str] = []
    args = _extract_call_args(expr, method)
    strings = string_literals(args or expr)

    if method in {"select", "selectExpr"}:
        fields.extend(strings)
        if method == "selectExpr":
            formulas.extend(strings)
    elif method in {"filter", "where"}:
        conditions.append(args or expr)
    elif method in {"withColumn", "assign"}:
        if strings:
            fields.append(strings[0])
        formulas.append(args or expr)
    elif method == "withColumnRenamed":
        if len(strings) >= 2:
            fields.append(f"{strings[0]} -> {strings[1]}")
            formulas.append(f"rename {strings[0]} to {strings[1]}")
    elif method in {"groupBy", "groupby"}:
        fields.extend(strings)
        notes.append("分组键决定后续聚合粒度")
    elif method in {"agg", "aggregate"}:
        formulas.append(args or expr)
        fields.extend(strings)
        fields.extend(re.findall(r"\b([A-Za-z_]\w*)\s*=\s*\(", args or ""))
    elif method in {"join", "merge"}:
        formulas.append(args or expr)
        if strings:
            fields.extend(strings)
    elif method in {"drop", "dropDuplicates", "distinct"}:
        fields.extend(strings)
    elif method in {"cast", "coalesce"}:
        formulas.append(args or expr)

    return (
        unique_preserve_order(fields),
        unique_preserve_order(conditions),
        unique_preserve_order(formulas),
        unique_preserve_order(notes),
    )


def lineage_from_steps(steps: list[TransformStep]) -> list[FieldLineage]:
    """Build best-effort field lineage from transform semantics."""
    lineage: list[FieldLineage] = []
    for step in steps:
        evidence = [step.location]
        input_fields = _fields_from_refs_and_expr(step.input_refs, step.expression)
        conditions = list(step.conditions)

        if step.step_type == "derive_field" and step.fields:
            for field in step.fields:
                lineage.append(FieldLineage(
                    output_field=field,
                    input_fields=input_fields,
                    formula=step.formulas[0] if step.formulas else step.expression,
                    conditions=conditions,
                    evidence=evidence,
                ))
        elif step.step_type == "aggregate":
            aggregate_lineage = _aggregate_lineage(step)
            if aggregate_lineage:
                lineage.extend(aggregate_lineage)
                continue
            if step.fields:
                for field in step.fields:
                    lineage.append(FieldLineage(
                        output_field=field,
                        input_fields=input_fields,
                        formula=step.formulas[0] if step.formulas else step.expression,
                        conditions=conditions,
                        evidence=evidence,
                    ))
            else:
                lineage.append(FieldLineage(
                    output_field="聚合结果字段",
                    input_fields=input_fields,
                    formula=step.formulas[0] if step.formulas else step.expression,
                    conditions=conditions,
                    evidence=evidence,
                ))
        elif step.step_type == "select":
            for field in step.fields:
                lineage.append(FieldLineage(
                    output_field=field,
                    input_fields=[field],
                    formula=f"保留或选择字段 {field}",
                    conditions=conditions,
                    evidence=evidence,
                ))
        elif step.step_type == "rename_field":
            for field in step.fields:
                if "->" in field:
                    src, dst = [p.strip() for p in field.split("->", 1)]
                    lineage.append(FieldLineage(
                        output_field=dst,
                        input_fields=[src],
                        formula=f"字段重命名：{src} -> {dst}",
                        conditions=conditions,
                        evidence=evidence,
                    ))
        elif step.step_type in {"sql", "spark_sql_step"}:
            for formula in step.fields:
                output_field = _field_output_name(formula)
                lineage.append(FieldLineage(
                    output_field=output_field,
                    input_fields=_fields_from_refs_and_expr(step.input_refs, formula),
                    formula=formula,
                    conditions=conditions,
                    evidence=evidence,
                ))
    return lineage


def describe_step(step: TransformStep) -> str:
    """Human-readable Chinese description for a transform step."""
    loc = step.location.label()
    if step.step_type == "input":
        return f"读取输入数据，产生 `{step.output_ref}`。证据：{loc}"
    if step.step_type == "filter":
        cond = "；".join(step.conditions) if step.conditions else step.expression
        return f"过滤数据：{cond}。证据：{loc}"
    if step.step_type == "select":
        fields = "、".join(step.fields) if step.fields else "表达式中的字段"
        return f"选择输出字段：{fields}。证据：{loc}"
    if step.step_type == "derive_field":
        fields = "、".join(step.fields) if step.fields else step.output_ref
        formula = "；".join(step.formulas) if step.formulas else step.expression
        return f"计算派生字段 `{fields}`：{formula}。证据：{loc}"
    if step.step_type == "rename_field":
        fields = "、".join(step.fields) if step.fields else step.expression
        return f"重命名字段：{fields}。证据：{loc}"
    if step.step_type == "join":
        formula = "；".join(step.formulas) if step.formulas else step.expression
        return f"关联数据集：{formula}。证据：{loc}"
    if step.step_type == "groupby":
        fields = "、".join(step.fields) if step.fields else "表达式中的分组键"
        return f"按 {fields} 分组，为后续聚合确定粒度。证据：{loc}"
    if step.step_type == "aggregate":
        formula = "；".join(step.formulas) if step.formulas else step.expression
        return f"执行聚合计算：{formula}。证据：{loc}"
    if step.step_type == "sql":
        return f"执行 SQL 计算：{step.expression}。证据：{loc}"
    if step.step_type == "spark_sql_step":
        return f"执行 XML 配置中的 Spark SQL step：{step.expression}。证据：{loc}"
    return f"执行 `{step.step_type}` 转换：{step.expression}。证据：{loc}"


def _extract_call_args(expr: str, method: str) -> str:
    pattern = re.compile(rf"\.{re.escape(method)}\s*\((.*)\)", re.DOTALL)
    match = pattern.search(expr)
    if not match:
        pattern = re.compile(rf"\b{re.escape(method)}\s*\((.*)\)", re.DOTALL)
        match = pattern.search(expr)
    if not match:
        return ""
    args = match.group(1)
    depth = 0
    end = len(args)
    for idx, ch in enumerate(args):
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                end = idx
                break
            depth -= 1
    return " ".join(args[:end].split())


def _fields_from_refs_and_expr(input_refs: list[str], expr: str) -> list[str]:
    fields = [name for name in identifiers(expr) if name not in set(input_refs)]
    return unique_preserve_order(fields[:12])


def _field_output_name(formula: str) -> str:
    match = re.search(r"\bAS\s+[`\"]?([A-Za-z_][\w]*)", formula, re.IGNORECASE)
    if match:
        return match.group(1)
    parts = formula.split(".")
    if len(parts) > 1 and re.match(r"^[A-Za-z_]\w*$", parts[-1]):
        return parts[-1]
    return formula


def _aggregate_lineage(step: TransformStep) -> list[FieldLineage]:
    formula = "; ".join(step.formulas) if step.formulas else step.expression
    result: list[FieldLineage] = []
    evidence = [step.location]

    # Pandas named aggregation:
    # total_amount=("amount", "sum"), order_count=("order_id", "count")
    for out, src, func in re.findall(
        r"\b([A-Za-z_]\w*)\s*=\s*\(\s*[\"']([^\"']+)[\"']\s*,\s*[\"']([^\"']+)[\"']\s*\)",
        formula,
    ):
        result.append(FieldLineage(
            output_field=out,
            input_fields=[src],
            formula=f"{func}({src})",
            conditions=list(step.conditions),
            evidence=evidence,
        ))

    # Spark aggregation with alias:
    # sum("amount").alias("total_amount")
    for func, src, out in re.findall(
        r"\b([A-Za-z_]\w*)\s*\(\s*[\"']([^\"']+)[\"']\s*\)\s*\.alias\s*\(\s*[\"']([^\"']+)[\"']\s*\)",
        formula,
    ):
        result.append(FieldLineage(
            output_field=out,
            input_fields=[src],
            formula=f"{func}({src})",
            conditions=list(step.conditions),
            evidence=evidence,
        ))

    return result
