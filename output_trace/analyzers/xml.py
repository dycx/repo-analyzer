"""XML configured Spark SQL analyzer."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from output_trace.ir import FactStore
from output_trace.sql import analyze_sql
from output_trace.text import line_for_offset


SQL_BLOCK_RE = re.compile(
    r"((?:SELECT|INSERT|CREATE\s+TABLE|CREATE\s+OR\s+REPLACE|MERGE\s+INTO)\b.*?)(?=<\/|$)",
    re.IGNORECASE | re.DOTALL,
)


def analyze_xml(path: str, rel_path: str, repo_root: str) -> FactStore:
    with open(path, encoding="utf-8", errors="ignore") as handle:
        source = handle.read()
    facts = FactStore(repo_root=repo_root)
    parsed_any_sql = False
    try:
        root = ET.fromstring(source)
        for element in root.iter():
            candidates = []
            if element.text:
                candidates.append(element.text)
            candidates.extend(element.attrib.values())
            for text in candidates:
                if _looks_like_sql(text):
                    parsed_any_sql = True
                    line = _line_for_text(source, text)
                    sql_facts = analyze_sql(text, rel_path, line, repo_root, kind="xml_spark_sql")
                    _mark_xml_sql(sql_facts)
                    facts.extend(sql_facts)
    except ET.ParseError as exc:
        facts.warnings.append(f"XML parse failed for {rel_path}; regex fallback used: {exc}")

    if not parsed_any_sql:
        for match in SQL_BLOCK_RE.finditer(source):
            sql = match.group(1)
            if _looks_like_sql(sql):
                sql_facts = analyze_sql(sql, rel_path, line_for_offset(source, match.start()), repo_root, kind="xml_spark_sql")
                _mark_xml_sql(sql_facts)
                facts.extend(sql_facts)
    return facts


def _mark_xml_sql(facts: FactStore) -> None:
    for operation in facts.operations:
        operation.kind = "xml_spark_sql"
    for sink in facts.sinks:
        if not sink.format:
            sink.format = "sql"


def _looks_like_sql(text: str) -> bool:
    upper = " ".join(text.upper().split())
    return any(keyword in upper for keyword in ("SELECT ", "INSERT ", "CREATE TABLE", "MERGE INTO"))


def _line_for_text(source: str, text: str) -> int:
    offset = source.find(text)
    return line_for_offset(source, offset if offset >= 0 else 0)

