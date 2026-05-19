"""Build output-specific traces from extracted facts."""

from __future__ import annotations

from collections import defaultdict

from output_trace.ir import FactStore, Operation, OutputTrace, Source
from output_trace.semantics import field_rules_from_operations


def build_traces(facts: FactStore) -> list[OutputTrace]:
    """Return one trace per sink by walking upstream refs."""
    sources_by_id: dict[str, list[Source]] = defaultdict(list)
    for source in facts.sources:
        sources_by_id[source.id].append(source)
        if source.kind == "table":
            sources_by_id[f"table:{source.name}"].append(source)

    operations_by_output: dict[str, list[Operation]] = defaultdict(list)
    for operation in facts.operations:
        operations_by_output[operation.output].append(operation)

    traces: list[OutputTrace] = []
    for sink in facts.sinks:
        trace_sources: list[Source] = []
        trace_operations: list[Operation] = []
        unresolved: set[str] = set()
        seen_refs: set[str] = set()
        seen_sources: set[tuple[str, str, int]] = set()
        seen_operations: set[str] = set()

        roots = list(sink.depends_on)
        table_root = f"table:{sink.name}"
        if sink.kind == "table" and table_root in operations_by_output:
            roots.insert(0, table_root)

        def visit(ref: str, depth: int = 0) -> None:
            if not ref or depth > 32 or ref in seen_refs:
                return
            seen_refs.add(ref)
            matched = False
            for source in sources_by_id.get(ref, []):
                key = (source.id, source.location.file, source.location.line)
                if key not in seen_sources:
                    trace_sources.append(source)
                    seen_sources.add(key)
                matched = True
            for operation in operations_by_output.get(ref, []):
                if operation.id not in seen_operations:
                    trace_operations.append(operation)
                    seen_operations.add(operation.id)
                matched = True
                for upstream in operation.inputs:
                    visit(upstream, depth + 1)
            if not matched and not _ignore_unresolved(ref):
                unresolved.add(ref)

        for root in roots:
            visit(root)

        ordered_ops = sorted(trace_operations, key=lambda item: (item.location.file, item.location.line, item.id))
        traces.append(OutputTrace(
            sink=sink,
            sources=sorted(trace_sources, key=lambda item: (item.location.file, item.location.line, item.id)),
            operations=ordered_ops,
            field_rules=field_rules_from_operations(ordered_ops),
            unresolved_refs=sorted(unresolved),
            confidence=_confidence(trace_sources, ordered_ops, unresolved),
        ))
    return traces


def _confidence(sources: list[Source], operations: list[Operation], unresolved: set[str]) -> str:
    if sources and operations and not unresolved:
        return "high"
    if sources and operations:
        return "medium"
    if sources or operations:
        return "low"
    return "unknown"


def _ignore_unresolved(ref: str) -> bool:
    return ref in {"spark", "pd", "pandas"} or ref.startswith("literal:")

