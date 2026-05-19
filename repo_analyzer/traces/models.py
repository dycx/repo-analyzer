"""Shared data models for output-oriented tracing."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CodeLocation:
    """A source location used as evidence for a trace fact."""

    file: str
    line: int
    end_line: int | None = None

    def label(self) -> str:
        if self.end_line and self.end_line != self.line:
            return f"{self.file}:{self.line}-{self.end_line}"
        return f"{self.file}:{self.line}"


@dataclass
class InputSource:
    """A concrete upstream data source."""

    name: str
    source_type: str
    ref: str
    location: CodeLocation
    evidence: str
    format: str = ""


@dataclass
class OutputSink:
    """A concrete write/return/publish point."""

    name: str
    sink_type: str
    input_refs: list[str]
    location: CodeLocation
    evidence: str
    format: str = ""


@dataclass
class TransformStep:
    """A data transformation or computation step."""

    step_id: str
    step_type: str
    input_refs: list[str]
    output_ref: str
    expression: str
    location: CodeLocation
    evidence: str
    fields: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    formulas: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class FieldLineage:
    """A best-effort field-level lineage statement."""

    output_field: str
    input_fields: list[str]
    formula: str
    conditions: list[str]
    evidence: list[CodeLocation]


@dataclass
class AnalysisFacts:
    """Facts extracted from source files before slicing by output."""

    repo_path: str
    inputs: list[InputSource] = field(default_factory=list)
    outputs: list[OutputSink] = field(default_factory=list)
    steps: list[TransformStep] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: "AnalysisFacts") -> None:
        self.inputs.extend(other.inputs)
        self.outputs.extend(other.outputs)
        self.steps.extend(other.steps)
        self.warnings.extend(other.warnings)


@dataclass
class OutputTrace:
    """The final trace for one output sink."""

    output: OutputSink
    inputs: list[InputSource]
    steps: list[TransformStep]
    field_lineage: list[FieldLineage]
    unresolved: list[str]
    confidence: str


def dataclass_to_dict(value: Any) -> Any:
    """Convert trace dataclasses to JSON-safe dictionaries."""
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [dataclass_to_dict(v) for v in value]
    if isinstance(value, dict):
        return {k: dataclass_to_dict(v) for k, v in value.items()}
    return value

