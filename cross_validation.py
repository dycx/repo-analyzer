"""Cross-validation: verify LLM-generated analysis against Phase 1 ground truth.

Compares LLM output (Phase 2.5/3) with actual call graph, symbols, and imports
from Phase 1 to detect hallucinated or inaccurate relationships.
"""

import re
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    """Result of cross-validating LLM output against Phase 1 data."""
    verified_calls: list[dict] = field(default_factory=list)      # confirmed in call graph
    unverified_calls: list[dict] = field(default_factory=list)    # NOT in call graph (possible hallucination)
    missing_calls: list[dict] = field(default_factory=list)       # in call graph but not mentioned
    verified_tables: list[str] = field(default_factory=list)      # confirmed in SQL analysis
    unverified_tables: list[str] = field(default_factory=list)    # NOT found
    verified_udfs: list[str] = field(default_factory=list)        # confirmed UDF definitions
    unverified_udfs: list[str] = field(default_factory=list)      # NOT found in UDF registry
    accuracy_score: float = 0.0                                   # 0.0 - 1.0


def build_ground_truth(structure_data: dict, module_data: list[dict] = None) -> dict:
    """Build a ground truth index from Phase 1 structure data.

    Returns a dict with:
    - call_edges: set of (caller, callee) pairs
    - call_edges_by_name: dict[callee_name] -> list of (caller, file, line)
    - symbols: dict[symbol_name] -> list of (file, kind, line)
    - imports: set of (file, source) pairs
    - tables: set of table names found in SQL
    - udfs: dict[udf_name] -> list of (file, class, registration_type)
    - xml_loaders: dict[xml_file] -> list of (loader_file, method)
    """
    gt = {
        "call_edges": set(),
        "call_edges_by_name": {},
        "symbols": {},
        "imports": set(),
        "tables": set(),
        "udfs": {},
        "xml_loaders": {},
    }

    # Call graph from structure.json
    for edge in structure_data.get("call_graph", []):
        caller = edge.get("caller", "")
        callee = edge.get("callee", "")
        if caller and callee:
            gt["call_edges"].add((caller, callee))
            if callee not in gt["call_edges_by_name"]:
                gt["call_edges_by_name"][callee] = []
            gt["call_edges_by_name"][callee].append({
                "caller": caller,
                "file": edge.get("file", ""),
                "line": edge.get("line", 0),
            })

    # Import graph
    for imp in structure_data.get("import_graph", []):
        f = imp.get("file", "")
        s = imp.get("source", "")
        if f and s:
            gt["imports"].add((f, s))

    # Symbols from module data
    if module_data:
        for mod in module_data:
            for f in mod.get("files", []):
                for sym in f.get("symbols", []):
                    name = sym.get("name", "")
                    if name:
                        if name not in gt["symbols"]:
                            gt["symbols"][name] = []
                        gt["symbols"][name].append({
                            "file": f.get("path", ""),
                            "kind": sym.get("kind", ""),
                            "line": sym.get("line", 0),
                        })

            # SQL statements -> table references
            for f in mod.get("files", []):
                for sql in f.get("sql_stmts", []):
                    sql_text = sql.get("sql", "")
                    _extract_tables_from_sql(sql_text, gt["tables"])

            # Spark cross-ref
            for f in mod.get("files", []):
                for ref in f.get("spark_cross_ref", []):
                    for u in ref.get("udfs", []):
                        name = u.get("name", "")
                        if name:
                            if name not in gt["udfs"]:
                                gt["udfs"][name] = []
                            gt["udfs"][name].append({
                                "file": u.get("file", ""),
                                "class": u.get("class", ""),
                                "type": u.get("type", ""),
                            })
                    for xl in ref.get("xml_loaders", []):
                        xml_file = xl.get("xml_file", "")
                        if xml_file:
                            if xml_file not in gt["xml_loaders"]:
                                gt["xml_loaders"][xml_file] = []
                            gt["xml_loaders"][xml_file].append({
                                "loader_file": xl.get("loader_file", ""),
                                "method": xl.get("method", ""),
                            })

    return gt


def _extract_tables_from_sql(sql_text: str, tables: set):
    """Extract table names from SQL text."""
    pattern = re.compile(
        r'\b(?:FROM|JOIN|INTO|OVERWRITE\s+TABLE|TABLE)\s+[`"\']?(\w+(?:\.\w+)*?)[`"\']?',
        re.IGNORECASE,
    )
    skip = {"select", "where", "and", "or", "null", "set", "as", "on", "from"}
    for m in pattern.finditer(sql_text):
        name = m.group(1).strip('`"\'')
        if name.lower() not in skip:
            tables.add(name)


def validate_cross_module_calls(
    llm_flows: str,
    ground_truth: dict,
) -> ValidationResult:
    """Validate cross-module flow descriptions against Phase 1 call graph.

    Extracts function/module references from LLM output and checks them
    against the actual call graph.
    """
    result = ValidationResult()

    # Extract function calls mentioned in LLM output
    # Patterns: "A->>B: func_name", "func_name()", "module.func_name", "调用 xxx"
    mentioned_calls = set()

    # Sequence diagram messages: A->>B: func_name(args)
    for m in re.finditer(r'->>+[^:]+:\s*(\w+(?:\.\w+)?)', llm_flows):
        mentioned_calls.add(m.group(1))

    # Flowchart node labels with function names
    for m in re.finditer(r'\["?(?:调用|call)?\s*(\w+(?:\.\w+)?)["?\]]', llm_flows):
        mentioned_calls.add(m.group(1))

    # Generic function calls: name(...)
    for m in re.finditer(r'\b([a-zA-Z_]\w+(?:\.\w+)*)\s*\(', llm_flows):
        name = m.group(1)
        if len(name) > 3 and not name[0].isupper():  # skip class names
            mentioned_calls.add(name)

    # Check each mentioned call against ground truth
    for call_name in mentioned_calls:
        # Check in call graph (by callee name), symbols, or UDF registry
        if call_name in ground_truth["call_edges_by_name"]:
            refs = ground_truth["call_edges_by_name"][call_name]
            result.verified_calls.append({
                "name": call_name,
                "found_in": refs[0]["file"],
                "line": refs[0]["line"],
            })
        elif call_name in ground_truth["symbols"]:
            refs = ground_truth["symbols"][call_name]
            result.verified_calls.append({
                "name": call_name,
                "found_in": refs[0]["file"],
                "kind": refs[0]["kind"],
            })
        elif call_name in ground_truth["udfs"]:
            refs = ground_truth["udfs"][call_name]
            result.verified_calls.append({
                "name": call_name,
                "found_in": refs[0]["file"],
                "kind": "udf",
            })
        else:
            result.unverified_calls.append({"name": call_name})

    # Check table references
    mentioned_tables = set()
    for m in re.finditer(r'\b(?:FROM|JOIN|INTO|TABLE)\s+[`"\']?(\w+)', llm_flows, re.IGNORECASE):
        t = m.group(1).strip('`"\'')
        if t.lower() not in ("select", "where", "and", "or", "null", "set"):
            mentioned_tables.add(t)

    for table in mentioned_tables:
        if table in ground_truth["tables"]:
            result.verified_tables.append(table)
        else:
            result.unverified_tables.append(table)

    # Check UDF references
    for udf_name in ground_truth["udfs"]:
        if udf_name.lower() in llm_flows.lower():
            result.verified_udfs.append(udf_name)

    # Find unverified UDFs mentioned in LLM output but not in ground truth
    for m in re.finditer(r'\b(?:udf|UDF)[_]?(\w+)', llm_flows):
        name = m.group(1)
        if name and name not in ground_truth["udfs"]:
            result.unverified_udfs.append(name)

    # Calculate accuracy score
    total = len(result.verified_calls) + len(result.unverified_calls)
    if total > 0:
        result.accuracy_score = len(result.verified_calls) / total
    else:
        result.accuracy_score = 1.0  # no claims to verify

    return result


def build_validation_summary(result: ValidationResult) -> str:
    """Build a human-readable validation summary for embedding in prompts."""
    lines = []
    lines.append("## 交叉验证结果\n")

    if result.verified_calls:
        lines.append(f"### ✓ 已验证的调用关系 ({len(result.verified_calls)} 个)")
        for c in result.verified_calls[:20]:
            loc = f" @ {c.get('found_in', '')}:{c.get('line', '')}"
            lines.append(f"  - `{c['name']}`{loc}")

    if result.unverified_calls:
        lines.append(f"\n### ⚠ 未验证的调用 ({len(result.unverified_calls)} 个)")
        lines.append("以下调用在 Phase 1 结构分析中未找到，可能需要重新检查：")
        for c in result.unverified_calls[:20]:
            lines.append(f"  - `{c['name']}` — 未在调用图或符号表中找到")

    if result.verified_tables:
        lines.append(f"\n### ✓ 已验证的表引用 ({len(result.verified_tables)} 个)")
        for t in result.verified_tables:
            lines.append(f"  - `{t}`")

    if result.unverified_tables:
        lines.append(f"\n### ⚠ 未验证的表引用 ({len(result.unverified_tables)} 个)")
        for t in result.unverified_tables:
            lines.append(f"  - `{t}` — 未在 SQL 分析中找到")

    if result.verified_udfs:
        lines.append(f"\n### ✓ 已验证的 UDF ({len(result.verified_udfs)} 个)")
        for u in result.verified_udfs:
            lines.append(f"  - `{u}`")

    total = len(result.verified_calls) + len(result.unverified_calls)
    lines.append(f"\n**准确率**: {result.accuracy_score:.0%} ({len(result.verified_calls)}/{total} 已验证)")

    return "\n".join(lines)


def build_structured_context(
    structure_data: dict,
    module_data: list[dict],
    ground_truth: dict,
) -> str:
    """Build a structured context string with Phase 1 ground truth data.

    This replaces truncated text summaries with structured, verifiable data.
    """
    parts = []

    # Module interfaces (public functions/classes)
    parts.append("## 模块公共接口清单\n")
    for mod in module_data:
        mod_name = mod.get("module", "")
        pub_syms = []
        for f in mod.get("files", []):
            for s in f.get("symbols", []):
                if s.get("kind") in ("function", "class", "method", "interface"):
                    sig = s.get("signature", "")
                    name = s.get("name", "")
                    parent = s.get("parent", "")
                    qual = f"{parent}.{name}" if parent else name
                    pub_syms.append(f"  - `{qual}` {s['kind']} @ {f.get('path', '')}:{s.get('line', 0)}")
        if pub_syms:
            parts.append(f"### {mod_name}")
            parts.extend(pub_syms[:30])  # limit per module
            if len(pub_syms) > 30:
                parts.append(f"  ... ({len(pub_syms) - 30} more)")
            parts.append("")

    # Call graph edges (verified)
    cg = structure_data.get("call_graph", [])
    if cg:
        parts.append(f"## 验证过的调用关系 ({len(cg)} 条)\n")
        for edge in cg[:500]:
            parts.append(f"  `{edge['caller']}` → `{edge['callee']}` @ {edge.get('file', '')}:{edge.get('line', 0)}")
        if len(cg) > 500:
            parts.append(f"  ... ({len(cg) - 500} more edges)")
        parts.append("")

    # Import graph
    ig = structure_data.get("import_graph", [])
    if ig:
        parts.append(f"## 模块导入关系 ({len(ig)} 条)\n")
        for imp in ig[:300]:
            parts.append(f"  `{imp['file']}` imports `{imp['source']}`")
        if len(ig) > 300:
            parts.append(f"  ... ({len(ig) - 300} more)")
        parts.append("")

    # UDF registry
    if ground_truth["udfs"]:
        parts.append(f"## UDF 定义清单 ({len(ground_truth['udfs'])} 个)\n")
        for name, refs in ground_truth["udfs"].items():
            r = refs[0]
            parts.append(f"  - `{name}` @ {r.get('file', '')}:{r.get('line', 0)} ({r.get('type', '')})")
        parts.append("")

    # XML loader references
    if ground_truth["xml_loaders"]:
        parts.append(f"## XML 配置加载引用 ({len(ground_truth['xml_loaders'])} 个)\n")
        for xml_file, refs in ground_truth["xml_loaders"].items():
            for r in refs:
                parts.append(f"  - `{xml_file}` loaded by `{r['loader_file']}` via {r['method']}")
        parts.append("")

    # SQL-in-XML references
    sql_in_xml = []
    for mod in module_data:
        for f in mod.get("files", []):
            for sym in f.get("symbols", []):
                if sym.get("kind") == "sql_in_xml":
                    sql_in_xml.append(sym)
    if sql_in_xml:
        parts.append(f"## XML 中的 SQL 语句 ({len(sql_in_xml)} 条)\n")
        for s in sql_in_xml[:50]:
            parts.append(f"  - `{s.get('parent', '')}` @ {s.get('file', '')}:{s.get('line', 0)}")
            sig = s.get("signature", "")
            if sig:
                parts.append(f"    ```{sig[:200]}```")
        parts.append("")

    return "\n".join(parts)
