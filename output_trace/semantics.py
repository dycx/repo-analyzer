"""Human-readable operation semantics and field rules."""

from __future__ import annotations

import re

from output_trace.ir import FieldRule, Operation
from output_trace.text import identifiers, unique


def describe_operation(operation: Operation) -> str:
    loc = operation.location.label()
    if operation.kind == "filter":
        condition = "；".join(operation.conditions) or operation.expression
        return f"过滤数据：{condition}。证据：{loc}"
    if operation.kind == "select":
        fields = "、".join(operation.fields) or "表达式中的字段"
        return f"选择字段：{fields}。证据：{loc}"
    if operation.kind == "derive":
        field = "、".join(operation.fields) or operation.output
        formula = "；".join(operation.formulas) or operation.expression
        return f"计算派生字段 `{field}`：{formula}。证据：{loc}"
    if operation.kind == "join":
        formula = "；".join(operation.formulas) or operation.expression
        return f"关联数据：{formula}。证据：{loc}"
    if operation.kind == "group":
        fields = "、".join(operation.fields) or "表达式中的分组键"
        return f"按 {fields} 分组。证据：{loc}"
    if operation.kind == "aggregate":
        formula = "；".join(operation.formulas) or operation.expression
        return f"执行聚合计算：{formula}。证据：{loc}"
    if operation.kind == "sql":
        return f"执行 SQL 计算：{operation.expression}。证据：{loc}"
    if operation.kind == "xml_spark_sql":
        return f"执行 XML 配置中的 Spark SQL step：{operation.expression}。证据：{loc}"
    return f"执行 `{operation.kind}` 转换：{operation.expression or operation.evidence}。证据：{loc}"


def field_rules_from_operations(operations: list[Operation]) -> list[FieldRule]:
    rules: list[FieldRule] = []
    for operation in operations:
        if operation.kind in {"sql", "xml_spark_sql"}:
            rules.extend(_sql_field_rules(operation))
        elif operation.kind == "aggregate":
            rules.extend(_aggregate_field_rules(operation))
        elif operation.kind == "derive":
            for field in operation.fields:
                rules.append(FieldRule(
                    field=field,
                    formula=operation.formulas[0] if operation.formulas else operation.expression,
                    input_fields=_input_fields(operation.formulas[0] if operation.formulas else operation.expression),
                    conditions=list(operation.conditions),
                    evidence=[operation.location],
                ))
        elif operation.kind == "select":
            for field in operation.fields:
                rules.append(FieldRule(
                    field=field,
                    formula=f"保留字段 {field}",
                    input_fields=[field],
                    conditions=[],
                    evidence=[operation.location],
                ))
    return _dedupe_rules(rules)


def _sql_field_rules(operation: Operation) -> list[FieldRule]:
    result: list[FieldRule] = []
    for expression in operation.fields:
        result.append(FieldRule(
            field=_output_field_name(expression),
            formula=expression,
            input_fields=_input_fields(expression),
            conditions=list(operation.conditions),
            evidence=[operation.location],
        ))
    return result


def _aggregate_field_rules(operation: Operation) -> list[FieldRule]:
    formula = "; ".join(operation.formulas) or operation.expression
    result: list[FieldRule] = []
    for out_field, src_field, func in re.findall(
        r"\b([A-Za-z_]\w*)\s*=\s*\(\s*[\"']([^\"']+)[\"']\s*,\s*[\"']([^\"']+)[\"']\s*\)",
        formula,
    ):
        result.append(FieldRule(
            field=out_field,
            formula=f"{func}({src_field})",
            input_fields=[src_field],
            conditions=list(operation.conditions),
            evidence=[operation.location],
        ))
    for func, src_field, out_field in re.findall(
        r"\b([A-Za-z_]\w*)\s*\(\s*[\"']([^\"']+)[\"']\s*\)\s*\.alias\s*\(\s*[\"']([^\"']+)[\"']\s*\)",
        formula,
    ):
        result.append(FieldRule(
            field=out_field,
            formula=f"{func}({src_field})",
            input_fields=[src_field],
            conditions=list(operation.conditions),
            evidence=[operation.location],
        ))
    return result


def _output_field_name(expression: str) -> str:
    match = re.search(r"\bAS\s+[`\"]?([A-Za-z_]\w*)", expression, re.IGNORECASE)
    if match:
        return match.group(1)
    clean = expression.strip().strip("`")
    if re.match(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?$", clean):
        return clean.split(".")[-1]
    return clean


def _input_fields(expression: str) -> list[str]:
    skip = {
        "AS", "and", "or", "case", "when", "then", "else", "end",
        "sum", "count", "avg", "min", "max", "alias",
    }
    return unique([name for name in identifiers(expression) if name not in skip and not name.isupper()])[:12]


def _dedupe_rules(rules: list[FieldRule]) -> list[FieldRule]:
    seen: set[tuple[str, str]] = set()
    result: list[FieldRule] = []
    for rule in rules:
        key = (rule.field, rule.formula)
        if key in seen:
            continue
        seen.add(key)
        result.append(rule)
    return result

