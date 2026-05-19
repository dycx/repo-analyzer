"""Build output traces from extracted input/transform/output facts."""

from __future__ import annotations

from collections import defaultdict

from repo_analyzer.traces.models import (
    AnalysisFacts,
    FieldLineage,
    InputSource,
    OutputSink,
    OutputTrace,
    TransformStep,
)
from repo_analyzer.traces.semantics import lineage_from_steps


def build_output_traces(facts: AnalysisFacts) -> list[OutputTrace]:
    """Create one backward-sliced trace for each output sink."""
    inputs_by_ref: dict[str, list[InputSource]] = defaultdict(list)
    for source in facts.inputs:
        inputs_by_ref[source.ref].append(source)
        if source.source_type == "table":
            inputs_by_ref[f"table:{source.name}"].append(source)

    steps_by_output: dict[str, list[TransformStep]] = defaultdict(list)
    for step in facts.steps:
        steps_by_output[step.output_ref].append(step)

    traces: list[OutputTrace] = []
    for output in facts.outputs:
        trace_inputs: list[InputSource] = []
        trace_steps: list[TransformStep] = []
        unresolved: list[str] = []
        seen_refs: set[str] = set()
        seen_steps: set[str] = set()
        seen_inputs: set[tuple[str, str, int]] = set()

        def visit_ref(ref: str, depth: int = 0) -> None:
            if not ref or depth > 24:
                return
            if ref in seen_refs:
                return
            seen_refs.add(ref)

            matched_input = False
            for source in inputs_by_ref.get(ref, []):
                key = (source.ref, source.location.file, source.location.line)
                if key not in seen_inputs:
                    trace_inputs.append(source)
                    seen_inputs.add(key)
                matched_input = True

            matched_step = False
            for step in steps_by_output.get(ref, []):
                if step.step_id not in seen_steps:
                    trace_steps.append(step)
                    seen_steps.add(step.step_id)
                matched_step = True
                for upstream in step.input_refs:
                    visit_ref(upstream, depth + 1)

            if not matched_input and not matched_step and not _is_literal_or_framework_ref(ref):
                unresolved.append(ref)

        output_refs = list(output.input_refs)
        table_ref = f"table:{output.name}"
        if output.sink_type == "table" and table_ref in steps_by_output:
            output_refs.insert(0, table_ref)
        for ref in output_refs:
            visit_ref(ref)

        ordered_steps = _order_steps_upstream_first(trace_steps)
        field_lineage = lineage_from_steps(ordered_steps)
        confidence = _confidence(output, trace_inputs, ordered_steps, unresolved)
        traces.append(OutputTrace(
            output=output,
            inputs=_dedupe_inputs(trace_inputs),
            steps=ordered_steps,
            field_lineage=_dedupe_lineage(field_lineage),
            unresolved=sorted(set(unresolved)),
            confidence=confidence,
        ))

    return traces


def _order_steps_upstream_first(steps: list[TransformStep]) -> list[TransformStep]:
    return sorted(steps, key=lambda s: (s.location.file, s.location.line, s.step_id))


def _dedupe_inputs(inputs: list[InputSource]) -> list[InputSource]:
    seen: set[tuple[str, str, int]] = set()
    result: list[InputSource] = []
    for source in inputs:
        key = (source.ref, source.location.file, source.location.line)
        if key in seen:
            continue
        seen.add(key)
        result.append(source)
    return result


def _dedupe_lineage(lineage: list[FieldLineage]) -> list[FieldLineage]:
    seen: set[tuple[str, str]] = set()
    result: list[FieldLineage] = []
    for item in lineage:
        key = (item.output_field, item.formula)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _confidence(
    output: OutputSink,
    inputs: list[InputSource],
    steps: list[TransformStep],
    unresolved: list[str],
) -> str:
    if inputs and steps and not unresolved:
        return "high"
    if inputs and steps:
        return "medium"
    if inputs or steps or output.input_refs:
        return "low"
    return "unknown"


def _is_literal_or_framework_ref(ref: str) -> bool:
    lowered = ref.lower()
    return (
        lowered in {"f", "pd", "spark", "sqlcontext", "hivecontext", "path", "str"}
        or lowered.startswith("table:")
        and "." not in lowered
    )
