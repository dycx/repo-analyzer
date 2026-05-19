"""Python analyzer for Pandas/Spark-style dataflow."""

from __future__ import annotations

import ast

from output_trace.ir import FactStore, Location, Operation, Sink, Source
from output_trace.sql import analyze_sql
from output_trace.text import compact, first_string, path_format, slug_ref, string_literals, unique


INPUT_METHODS = {
    "read_csv", "read_json", "read_parquet", "read_excel", "read_table",
    "read_sql", "csv", "json", "parquet", "orc", "table", "load",
}
OUTPUT_METHODS = {
    "to_csv", "to_json", "to_parquet", "to_excel", "save", "saveAsTable",
    "insertInto", "csv", "json", "parquet", "orc", "write_text", "write_bytes",
}
TRANSFORM_METHODS = {
    "filter", "where", "select", "selectExpr", "assign", "withColumn",
    "withColumnRenamed", "rename", "join", "merge", "groupBy", "groupby",
    "agg", "aggregate", "drop", "dropDuplicates", "distinct", "sort",
    "orderBy", "union", "map", "flatMap",
}


class PythonAnalyzer(ast.NodeVisitor):
    """AST visitor that extracts output-oriented dataflow facts."""

    def __init__(self, file_path: str, source: str, repo_root: str):
        self.file_path = file_path
        self.source = source
        self.repo_root = repo_root
        self.facts = FactStore(repo_root=repo_root)
        self.scope: list[str] = []
        self.route_stack: list[bool] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        self.route_stack.append(self._has_route_decorator(node))
        self.generic_visit(node)
        self.route_stack.pop()
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_Assign(self, node: ast.Assign) -> None:
        targets = [name for target in node.targets for name in self._target_names(target)]
        if targets:
            self._handle_binding(targets[0], node.value, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        targets = self._target_names(node.target)
        if targets and node.value is not None:
            self._handle_binding(targets[0], node.value, node)
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        if isinstance(node.value, ast.Call):
            self._handle_standalone_call(node.value, node)
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        if node.value is not None and self.route_stack and self.route_stack[-1]:
            name = self.scope[-1] if self.scope else "api_response"
            refs = [self._ref(item) for item in self._loaded_names(node.value) if not self._is_framework(item)]
            self.facts.sinks.append(Sink(
                id=slug_ref("py_api", self.file_path, self._line(node), name),
                name=name,
                kind="api_response",
                format="python",
                depends_on=refs,
                location=self._loc(node),
                evidence="return " + compact(self._expr(node.value)),
            ))
        self.generic_visit(node)

    def _handle_binding(self, target: str, value: ast.AST, node: ast.AST) -> None:
        target_ref = self._ref(target)
        loc = self._loc(node)
        expr = self._expr(value)

        if isinstance(value, ast.Call):
            chain = self._call_chain(value)
            if self._is_input_call(chain, expr):
                literal = first_string(expr, target)
                kind = "table" if chain and chain[-1] in {"table", "read_sql"} else "file"
                if "SELECT " in expr.upper():
                    kind = "query"
                self.facts.sources.append(Source(
                    id=target_ref,
                    name=literal,
                    kind=kind,
                    format=path_format(expr) or (chain[-1] if chain else ""),
                    location=loc,
                    evidence=compact(expr),
                ))
                self._merge_embedded_sql(expr, loc.line, output_ref=target_ref)
                return

            methods = [method for method in chain if method in TRANSFORM_METHODS]
            if methods:
                upstream = self._call_inputs(value, target)
                for index, method in enumerate(methods):
                    self.facts.operations.append(self._operation_from_method(
                        method=method,
                        target_ref=target_ref,
                        upstream=upstream,
                        expr=expr,
                        loc=loc,
                        suffix=f"{target}_{index}_{method}",
                    ))
                return

        if isinstance(value, ast.Subscript):
            base = self._base_name(value.value)
            if base and not self._is_framework(base):
                condition = self._expr(value.slice)
                kind = "filter" if any(token in condition for token in ("==", "!=", ">", "<", "&", "|")) else "select"
                self.facts.operations.append(Operation(
                    id=slug_ref("py_slice", self.file_path, loc.line, target),
                    kind=kind,
                    output=target_ref,
                    inputs=[self._ref(base)],
                    location=loc,
                    evidence=compact(expr),
                    expression=compact(expr),
                    conditions=[condition] if kind == "filter" else [],
                    fields=[] if kind == "filter" else [condition],
                ))
                return

        refs = [self._ref(name) for name in self._loaded_names(value) if name != target and not self._is_framework(name)]
        if refs:
            self.facts.operations.append(Operation(
                id=slug_ref("py_assign", self.file_path, loc.line, target),
                kind="assign",
                output=target_ref,
                inputs=unique(refs),
                location=loc,
                evidence=compact(expr),
                expression=compact(expr),
            ))

    def _handle_standalone_call(self, call: ast.Call, node: ast.AST) -> None:
        chain = self._call_chain(call)
        expr = self._expr(call)
        if not self._is_output_call(chain, expr):
            self._merge_embedded_sql(expr, self._line(node))
            return
        method = chain[-1] if chain else "output"
        base = self._base_name(call.func)
        literal = first_string(expr)
        if literal.lower() in {"utf-8", "utf8"}:
            literal = ""
        output_name = literal or base or method
        sink_kind = "table" if method in {"saveAsTable", "insertInto"} else "file"
        if method in {"publish", "send", "emit"}:
            sink_kind = "message"
        deps = [self._ref(base)] if base and not self._is_framework(base) else [
            self._ref(name) for name in self._loaded_names(call) if not self._is_framework(name)
        ]
        self.facts.sinks.append(Sink(
            id=slug_ref("py_sink", self.file_path, self._line(node), output_name),
            name=output_name,
            kind=sink_kind,
            format=path_format(expr) or method,
            depends_on=unique(deps),
            location=self._loc(node),
            evidence=compact(expr),
        ))

    def _operation_from_method(
        self,
        method: str,
        target_ref: str,
        upstream: list[str],
        expr: str,
        loc: Location,
        suffix: str,
    ) -> Operation:
        fields, conditions, formulas, notes = _method_semantics(method, expr)
        return Operation(
            id=slug_ref("py_op", self.file_path, loc.line, suffix),
            kind=_method_kind(method),
            output=target_ref,
            inputs=upstream,
            location=loc,
            evidence=compact(expr),
            expression=compact(expr),
            fields=fields,
            conditions=conditions,
            formulas=formulas,
            notes=notes,
        )

    def _merge_embedded_sql(self, expr: str, line: int, output_ref: str = "") -> None:
        for literal in _sql_literals(expr):
            sql_facts = analyze_sql(literal, self.file_path, line, self.repo_root)
            if output_ref:
                for operation in sql_facts.operations:
                    operation.output = output_ref
            self.facts.extend(sql_facts)

    def _is_input_call(self, chain: list[str], expr: str) -> bool:
        return any(method in INPUT_METHODS for method in chain) and any(
            marker in expr for marker in ("read", "spark.read", "read_", ".table", "read_sql", ".load")
        )

    def _is_output_call(self, chain: list[str], expr: str) -> bool:
        return any(method in OUTPUT_METHODS for method in chain) and any(
            marker in expr for marker in ("to_", ".write", "write_text", "write_bytes", "saveAsTable", "insertInto")
        )

    def _call_inputs(self, call: ast.Call, target: str) -> list[str]:
        refs = []
        base = self._base_name(call.func)
        if base and not self._is_framework(base):
            refs.append(self._ref(base))
        for name in self._loaded_names(call):
            if name != target and not self._is_framework(name):
                refs.append(self._ref(name))
        return unique(refs)

    def _call_chain(self, call: ast.Call) -> list[str]:
        result: list[str] = []

        def visit_func(node: ast.AST) -> None:
            if isinstance(node, ast.Attribute):
                visit_func(node.value)
                result.append(node.attr)
            elif isinstance(node, ast.Call):
                visit_func(node.func)
            elif isinstance(node, ast.Name):
                result.append(node.id)

        visit_func(call.func)
        return result

    def _base_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return self._base_name(node.value)
        if isinstance(node, ast.Call):
            return self._base_name(node.func)
        return ""

    def _target_names(self, node: ast.AST) -> list[str]:
        if isinstance(node, ast.Name):
            return [node.id]
        if isinstance(node, (ast.Tuple, ast.List)):
            names = []
            for item in node.elts:
                names.extend(self._target_names(item))
            return names
        return []

    def _loaded_names(self, node: ast.AST) -> list[str]:
        return unique([
            child.id for child in ast.walk(node)
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
        ])

    def _has_route_decorator(self, node: ast.FunctionDef) -> bool:
        for decorator in node.decorator_list:
            text = self._expr(decorator).lower()
            if any(marker in text for marker in (".route", ".get(", ".post(", ".put(", ".delete(", "router.")):
                return True
        return False

    def _ref(self, name: str) -> str:
        scope = ".".join(self.scope) if self.scope else "<module>"
        return f"py:{self.file_path}:{scope}:{name}"

    def _expr(self, node: ast.AST) -> str:
        segment = ast.get_source_segment(self.source, node)
        if segment:
            return segment
        try:
            return ast.unparse(node)
        except Exception:
            return type(node).__name__

    def _loc(self, node: ast.AST) -> Location:
        line = self._line(node)
        return Location(file=self.file_path, line=line, end_line=getattr(node, "end_lineno", line))

    @staticmethod
    def _line(node: ast.AST) -> int:
        return int(getattr(node, "lineno", 1))

    @staticmethod
    def _is_framework(name: str) -> bool:
        return name in {"pd", "pandas", "spark", "sqlContext", "hiveContext", "F", "Path", "os", "sys", "json", "re"}


def analyze_python(path: str, rel_path: str, repo_root: str) -> FactStore:
    with open(path, encoding="utf-8", errors="ignore") as handle:
        source = handle.read()
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError as exc:
        facts = FactStore(repo_root=repo_root)
        facts.warnings.append(f"Python parse failed for {rel_path}: {exc}")
        return facts
    analyzer = PythonAnalyzer(rel_path, source, repo_root)
    analyzer.visit(tree)
    return analyzer.facts


def _method_kind(method: str) -> str:
    return {
        "where": "filter",
        "filter": "filter",
        "select": "select",
        "selectExpr": "select",
        "withColumn": "derive",
        "assign": "derive",
        "withColumnRenamed": "rename",
        "rename": "rename",
        "join": "join",
        "merge": "join",
        "groupBy": "group",
        "groupby": "group",
        "agg": "aggregate",
        "aggregate": "aggregate",
        "dropDuplicates": "dedupe",
        "distinct": "dedupe",
        "sort": "sort",
        "orderBy": "sort",
    }.get(method, "transform")


def _method_semantics(method: str, expr: str) -> tuple[list[str], list[str], list[str], list[str]]:
    args = _call_args(expr, method) or expr
    strings = string_literals(args)
    fields: list[str] = []
    conditions: list[str] = []
    formulas: list[str] = []
    notes: list[str] = []
    if method in {"filter", "where"}:
        conditions.append(args)
    elif method in {"select", "selectExpr"}:
        fields.extend(strings)
        if method == "selectExpr":
            formulas.extend(strings)
    elif method in {"withColumn", "assign"}:
        if strings:
            fields.append(strings[0])
        formulas.append(args)
    elif method in {"groupBy", "groupby"}:
        fields.extend(strings)
        notes.append("grouping keys define aggregation grain")
    elif method in {"agg", "aggregate"}:
        fields.extend(strings)
        formulas.append(args)
        fields.extend(_named_agg_outputs(args))
    elif method in {"join", "merge"}:
        formulas.append(args)
        fields.extend(strings)
    return unique(fields), unique(conditions), unique(formulas), unique(notes)


def _call_args(expr: str, method: str) -> str:
    marker = f".{method}("
    start = expr.find(marker)
    if start < 0:
        marker = f"{method}("
        start = expr.find(marker)
        if start < 0:
            return ""
    index = start + len(marker)
    depth = 0
    quote = ""
    chars: list[str] = []
    for char in expr[index:]:
        if quote:
            chars.append(char)
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            chars.append(char)
        elif char == "(":
            depth += 1
            chars.append(char)
        elif char == ")":
            if depth == 0:
                break
            depth -= 1
            chars.append(char)
        else:
            chars.append(char)
    return compact("".join(chars), 500)


def _named_agg_outputs(args: str) -> list[str]:
    import re

    return re.findall(r"\b([A-Za-z_]\w*)\s*=\s*\(", args)


def _sql_literals(expr: str) -> list[str]:
    values = []
    for literal in string_literals(expr):
        upper = literal.upper()
        if any(keyword in upper for keyword in ("SELECT ", "INSERT ", "CREATE TABLE", "MERGE INTO")):
            values.append(literal)
    return values

