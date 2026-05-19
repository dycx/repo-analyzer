# Greenfield Output Trace Analyzer

This branch contains a clean implementation of the output-oriented analyzer.
It intentionally does not reuse the existing `repo_analyzer` phases.

## Goal

The analyzer answers:

> Which inputs and computations produce each output file, table, API response, or message?

The generated report is organized by output and emphasizes:

- input sources
- data transformations
- filters
- joins
- grouping and aggregation
- field-level computation rules
- unresolved upstream references

## Run

```bash
python -m output_trace /path/to/repo
python -m output_trace /path/to/repo -o /tmp/output-trace.md
```

## Supported MVP Scope

- Python Pandas / Spark-style operations
- Java / Scala Spark-style operations
- SQL files and embedded Spark SQL strings
- XML configuration files containing Spark SQL step text

The XML analyzer is schema-agnostic: it scans element text and attributes for
SQL-looking content, then analyzes that SQL as a Spark SQL step.

## Architecture

```text
scanner -> language analyzers -> FactStore -> trace graph -> reports
```

The core IR lives in `output_trace/ir.py`:

- `Source`: input dataset
- `Sink`: output dataset
- `Operation`: transformation step
- `OutputTrace`: backward slice rooted at a sink

This is meant to be compared with the incremental implementation on
`codex/output-trace-dataflow`.

