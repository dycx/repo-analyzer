"""Markdown and JSON report generation for output traces."""

from __future__ import annotations

import json
from pathlib import Path

from repo_analyzer.traces.models import AnalysisFacts, OutputTrace, dataclass_to_dict
from repo_analyzer.traces.semantics import describe_step


def write_trace_outputs(
    traces: list[OutputTrace],
    facts: AnalysisFacts,
    output_path: Path,
    repo_name: str,
    emit_json: bool = True,
) -> tuple[Path, Path | None]:
    """Write Markdown report and optional JSON trace data."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown_report(traces, facts, repo_name)
    output_path.write_text(markdown, encoding="utf-8")

    json_path: Path | None = None
    if emit_json:
        json_path = output_path.with_suffix(".json")
        payload = {
            "repo": repo_name,
            "summary": {
                "inputs": len(facts.inputs),
                "outputs": len(facts.outputs),
                "steps": len(facts.steps),
                "traces": len(traces),
                "warnings": len(facts.warnings),
            },
            "traces": dataclass_to_dict(traces),
            "warnings": facts.warnings,
        }
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return output_path, json_path


def render_markdown_report(
    traces: list[OutputTrace],
    facts: AnalysisFacts,
    repo_name: str,
) -> str:
    lines: list[str] = []
    lines.append(f"# {repo_name} 输出数据流与算法说明\n")
    lines.append("> 本报告按输出物组织，重点说明输入数据如何经过过滤、转换、关联、聚合和字段计算后形成输出。")
    lines.append("")
    lines.append("## 输出清单\n")
    if traces:
        lines.append("| # | 输出 | 类型 | 位置 | 置信度 | 输入数 | 步骤数 |")
        lines.append("|---|------|------|------|--------|--------|--------|")
        for idx, trace in enumerate(traces, start=1):
            out = trace.output
            lines.append(
                f"| {idx} | `{_escape_cell(out.name)}` | {out.sink_type} | "
                f"`{out.location.label()}` | {trace.confidence} | "
                f"{len(trace.inputs)} | {len(trace.steps)} |"
            )
    else:
        lines.append("未识别到输出点。")
    lines.append("")

    for idx, trace in enumerate(traces, start=1):
        _render_trace(lines, idx, trace)

    if facts.warnings:
        lines.append("\n---\n")
        lines.append("## 分析警告\n")
        for warning in facts.warnings:
            lines.append(f"- {warning}")

    return "\n".join(lines) + "\n"


def _render_trace(lines: list[str], idx: int, trace: OutputTrace) -> None:
    out = trace.output
    lines.append("\n---\n")
    lines.append(f"## {idx}. 输出：`{out.name}`\n")
    lines.append(f"- **输出类型:** {out.sink_type}")
    if out.format:
        lines.append(f"- **输出格式:** {out.format}")
    lines.append(f"- **生成位置:** `{out.location.label()}`")
    lines.append(f"- **证据:** `{out.evidence}`")
    lines.append(f"- **追踪置信度:** {trace.confidence}")
    lines.append("")

    lines.append("### 输入来源\n")
    if trace.inputs:
        lines.append("| 输入 | 类型 | 格式 | 位置 | 证据 |")
        lines.append("|------|------|------|------|------|")
        for source in trace.inputs:
            lines.append(
                f"| `{_escape_cell(source.name)}` | {source.source_type} | "
                f"{source.format or '-'} | `{source.location.label()}` | "
                f"`{_escape_cell(source.evidence)}` |"
            )
    else:
        lines.append("未能确定明确输入来源。")
    lines.append("")

    lines.append("### 输入到输出流程\n")
    if trace.steps:
        for step_idx, step in enumerate(trace.steps, start=1):
            lines.append(f"{step_idx}. {describe_step(step)}")
    else:
        lines.append("未能还原中间转换步骤；请查看未确认项和输出位置附近代码。")
    lines.append("")

    lines.append("### 字段级计算规则\n")
    if trace.field_lineage:
        lines.append("| 输出字段 | 来源字段 | 计算方式 | 条件 | 证据 |")
        lines.append("|----------|----------|----------|------|------|")
        for item in trace.field_lineage:
            source_fields = ", ".join(f"`{field}`" for field in item.input_fields[:12]) or "-"
            conditions = "<br>".join(_escape_cell(c) for c in item.conditions) or "-"
            evidence = ", ".join(f"`{loc.label()}`" for loc in item.evidence)
            lines.append(
                f"| `{_escape_cell(item.output_field)}` | {source_fields} | "
                f"`{_escape_cell(item.formula)}` | {conditions} | {evidence} |"
            )
    else:
        lines.append("未提取到字段级 lineage。通常原因是代码使用了动态表达式、UDF、字符串拼接 SQL，或当前规则尚未覆盖该框架写法。")
    lines.append("")

    lines.append("### 关键过滤与分支条件\n")
    conditions = []
    for step in trace.steps:
        conditions.extend(step.conditions)
    if conditions:
        for condition in dict.fromkeys(conditions):
            lines.append(f"- `{condition}`")
    else:
        lines.append("未识别到显式过滤条件。")
    lines.append("")

    lines.append("### 伪代码\n")
    lines.append("```text")
    if trace.inputs:
        for source in trace.inputs:
            lines.append(f"read {source.name} -> {source.ref}")
    for step in trace.steps:
        refs = ", ".join(step.input_refs) or "unknown"
        lines.append(f"{step.output_ref} = {step.step_type}({refs})")
    refs = ", ".join(out.input_refs) or "unknown"
    lines.append(f"write {refs} -> {out.name}")
    lines.append("```")
    lines.append("")

    lines.append("### 未确认项\n")
    if trace.unresolved:
        for ref in trace.unresolved:
            lines.append(f"- `{ref}` 的上游来源未能静态确认。")
    else:
        lines.append("未发现未确认上游引用。")


def _escape_cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")

