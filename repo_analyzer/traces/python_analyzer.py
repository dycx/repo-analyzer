"""Python AST-based dataflow fact extraction."""

from __future__ import annotations

import ast
import os
from pathlib import Path

from repo_analyzer.traces.models import (
    AnalysisFacts,
    CodeLocation,
    InputSource,
    OutputSink,
    TransformStep,
)
from repo_analyzer.traces.patterns import (
    classify_path_format,
    first_string_literal,
    safe_ref,
    summarize_expression,
    unique_preserve_order,
)
from repo_analyzer.traces.semantics import (
    INPUT_METHODS,
    OUTPUT_METHODS,
    TRANSFORM_METHODS,
    infer_transform_semantics,
    method_to_step_type,
)
from repo_analyzer.traces.sql_analyzer import analyze_sql_text


def analyze_python_file(path: str, repo_root: str) -> AnalysisFacts:
    with open(path, encoding="utf-8", errors="ignore") as f:
        source = f.read()
    rel = os.path.relpath(path, repo_root)
    facts = AnalysisFacts(repo_path=repo_root)
    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError as exc:
        facts.warnings.append(f"Could not parse Python file {rel}: {exc}")
        return facts

    visitor = _PythonTraceVisitor(rel, source, repo_root, facts)
    visitor.visit(tree)
    return facts


class _PythonTraceVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str, source: str, repo_root: str, facts: AnalysisFacts):
        self.file_path = file_path
        self.source = source
        self.repo_root = repo_root
        self.facts = facts
        self.function_stack: list[str] = []
        self.api_handler_stack: list[bool] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node.name)
        self.api_handler_stack.append(self._has_route_decorator(node))
        self.generic_visit(node)
        self.api_handler_stack.pop()
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_Assign(self, node: ast.Assign) -> None:
        targets = [name for target in node.targets for name in self._target_names(target)]
        self._handle_binding(targets, node.value, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._handle_binding(self._target_names(node.target), node.value, node)
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        if isinstance(node.value, ast.Call):
            self._handle_call_expression(node.value, node)
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        if node.value is not None and self._looks_like_api_handler():
            expr = self._expr_text(node.value)
            refs = [self._ref(name) for name in self._loaded_names(node.value) if not self._is_framework_name(name)]
            loc = self._loc(node)
            name = self.function_stack[-1] if self.function_stack else "api_response"
            self.facts.outputs.append(OutputSink(
                name=name,
                sink_type="api_response",
                input_refs=refs,
                location=loc,
                evidence=f"return {summarize_expression(expr)}",
                format="python",
            ))
        self.generic_visit(node)

    def _handle_binding(self, targets: list[str], value: ast.AST, node: ast.AST) -> None:
        if not targets:
            return
        target = targets[0]
        target_ref = self._ref(target)
        if isinstance(value, ast.Call):
            call_info = self._call_info(value)
            method = call_info[-1] if call_info else ""
            expr = self._expr_text(value)
            loc = self._loc(node)

            if self._is_input_call(call_info, expr):
                name = first_string_literal(expr, fallback=target)
                source_type = "table" if method in {"table", "read_sql"} else "file"
                if "sql" in method.lower() or "SELECT" in expr.upper():
                    source_type = "query"
                self.facts.inputs.append(InputSource(
                    name=name,
                    source_type=source_type,
                    ref=target_ref,
                    location=loc,
                    evidence=summarize_expression(expr),
                    format=classify_path_format(expr) or method,
                ))
                if "SELECT" in expr.upper():
                    self._extract_embedded_sql(expr, loc.line, output_ref=target_ref)
                return

            transform_methods = [m for m in call_info if m in TRANSFORM_METHODS]
            if transform_methods:
                input_refs = self._input_refs_for_call(value, target)
                for index, transform_method in enumerate(transform_methods):
                    fields, conditions, formulas, notes = infer_transform_semantics(transform_method, expr)
                    self.facts.steps.append(TransformStep(
                        step_id=safe_ref("py_step", self.file_path, loc.line, f"{target}_{index}_{transform_method}"),
                        step_type=method_to_step_type(transform_method),
                        input_refs=input_refs,
                        output_ref=target_ref,
                        expression=summarize_expression(expr),
                        location=loc,
                        evidence=summarize_expression(expr),
                        fields=fields,
                        conditions=conditions,
                        formulas=formulas,
                        notes=notes,
                    ))
                return

        if isinstance(value, ast.Subscript):
            base = self._base_name(value.value)
            if base and not self._is_framework_name(base):
                loc = self._loc(node)
                expr = self._expr_text(value)
                condition = self._expr_text(value.slice)
                step_type = "filter" if any(op in condition for op in ("==", "!=", ">", "<", "&", "|")) else "select"
                self.facts.steps.append(TransformStep(
                    step_id=safe_ref("py_subscript", self.file_path, loc.line, target),
                    step_type=step_type,
                    input_refs=[self._ref(base)],
                    output_ref=target_ref,
                    expression=summarize_expression(expr),
                    location=loc,
                    evidence=summarize_expression(expr),
                    conditions=[condition] if step_type == "filter" else [],
                    fields=[] if step_type == "filter" else [condition],
                ))
                return

        refs = self._loaded_names(value)
        if refs:
            loc = self._loc(node)
            expr = self._expr_text(value)
            self.facts.steps.append(TransformStep(
                step_id=safe_ref("py_assign", self.file_path, loc.line, target),
                step_type="assign",
                input_refs=[self._ref(r) for r in refs if r != target and not self._is_framework_name(r)],
                output_ref=target_ref,
                expression=summarize_expression(expr),
                location=loc,
                evidence=summarize_expression(expr),
            ))

    def _handle_call_expression(self, call: ast.Call, node: ast.AST) -> None:
        call_info = self._call_info(call)
        method = call_info[-1] if call_info else ""
        expr = self._expr_text(call)
        if self._is_output_call(call_info, expr):
            loc = self._loc(node)
            base = self._base_name(call.func) or ""
            input_refs = [self._ref(base)] if base and not self._is_framework_name(base) else [
                self._ref(name) for name in self._loaded_names(call) if not self._is_framework_name(name)
            ]
            literal_name = first_string_literal(expr, fallback="")
            if literal_name.lower() in {"utf-8", "utf8"}:
                literal_name = ""
            name = literal_name or base or method or "output"
            sink_type = "table" if method in {"saveAsTable", "insertInto"} else "file"
            if method in {"publish", "send", "emit"}:
                sink_type = "message"
            self.facts.outputs.append(OutputSink(
                name=name,
                sink_type=sink_type,
                input_refs=unique_preserve_order(input_refs),
                location=loc,
                evidence=summarize_expression(expr),
                format=classify_path_format(expr) or method,
            ))
        elif "sql" in call_info and "SELECT" in expr.upper():
            loc = self._loc(node)
            self._extract_embedded_sql(expr, loc.line)

    def _extract_embedded_sql(self, expr: str, line: int, output_ref: str = "") -> None:
        literals = [value for value in self._string_literals_from_expr(expr) if _looks_like_sql(value)]
        for sql in literals:
            sql_facts = analyze_sql_text(
                sql,
                self.file_path,
                line,
                self.repo_root,
                ref_prefix="py_sql",
                step_type="sql",
            )
            if output_ref:
                for step in sql_facts.steps:
                    step.output_ref = output_ref
            self.facts.merge(sql_facts)

    def _is_input_call(self, call_info: list[str], expr: str) -> bool:
        if any(method in INPUT_METHODS for method in call_info):
            if any(marker in expr for marker in ("read", "spark.read", "read_", ".table", "read_sql")):
                return True
        return "open(" in expr and any(mode in expr for mode in ("'r'", '"r"', "'rb'", '"rb"'))

    def _is_output_call(self, call_info: list[str], expr: str) -> bool:
        if any(method in OUTPUT_METHODS for method in call_info):
            if any(marker in expr for marker in ("to_", ".write", "write_text", "write_bytes", "saveAsTable", "insertInto")):
                return True
        return "open(" in expr and any(mode in expr for mode in ("'w'", '"w"', "'a'", '"a"', "'wb'", '"wb"'))

    def _call_info(self, call: ast.Call) -> list[str]:
        names: list[str] = []
        node: ast.AST | None = call.func
        while isinstance(node, ast.Attribute):
            names.append(node.attr)
            node = node.value
            if isinstance(node, ast.Call):
                nested = self._call_info(node)
                names.extend(reversed(nested))
                break
        if isinstance(node, ast.Name):
            names.append(node.id)
        return list(reversed(names))

    def _input_refs_for_call(self, call: ast.Call, target: str) -> list[str]:
        base = self._base_name(call.func)
        refs = self._loaded_names(call)
        if base:
            refs.insert(0, base)
        return unique_preserve_order([
            self._ref(r) for r in refs
            if r != target and not self._is_framework_name(r)
        ])

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
            names: list[str] = []
            for elt in node.elts:
                names.extend(self._target_names(elt))
            return names
        return []

    def _loaded_names(self, node: ast.AST) -> list[str]:
        names: list[str] = []
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                names.append(child.id)
        return unique_preserve_order(names)

    def _string_literals_from_expr(self, expr: str) -> list[str]:
        try:
            parsed = ast.parse(expr)
        except SyntaxError:
            return []
        result: list[str] = []
        for node in ast.walk(parsed):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                result.append(node.value)
        return result

    def _expr_text(self, node: ast.AST) -> str:
        segment = ast.get_source_segment(self.source, node)
        if segment:
            return segment
        try:
            return ast.unparse(node)
        except Exception:
            return type(node).__name__

    def _loc(self, node: ast.AST) -> CodeLocation:
        line = getattr(node, "lineno", 1)
        end_line = getattr(node, "end_lineno", line)
        return CodeLocation(file=self.file_path, line=line, end_line=end_line)

    def _looks_like_api_handler(self) -> bool:
        return bool(self.api_handler_stack and self.api_handler_stack[-1])

    def _has_route_decorator(self, node: ast.FunctionDef) -> bool:
        for deco in node.decorator_list:
            text = self._expr_text(deco)
            lowered = text.lower()
            if any(marker in lowered for marker in (
                ".route", ".get(", ".post(", ".put(", ".delete(", "router.",
            )):
                return True
        return False

    def _ref(self, name: str) -> str:
        if not name:
            return ""
        if name.startswith("table:") or self._is_framework_name(name):
            return name
        scope = ".".join(self.function_stack) if self.function_stack else "<module>"
        return f"py:{self.file_path}:{scope}:{name}"

    @staticmethod
    def _is_framework_name(name: str) -> bool:
        return name in {
            "pd", "pandas", "spark", "sqlContext", "hiveContext", "F",
            "Path", "os", "sys", "json", "re", "ET",
        }


def _looks_like_sql(text: str) -> bool:
    upper = text.upper()
    return any(keyword in upper for keyword in ("SELECT ", "INSERT ", "CREATE TABLE", "MERGE INTO"))
