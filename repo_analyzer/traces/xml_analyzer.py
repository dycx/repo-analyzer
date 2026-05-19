"""XML-configured Spark SQL step extraction."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET

from repo_analyzer.traces.models import AnalysisFacts, CodeLocation, TransformStep
from repo_analyzer.traces.patterns import safe_ref, summarize_expression
from repo_analyzer.traces.sql_analyzer import analyze_sql_text


_SQL_BLOCK_RE = re.compile(
    r"((?:SELECT|INSERT|CREATE\s+TABLE|CREATE\s+OR\s+REPLACE|MERGE\s+INTO)\b.*?)(?=<\/|$)",
    re.IGNORECASE | re.DOTALL,
)


def analyze_xml_file(path: str, repo_root: str) -> AnalysisFacts:
    with open(path, encoding="utf-8", errors="ignore") as f:
        source = f.read()
    rel = os.path.relpath(path, repo_root)
    facts = AnalysisFacts(repo_path=repo_root)
    parsed_had_sql = False

    # ElementTree gives us text/attribute access when the file is valid XML.
    try:
        root = ET.fromstring(source)
        for elem in root.iter():
            texts = []
            if elem.text:
                texts.append(elem.text)
            texts.extend(elem.attrib.values())
            for text in texts:
                if _looks_like_sql(text):
                    parsed_had_sql = True
                    line = _line_for_text(source, text)
                    facts.merge(analyze_sql_text(
                        text,
                        rel,
                        line,
                        repo_root,
                        ref_prefix="xml_sql",
                        step_type="spark_sql_step",
                    ))
    except ET.ParseError:
        facts.warnings.append(f"XML parse failed for {rel}; falling back to regex SQL extraction")

    # Regex fallback also catches CDATA and loosely structured step configs.
    if not parsed_had_sql:
        for match in _SQL_BLOCK_RE.finditer(source):
            sql = match.group(1)
            if _looks_like_sql(sql):
                line = source[: match.start()].count("\n") + 1
                before = len(facts.steps)
                facts.merge(analyze_sql_text(
                    sql,
                    rel,
                    line,
                    repo_root,
                    ref_prefix="xml_sql",
                    step_type="spark_sql_step",
                ))
                for step in facts.steps[before:]:
                    _mark_xml_step(step, rel, line)

    return facts


def _mark_xml_step(step: TransformStep, file_path: str, line: int) -> None:
    if step.step_type != "spark_sql_step":
        step.step_type = "spark_sql_step"
    if not step.step_id.startswith("xml_sql"):
        step.step_id = safe_ref("xml_sql", file_path, line, "spark_sql_step")
    step.evidence = summarize_expression(step.evidence, limit=800)


def _looks_like_sql(text: str) -> bool:
    upper = " ".join(text.upper().split())
    return any(keyword in upper for keyword in ("SELECT ", "INSERT ", "CREATE TABLE", "MERGE INTO"))


def _line_for_text(source: str, text: str) -> int:
    idx = source.find(text)
    if idx < 0:
        return 1
    return source[:idx].count("\n") + 1
