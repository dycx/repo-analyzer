"""Intermediate representation for output-driven dataflow analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Location:
    """A source-code location used as evidence."""

    file: str
    line: int
    end_line: int | None = None

    def label(self) -> str:
        if self.end_line and self.end_line != self.line:
            return f"{self.file}:{self.line}-{self.end_line}"
        return f"{self.file}:{self.line}"


@dataclass
class Source:
    """A physical or logical input dataset."""

    id: str
    name: str
    kind: str
    location: Location
    evidence: str
    format: str = ""


@dataclass
class Sink:
    """A physical or logical output dataset."""

    id: str
    name: str
    kind: str
    depends_on: list[str]
    location: Location
    evidence: str
    format: str = ""


@dataclass
class Operation:
    """A computation step that transforms upstream refs into an output ref."""

    id: str
    kind: str
    output: str
    inputs: list[str]
    location: Location
    evidence: str
    expression: str = ""
    fields: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    formulas: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class FieldRule:
    """A best-effort statement about how one output field is produced."""

    field: str
    formula: str
    input_fields: list[str]
    conditions: list[str]
    evidence: list[Location]


@dataclass
class FactStore:
    """All facts extracted from a repository before output slicing."""

    repo_root: str
    sources: list[Source] = field(default_factory=list)
    sinks: list[Sink] = field(default_factory=list)
    operations: list[Operation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def extend(self, other: "FactStore") -> None:
        self.sources.extend(other.sources)
        self.sinks.extend(other.sinks)
        self.operations.extend(other.operations)
        self.warnings.extend(other.warnings)


@dataclass
class OutputTrace:
    """A backward slice rooted at one output sink."""

    sink: Sink
    sources: list[Source]
    operations: list[Operation]
    field_rules: list[FieldRule]
    unresolved_refs: list[str]
    confidence: str


def to_jsonable(value: Any) -> Any:
    """Convert IR dataclasses to JSON-safe values."""
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    return value

