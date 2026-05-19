"""Report generation for greenfield output traces."""

from __future__ import annotations

import json
from pathlib import Path

from output_trace.ir import FactStore, OutputTrace, to_jsonable
from output_trace.semantics import describe_operation


def write_reports(traces: list[OutputTrace], facts: FactStore, repo_name: str, output: Path, emit_json: bool = True) -> tuple[Path, Path | None]:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(traces, facts, repo_name), encoding="utf-8")
    json_path = None
    if emit_json:
        json_path = output.with_suffix(".json")
        payload = {
            "repo": repo_name,
            "summary": {
                "sources": len(facts.sources),
                "sinks": len(facts.sinks),
                "operations": len(facts.operations),
                "traces": len(traces),
                "warnings": len(facts.warnings),
            },
            "traces": to_jsonable(traces),
            "warnings": list(facts.warnings),
        }
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return output, json_path


def render_markdown(traces: list[OutputTrace], facts: FactStore, repo_name: str) -> str:
    lines: list[str] = []
    lines.append(f"# {repo_name} 输出追踪与算法说明\n")
    lines.append("> 绿地实现：按输出物组织，说明输入数据经过哪些计算、过滤、关联、聚合后生成输出。")
    lines.append("")
    lines.append("## 输出清单\n")
    if not traces:
        lines.append("未识别到输出点。")
    else:
        lines.append("| # | 输出 | 类型 | 位置 | 置信度 | 输入数 | 步骤数 |")
        lines.append("|---|------|------|------|--------|--------|--------|")
        for index, trace in enumerate(traces, start=1):
            sink = trace.sink
            lines.append(
                f"| {index} | `{_cell(sink.name)}` | {sink.kind} | `{sink.location.label()}` | "
                f"{trace.confidence} | {len(trace.sources)} | {len(trace.operations)} |"
            )
    for index, trace in enumerate(traces, start=1):
        _render_trace(lines, index, trace)
    if facts.warnings:
        lines.append("\n---\n")
        lines.append("## 分析警告\n")
        for warning in facts.warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines) + "\n"


def _render_trace(lines: list[str], index: int, trace: OutputTrace) -> None:
    sink = trace.sink
    lines.append("\n---\n")
    lines.append(f"## {index}. 输出：`{sink.name}`\n")
    lines.append(f"- **输出类型:** {sink.kind}")
    if sink.format:
        lines.append(f"- **输出格式:** {sink.format}")
    lines.append(f"- **生成位置:** `{sink.location.label()}`")
    lines.append(f"- **证据:** `{_cell(sink.evidence)}`")
    lines.append(f"- **追踪置信度:** {trace.confidence}")
    lines.append("")

    lines.append("### 输入来源\n")
    if trace.sources:
        lines.append("| 输入 | 类型 | 格式 | 位置 | 证据 |")
        lines.append("|------|------|------|------|------|")
        for source in trace.sources:
            lines.append(
                f"| `{_cell(source.name)}` | {source.kind} | {source.format or '-'} | "
                f"`{source.location.label()}` | `{_cell(source.evidence)}` |"
            )
    else:
        lines.append("未能静态确认输入来源。")
    lines.append("")

    lines.append("### 输入到输出流程\n")
    if trace.operations:
        for op_index, operation in enumerate(trace.operations, start=1):
            lines.append(f"{op_index}. {describe_operation(operation)}")
    else:
        lines.append("未能静态还原中间转换步骤。")
    lines.append("")

    lines.append("### 字段级计算规则\n")
    if trace.field_rules:
        lines.append("| 输出字段 | 来源字段 | 计算方式 | 条件 | 证据 |")
        lines.append("|----------|----------|----------|------|------|")
        for rule in trace.field_rules:
            source_fields = ", ".join(f"`{_cell(field)}`" for field in rule.input_fields) or "-"
            conditions = "<br>".join(_cell(condition) for condition in rule.conditions) or "-"
            evidence = ", ".join(f"`{loc.label()}`" for loc in rule.evidence)
            lines.append(
                f"| `{_cell(rule.field)}` | {source_fields} | `{_cell(rule.formula)}` | {conditions} | {evidence} |"
            )
    else:
        lines.append("未识别到字段级计算规则。")
    lines.append("")

    lines.append("### 关键过滤条件\n")
    conditions = []
    for operation in trace.operations:
        conditions.extend(operation.conditions)
    if conditions:
        for condition in dict.fromkeys(conditions):
            lines.append(f"- `{_cell(condition)}`")
    else:
        lines.append("未识别到显式过滤条件。")
    lines.append("")

    lines.append("### 伪代码\n")
    lines.append("```text")
    for source in trace.sources:
        lines.append(f"read {source.name} -> {source.id}")
    for operation in trace.operations:
        inputs = ", ".join(operation.inputs) or "unknown"
        lines.append(f"{operation.output} = {operation.kind}({inputs})")
    deps = ", ".join(sink.depends_on) or "unknown"
    lines.append(f"write {deps} -> {sink.name}")
    lines.append("```")
    lines.append("")

    lines.append("### 未确认项\n")
    if trace.unresolved_refs:
        for ref in trace.unresolved_refs:
            lines.append(f"- `{_cell(ref)}` 的上游来源未能静态确认。")
    else:
        lines.append("未发现未确认上游引用。")


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")

