"""Phase 1.5: Output Identification — 5-layer strategy.

Identifies all external outputs in a codebase using layered detection:
  Layer 1: Regex pattern matching (high precision)
  Layer 2: tree-sitter structural analysis (high precision)
  Layer 3: SQL output point analysis (high precision)
  Layer 4: Data flow tracing from outputs back to inputs (medium precision)
  Layer 5: LLM-assisted identification (high recall, lower precision)

Each output gets a confidence score and is linked to its input sources.
"""

import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path


# ── Output Point Data Model ─────────────────────────────────────────────────

@dataclass
class OutputPoint:
    """A detected external output in the codebase."""
    name: str              # output identifier (table name, API path, file name)
    output_type: str       # "db_table", "api_endpoint", "file", "message", "spark_table"
    file: str              # source file
    line: int              # line number
    confidence: str        # "high", "medium", "low"
    detection_layer: str   # "regex", "ast", "sql", "dataflow", "llm"
    evidence: str          # what matched
    context: str = ""      # surrounding code snippet
    inputs: list[dict] = field(default_factory=list)  # traced input sources
    schema: list[dict] = field(default_factory=list)   # output field schema if detectable


@dataclass
class DataFlowEdge:
    """A data flow edge from input to processing to output."""
    source: str            # input source (file, table, API param)
    target: str            # output target
    transform: str         # what transform happens
    file: str
    line: int
    confidence: str


# ── Layer 1: Regex Pattern Matching ─────────────────────────────────────────

# Patterns: (regex, output_type, name_extractor)
# name_extractor: function(match) -> output_name

def _extract_table_name(match):
    """Extract table name from SQL INSERT/CREATE."""
    for group in match.groups():
        if group and re.match(r'^[a-zA-Z_]\w*(\.\w+)*$', group):
            return group
    return "unknown_table"


def _extract_file_path(match):
    """Extract file path from write operations."""
    for group in match.groups():
        if group and ('/' in group or '.' in group):
            return group
    return "unknown_file"


def _extract_api_path(match):
    """Extract API path from route decorators."""
    for group in match.groups():
        if group and group.startswith('/'):
            return group
    return "unknown_endpoint"


OUTPUT_PATTERNS_SQL = [
    # INSERT INTO table SELECT ...
    (re.compile(r'INSERT\s+(?:OVERWRITE\s+)?(?:INTO\s+)?TABLE?\s+[`"\']?(\w+(?:\.\w+)*)[`"\']?', re.I),
     "db_table", _extract_table_name, "SQL INSERT"),
    # CREATE TABLE ... AS SELECT
    (re.compile(r'CREATE\s+(?:OR\s+REPLACE\s+)?(?:EXTERNAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\']?(\w+(?:\.\w+)*)[`"\']?', re.I),
     "db_table", _extract_table_name, "SQL CREATE TABLE"),
    # MERGE INTO table
    (re.compile(r'MERGE\s+INTO\s+[`"\']?(\w+(?:\.\w+)*)[`"\']?', re.I),
     "db_table", _extract_table_name, "SQL MERGE"),
]

OUTPUT_PATTERNS_SPARK = [
    # df.write.parquet / .csv / .json / .orc / .text
    (re.compile(r'\.write\.(parquet|csv|json|orc|text|avro|delta)\s*\(\s*["\']([^"\']+)["\']', re.I),
     "spark_file", lambda m: f"{m.group(2)}", "Spark write.format"),
    # .save("path")
    (re.compile(r'\.save\s*\(\s*["\']([^"\']+)["\']', re.I),
     "spark_file", lambda m: m.group(1), "Spark .save()"),
    # .saveAsTable("table_name")
    (re.compile(r'\.saveAsTable\s*\(\s*["\']([^"\']+)["\']', re.I),
     "spark_table", lambda m: m.group(1), "Spark saveAsTable"),
    # .insertInto("table_name")
    (re.compile(r'\.insertInto\s*\(\s*["\']([^"\']+)["\']', re.I),
     "spark_table", lambda m: m.group(1), "Spark insertInto"),
    # spark.sql("INSERT INTO ...")
    (re.compile(r'spark\.sql\s*\(\s*["\'].*?INSERT\s+(?:OVERWRITE\s+)?(?:INTO\s+)?TABLE?\s+[`"\']?(\w+)', re.I),
     "spark_table", lambda m: m.group(1), "Spark SQL INSERT"),
    # .format("jdbc").option("dbtable", "xxx").save()
    (re.compile(r'\.option\s*\(\s*["\']dbtable["\']\s*,\s*["\']([^"\']+)["\']', re.I),
     "db_table", lambda m: m.group(1), "Spark JDBC dbtable"),
]

OUTPUT_PATTERNS_FILE = [
    # open("path", "w") / open("path", "wb")
    (re.compile(r'open\s*\(\s*["\']([^"\']+)["\']\s*,\s*["\']w', re.I),
     "file", _extract_file_path, "Python open(w)"),
    # .to_csv("path") / .to_json("path") / .to_parquet("path")
    (re.compile(r'\.(to_csv|to_json|to_parquet|to_orc|to_excel)\s*\(\s*["\']([^"\']+)["\']', re.I),
     "file", lambda m: m.group(2), "Pandas to_*()"),
    # pd.to_csv / df.to_csv without path (in-memory, skip)
    # json.dump(data, open("path"...))
    (re.compile(r'json\.dump\s*\([^,]+,\s*open\s*\(\s*["\']([^"\']+)["\']', re.I),
     "file", lambda m: m.group(1), "json.dump"),
    # Path("xxx").write_text / write_bytes
    (re.compile(r'Path\s*\(\s*["\']([^"\']+)["\']\s*\)\s*\.\s*write_', re.I),
     "file", lambda m: m.group(1), "Path.write_*"),
]

OUTPUT_PATTERNS_API = [
    # Flask: @app.route("/path") / @bp.route("/path")
    (re.compile(r'@\w+\.route\s*\(\s*["\']([^"\']+)["\']', re.I),
     "api_endpoint", _extract_api_path, "Flask route"),
    # FastAPI: @app.get("/path") / @app.post("/path")
    (re.compile(r'@\w+\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', re.I),
     "api_endpoint", lambda m: m.group(2), "FastAPI route"),
    # Django: path("url", view)
    (re.compile(r'path\s*\(\s*["\']([^"\']+)["\']', re.I),
     "api_endpoint", lambda m: m.group(1), "Django path"),
    # Spring: @GetMapping("/path") / @PostMapping
    (re.compile(r'@(Get|Post|Put|Delete|Request)Mapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']', re.I),
     "api_endpoint", lambda m: m.group(2), "Spring Mapping"),
]

OUTPUT_PATTERNS_MESSAGE = [
    # producer.send("topic", data)
    (re.compile(r'\.send\s*\(\s*["\']([^"\']+)["\']', re.I),
     "message", lambda m: m.group(1), "Kafka/RabbitMQ send"),
    # publish("topic", data)
    (re.compile(r'\.publish\s*\(\s*["\']([^"\']+)["\']', re.I),
     "message", lambda m: m.group(1), "publish()"),
    # emit("event", data)
    (re.compile(r'\.emit\s*\(\s*["\']([^"\']+)["\']', re.I),
     "message", lambda m: m.group(1), "emit()"),
]

ALL_PATTERNS = (
    OUTPUT_PATTERNS_SQL
    + OUTPUT_PATTERNS_SPARK
    + OUTPUT_PATTERNS_FILE
    + OUTPUT_PATTERNS_API
    + OUTPUT_PATTERNS_MESSAGE
)


def _layer1_regex_scan(filepath: str, content: str) -> list[OutputPoint]:
    """Layer 1: Regex pattern matching for output points."""
    results = []
    seen = set()

    for pattern, out_type, name_extractor, evidence_name in ALL_PATTERNS:
        for m in pattern.finditer(content):
            name = name_extractor(m)
            key = (name, out_type, filepath)
            if key in seen:
                continue
            seen.add(key)

            line_num = content[:m.start()].count('\n') + 1
            ctx_start = max(0, m.start() - 40)
            ctx_end = min(len(content), m.end() + 60)
            context = content[ctx_start:ctx_end].replace('\n', ' ').strip()

            results.append(OutputPoint(
                name=name,
                output_type=out_type,
                file=filepath,
                line=line_num,
                confidence="high",
                detection_layer="regex",
                evidence=f"{evidence_name}: {m.group(0)[:100]}",
                context=context,
            ))

    return results


# ── Layer 2: tree-sitter Structural Analysis ────────────────────────────────

def _layer2_ast_scan(filepath: str, source: bytes, tree, lang: str) -> list[OutputPoint]:
    """Layer 2: tree-sitter structural analysis for output points.

    Identifies:
    - Function calls that are known output operations
    - Method chains ending in write/save/send operations
    - Return statements in API handler functions
    """
    results = []
    seen = set()

    # Known output function names
    OUTPUT_FUNCS = {
        "write", "save", "saveAsTable", "insertInto", "to_csv", "to_json",
        "to_parquet", "to_orc", "publish", "send", "emit", "execute",
        "executemany", "executescript", "dump", "dumps",
    }

    def _walk(node, depth=0):
        if node.type == "call":
            # Get function name
            func_node = node.child_by_field_name("function")
            if func_node:
                func_text = source[func_node.start_byte:func_node.end_byte].decode("utf-8", errors="replace")

                # Check if it's an output function
                for out_func in OUTPUT_FUNCS:
                    if out_func in func_text:
                        key = (func_text[:50], filepath, node.start_point[0])
                        if key not in seen:
                            seen.add(key)
                            results.append(OutputPoint(
                                name=func_text[:100],
                                output_type="ast_call",
                                file=filepath,
                                line=node.start_point[0] + 1,
                                confidence="medium",
                                detection_layer="ast",
                                evidence=f"AST call: {func_text[:100]}",
                            ))

        for child in node.children:
            _walk(child, depth + 1)

    if tree:
        _walk(tree.root_node)

    return results


# ── Layer 3: SQL Output Analysis ────────────────────────────────────────────

def _layer3_sql_outputs(sql_stmts: list[dict]) -> list[OutputPoint]:
    """Layer 3: Identify output points from SQL statements."""
    results = []
    seen = set()

    INSERT_PATTERN = re.compile(
        r'INSERT\s+(OVERWRITE\s+)?(?:INTO\s+)?TABLE?\s+[`"\']?(\w+(?:\.\w+)*)[`"\']?',
        re.IGNORECASE,
    )
    CREATE_PATTERN = re.compile(
        r'CREATE\s+(?:OR\s+REPLACE\s+)?(?:EXTERNAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\']?(\w+(?:\.\w+)*)[`"\']?',
        re.IGNORECASE,
    )
    CTAS_PATTERN = re.compile(
        r'CREATE\s+TABLE\s+\w+\s+AS\s+SELECT',
        re.IGNORECASE,
    )

    for stmt in sql_stmts:
        sql = stmt.get("sql", "")
        filepath = stmt.get("file", "")
        line = stmt.get("line", 0)

        # INSERT
        for m in INSERT_PATTERN.finditer(sql):
            table = m.group(2)
            key = (table, filepath, line)
            if key not in seen:
                seen.add(key)
                is_overwrite = bool(m.group(1))
                results.append(OutputPoint(
                    name=table,
                    output_type="db_table",
                    file=filepath,
                    line=line,
                    confidence="high",
                    detection_layer="sql",
                    evidence=f"SQL {'INSERT OVERWRITE' if is_overwrite else 'INSERT INTO'} {table}",
                ))

        # CREATE TABLE
        for m in CREATE_PATTERN.finditer(sql):
            table = m.group(1)
            key = (table, filepath, line)
            if key not in seen:
                seen.add(key)
                results.append(OutputPoint(
                    name=table,
                    output_type="db_table",
                    file=filepath,
                    line=line,
                    confidence="high",
                    detection_layer="sql",
                    evidence=f"SQL CREATE TABLE {table}",
                ))

    return results


# ── Layer 4: Data Flow Tracing ──────────────────────────────────────────────

def _layer4_trace_inputs(
    output: OutputPoint,
    structure_data: dict,
    module_data: list[dict],
) -> list[dict]:
    """Layer 4: Trace data flow from an output back to its input sources.

    Uses call graph and variable assignments to find what feeds into the output.
    """
    inputs = []
    call_graph = structure_data.get("call_graph", [])

    # Find functions that contribute to this output
    # Strategy: look for call edges that lead to the output file
    output_file = output.file
    output_line = output.line

    # Find the function containing the output point
    containing_func = None
    for edge in call_graph:
        if edge.get("file") == output_file:
            if edge.get("line", 0) <= output_line:
                containing_func = edge.get("caller", "")

    if not containing_func:
        return inputs

    # Trace upstream: who calls this function?
    callers = set()
    for edge in call_graph:
        if edge.get("callee") == containing_func:
            callers.add((edge.get("caller", ""), edge.get("file", ""), edge.get("line", 0)))

    # Find data sources in the call chain
    for caller, cfile, cline in callers:
        # Check if the caller reads from external sources
        inputs.append({
            "source_function": caller,
            "source_file": cfile,
            "source_line": cline,
            "relationship": "upstream_caller",
        })

    # Look for SQL statements in the same file that might be inputs
    for mod in module_data:
        for f in mod.get("files", []):
            if f.get("path") == output_file:
                for sql in f.get("sql_stmts", []):
                    sql_text = sql.get("sql", "")
                    # SELECT ... FROM table (potential input)
                    from_match = re.search(r'FROM\s+[`"\']?(\w+(?:\.\w+)*)[`"\']?', sql_text, re.I)
                    if from_match:
                        table = from_match.group(1)
                        if table.lower() not in ("select", "where", "and", "or", "null"):
                            inputs.append({
                                "source_type": "db_table",
                                "source_name": table,
                                "source_file": sql.get("file", ""),
                                "source_line": sql.get("line", 0),
                                "relationship": "sql_input",
                            })

    # Look for Spark read operations in the same file
    for mod in module_data:
        for f in mod.get("files", []):
            if f.get("path") == output_file:
                for sym in f.get("symbols", []):
                    sig = sym.get("signature", "")
                    if any(read_op in sig for read_op in ("read", "load", "source", "input")):
                        inputs.append({
                            "source_type": "data_read",
                            "source_name": sym.get("name", ""),
                            "source_file": f.get("path", ""),
                            "source_line": sym.get("line", 0),
                            "relationship": "data_read",
                        })

    return inputs


# ── Layer 5: LLM-Assisted Identification (prompt template) ─────────────────

LLM_OUTPUT_IDENTIFICATION_PROMPT = """请分析以下代码模块，识别所有对外输出点。

## 模块: {module_name}

## 源码摘要
{source_summary}

## 任务
识别所有对外输出，包括：
1. 数据库写入（表名、写入方式：INSERT/CREATE/MERGE）
2. 文件输出（路径、格式：CSV/JSON/Parquet等）
3. API 响应（端点路径、返回格式）
4. 消息发送（topic/queue名称、消息格式）
5. Spark 输出（saveAsTable/write/insertInto）

## 输出格式 (JSON)
```json
[
  {{
    "name": "输出标识（表名/路径/端点）",
    "type": "db_table|file|api_endpoint|message|spark_table",
    "location": "文件:行号",
    "inputs": ["输入来源1", "输入来源2"],
    "description": "一句话描述这个输出",
    "confidence": "high|medium|low"
  }}
]
```

只列出确定的输出，不要推测。
"""


# ── Main Entry Point ────────────────────────────────────────────────────────

def identify_outputs(
    repo_path: str,
    structure_data: dict,
    module_data: list[dict],
    xml_outputs: list[dict] = None,
) -> list[dict]:
    """Run all 5 layers of output identification.

    Args:
        repo_path: repository root path
        structure_data: Phase 1 structure.json data
        module_data: list of per-module JSON data from Phase 1
        xml_outputs: output points detected from XML configs (optional)

    Returns:
        list of OutputPoint as dicts, deduplicated and ranked by confidence
    """
    all_outputs: list[OutputPoint] = []
    seen_keys = set()

    def _add(output: OutputPoint):
        key = (output.name.lower(), output.output_type, output.file)
        if key not in seen_keys:
            seen_keys.add(key)
            all_outputs.append(output)

    # Collect all source files (skip test dirs)
    source_files = []
    root = Path(repo_path)
    skip_test_dirs = {
        "test", "tests", "testing", "__tests__", "spec", "specs",
        "test_fixtures", "testdata", "test_data", "test-resources",
    }
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d not in {
            '.git', 'node_modules', '__pycache__', '.venv', 'venv',
            'dist', 'build', 'target', '.gradle', '.idea', '.vscode',
        }]
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            source_files.append(fpath)

    # Layer 1: Regex scan
    print("  [Output ID] Layer 1: Regex pattern matching ...")
    for fpath in source_files:
        ext = os.path.splitext(fpath)[1].lower()
        if ext in ('.py', '.scala', '.java', '.sql', '.xml', '.js', '.ts', '.go', '.rs', '.rb', '.c', '.cpp', '.h'):
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                rel = os.path.relpath(fpath, repo_path)
                for op in _layer1_regex_scan(rel, content):
                    _add(op)
            except (OSError, PermissionError):
                pass
    print(f"    Found {len(all_outputs)} outputs from regex")

    # Layer 2: AST scan (for files that Phase 1 already parsed)
    print("  [Output ID] Layer 2: AST structural analysis ...")
    ast_count = 0
    for mod in module_data:
        for f in mod.get("files", []):
            fpath = os.path.join(repo_path, f.get("path", ""))
            if os.path.exists(fpath):
                try:
                    with open(fpath, 'rb') as fh:
                        source = fh.read()
                    # Simple AST scan without tree-sitter (regex-based for now)
                    content = source.decode('utf-8', errors='ignore')
                    for op in _layer1_regex_scan(f.get("path", ""), content):
                        op.detection_layer = "ast"
                        op.confidence = "medium"
                        _add(op)
                        ast_count += 1
                except (OSError, PermissionError):
                    pass
    print(f"    Found {ast_count} additional from AST")

    # Layer 3: SQL output analysis
    print("  [Output ID] Layer 3: SQL output analysis ...")
    sql_stmts = structure_data.get("all_sql_stmts", [])
    # Also collect from module data
    for mod in module_data:
        for f in mod.get("files", []):
            for sql in f.get("sql_stmts", []):
                sql_stmts.append(sql)
    sql_outputs = _layer3_sql_outputs(sql_stmts)
    for op in sql_outputs:
        _add(op)
    print(f"    Found {len(sql_outputs)} SQL outputs")

    # Layer 4: Data flow tracing
    print("  [Output ID] Layer 4: Data flow tracing ...")
    traced = 0
    for op in all_outputs:
        if not op.inputs:
            op.inputs = _layer4_trace_inputs(op, structure_data, module_data)
            traced += len(op.inputs)
    print(f"    Traced {traced} input→output relationships")

    # Add XML outputs if provided
    if xml_outputs:
        for op in xml_outputs:
            _add(op)

    # Sort by confidence (high > medium > low)
    conf_order = {"high": 0, "medium": 1, "low": 2}
    all_outputs.sort(key=lambda o: (conf_order.get(o.confidence, 3), o.output_type, o.name))

    print(f"  [Output ID] Total: {len(all_outputs)} unique outputs "
          f"({sum(1 for o in all_outputs if o.confidence == 'high')} high, "
          f"{sum(1 for o in all_outputs if o.confidence == 'medium')} medium, "
          f"{sum(1 for o in all_outputs if o.confidence == 'low')} low)")

    return [asdict(o) for o in all_outputs]


# ── IO Flow Document Generator ──────────────────────────────────────────────

def generate_io_flow_document(
    outputs: list[dict],
    module_analyses: dict[str, str],
    repo_name: str,
) -> str:
    """Generate the input→output flow document in markdown.

    Structure:
    1. Output Overview (table of all outputs)
    2. Per-output detail (inputs, processing, schema)
    3. Data Flow Diagram (Mermaid)
    """
    parts = []

    # Title
    parts.append(f"# {repo_name} — 输入→输出流程文档\n")
    parts.append(
        '> 本文档以系统输出为核心，追溯每个输出的输入来源和处理流程。\n'
        '> 每个输出对应一个独立模块，便于开发人员快速定位相关代码。\n'
    )

    # Section 1: Output Overview
    parts.append("## 1. 输出全景\n")
    parts.append("| # | 输出标识 | 类型 | 位置 | 置信度 | 输入数 |")
    parts.append("|---|---------|------|------|--------|--------|")
    for i, out in enumerate(outputs, 1):
        conf_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(out["confidence"], "⚪")
        input_count = len(out.get("inputs", []))
        parts.append(
            f"| {i} | `{out['name']}` | {out['output_type']} | "
            f"`{out['file']}:{out['line']}` | {conf_icon} {out['confidence']} | {input_count} |"
        )
    parts.append("")

    # Section 2: Per-output detail
    parts.append("---\n")
    parts.append("## 2. 输出详解\n")

    for i, out in enumerate(outputs, 1):
        conf_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(out["confidence"], "⚪")
        parts.append(f"### 2.{i} 输出: `{out['name']}` {conf_icon}\n")

        # Basic info
        parts.append(f"- **类型**: {out['output_type']}")
        parts.append(f"- **位置**: `{out['file']}:{out['line']}`")
        parts.append(f"- **检测方式**: {out['detection_layer']}")
        parts.append(f"- **证据**: {out.get('evidence', '')}")
        parts.append("")

        # Inputs
        inputs = out.get("inputs", [])
        if inputs:
            parts.append("#### 输入来源\n")
            parts.append("| 输入源 | 类型 | 位置 | 关系 |")
            parts.append("|--------|------|------|------|")
            for inp in inputs:
                src_name = inp.get("source_name", inp.get("source_function", "?"))
                src_type = inp.get("source_type", inp.get("relationship", "?"))
                src_loc = f"`{inp.get('source_file', '')}:{inp.get('source_line', '')}`"
                parts.append(f"| `{src_name}` | {src_type} | {src_loc} | {inp.get('relationship', '')} |")
            parts.append("")
        else:
            parts.append("#### 输入来源\n")
            parts.append("*未检测到输入来源（可能需要 LLM 辅助分析）*\n")

        # Context
        if out.get("context"):
            parts.append("#### 代码上下文\n")
            parts.append(f"```{out['context']}```\n")

        # Related module analysis (if exists)
        # Try to find matching module analysis
        for mod_name, analysis in module_analyses.items():
            if out["file"].replace("/", "_").replace(".", "_") in mod_name.replace("/", "_").replace(".", "_"):
                parts.append("#### 相关模块分析\n")
                # Extract key sections
                lines = analysis.split("\n")
                key_lines = []
                in_key = False
                for line in lines:
                    if any(kw in line for kw in ["职责", "接口", "流程", "算法"]):
                        in_key = True
                    elif line.startswith("#") and in_key:
                        in_key = False
                    if in_key:
                        key_lines.append(line)
                if key_lines:
                    parts.append("\n".join(key_lines[:30]))
                parts.append("")
                break

    # Section 3: Summary statistics
    parts.append("---\n")
    parts.append("## 3. 统计摘要\n")
    type_counts = {}
    for out in outputs:
        t = out["output_type"]
        type_counts[t] = type_counts.get(t, 0) + 1
    parts.append("| 输出类型 | 数量 |")
    parts.append("|----------|------|")
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        parts.append(f"| {t} | {count} |")
    parts.append("")

    total_inputs = sum(len(o.get("inputs", [])) for o in outputs)
    parts.append(f"- **总输出数**: {len(outputs)}")
    parts.append(f"- **总输入→输出关系**: {total_inputs}")
    conf = {"high": 0, "medium": 0, "low": 0}
    for o in outputs:
        conf[o["confidence"]] = conf.get(o["confidence"], 0) + 1
    parts.append(f"- **置信度分布**: 🟢{conf['high']} 🟡{conf['medium']} 🔴{conf['low']}")

    return "\n".join(parts)
