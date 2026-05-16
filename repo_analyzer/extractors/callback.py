"""C function pointer / callback pattern detection.

Detects function pointer patterns in C source code using regex (not tree-sitter):
1. Function pointer fields in structs
2. Callback registrations (var.field = func)
3. Indirect calls ((*func_ptr)(args) or func_ptr(args))
4. Dispatch tables grouping related function pointers
5. Enhanced call graph with indirect edges

This module works on raw source text and file metadata dicts, complementing
the tree-sitter based extractors.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field


# ── Regex patterns ───────────────────────────────────────────────────────────

# Pattern: type (*field_name)(params);
_FP_FIELD_RE = re.compile(
    r'(\w[\w\s\*]*?)\s*\(\s*\*\s*(\w+)\s*\)\s*\(([^)]*)\)\s*;'
)

# Pattern: struct_var->field = func_name;  or  struct_var.field = func_name;
_ASSIGN_FP_RE = re.compile(
    r'(\w+(?:->|\.)\w+)\s*=\s*(&?\s*\w+)\s*;'
)

# Pattern: (*struct_var->field)(args)  or  struct_var->field(args)
_CALL_FP_RE = re.compile(
    r'(?:\(\s*\*\s*)?(\w+(?:->|\.)+[\w>]+)(?:\s*\)?)\s*\('
)

# Pattern: typedef struct { ... } name;
_STRUCT_TYPEDEF_RE = re.compile(
    r'typedef\s+struct\s*(?:\w+)?\s*\{([^}]+)\}\s*(\w+)\s*;'
)

# Pattern: struct name { ... };
_STRUCT_RE = re.compile(
    r'struct\s+(\w+)\s*\{([^}]+)\}'
)

# Common function pointer field names (used as heuristics for indirect calls)
_FP_FIELD_NAMES = frozenset({
    "handler", "callback", "process", "execute", "dispatch",
    "init", "destroy", "read", "write", "open", "close",
    "connect", "send", "recv", "on_event", "on_error",
    "create", "free", "alloc", "copy", "compare", "hash",
    "filter", "checker", "resolver", "accept", "listen",
    "preconfiguration", "postconfiguration",
    "init_main_conf", "init_server_conf", "init_location_conf",
    "merge", "content_handler", "input_filter", "output_filter",
})

# Suffixes that strongly indicate function pointer fields
_FP_SUFFIXES = ("_handler", "_cb", "_callback", "_func", "_fn", "_hook")


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class FuncPointerField:
    """A function pointer field found in a C struct."""
    struct_name: str
    field_name: str
    return_type: str
    param_types: list[str]
    file: str
    line: int


@dataclass
class CallbackRegistration:
    """An assignment to a function pointer field."""
    struct_var: str
    field_name: str
    assigned_func: str
    file: str
    line: int
    inferred_type: str = ""


@dataclass
class IndirectCall:
    """A call through a function pointer."""
    expression: str
    field_name: str
    file: str
    line: int


@dataclass
class DispatchTable:
    """A struct that acts as a vtable-like dispatch table."""
    struct_name: str
    fields: list[FuncPointerField] = field(default_factory=list)
    registrations: list[CallbackRegistration] = field(default_factory=list)


# ── Extraction functions ─────────────────────────────────────────────────────

def _extract_func_pointers(source: str, filepath: str) -> list[FuncPointerField]:
    """Extract function pointer fields from C struct definitions."""
    results: list[FuncPointerField] = []

    def _process_struct(struct_name: str, body: str, base_line: int) -> None:
        for fm in _FP_FIELD_RE.finditer(body):
            ret_type = fm.group(1).strip()
            field_name = fm.group(2).strip()
            params_raw = fm.group(3).strip()
            param_types = [
                p.strip().split()[-1] for p in params_raw.split(",") if p.strip()
            ]
            line = base_line + body[:fm.start()].count("\n")
            results.append(FuncPointerField(
                struct_name=struct_name,
                field_name=field_name,
                return_type=ret_type,
                param_types=param_types,
                file=filepath,
                line=line,
            ))

    # typedef struct { ... } name;
    for m in _STRUCT_TYPEDEF_RE.finditer(source):
        _process_struct(m.group(2), m.group(1), source[:m.start()].count("\n") + 1)

    # struct name { ... };
    for m in _STRUCT_RE.finditer(source):
        _process_struct(m.group(1), m.group(2), source[:m.start()].count("\n") + 1)

    return results


def _extract_callback_registrations(source: str, filepath: str) -> list[CallbackRegistration]:
    """Find assignments like: module->postconfiguration = func_name;"""
    results: list[CallbackRegistration] = []

    for m in _ASSIGN_FP_RE.finditer(source):
        expr = m.group(1)
        func = m.group(2).strip().lstrip("&").strip()
        line = source[:m.start()].count("\n") + 1

        # Split into var->field or var.field
        if "->" in expr:
            var_name, field_name = expr.split("->", 1)
        elif "." in expr:
            var_name, field_name = expr.split(".", 1)
        else:
            continue

        # Skip non-function assignments (literals, NULL, numbers)
        if not func or func.startswith('"') or func.isdigit() or func == "NULL":
            continue

        results.append(CallbackRegistration(
            struct_var=var_name,
            field_name=field_name,
            assigned_func=func,
            file=filepath,
            line=line,
        ))

    return results


def _extract_indirect_calls(source: str, filepath: str) -> list[IndirectCall]:
    """Find calls like: c->read->handler(ev) or (*module->init)(cf)."""
    results: list[IndirectCall] = []

    for m in _CALL_FP_RE.finditer(source):
        expr = m.group(1)
        line = source[:m.start()].count("\n") + 1

        # Must contain -> or . to be a field access
        if "->" not in expr and "." not in expr:
            continue

        # Extract the field name (last component)
        parts = expr.replace("->", ".").split(".")
        field_name = parts[-1]

        # Heuristic: check if it looks like a function pointer
        if (field_name in _FP_FIELD_NAMES
                or any(field_name.endswith(s) for s in _FP_SUFFIXES)):
            results.append(IndirectCall(
                expression=expr,
                field_name=field_name,
                file=filepath,
                line=line,
            ))

    return results


def _build_dispatch_tables(
    func_ptrs: list[FuncPointerField],
    registrations: list[CallbackRegistration],
) -> list[DispatchTable]:
    """Group function pointer fields into dispatch tables (vtable-like structs)."""
    tables: dict[str, DispatchTable] = {}

    for fp in func_ptrs:
        if fp.struct_name not in tables:
            tables[fp.struct_name] = DispatchTable(struct_name=fp.struct_name)
        tables[fp.struct_name].fields.append(fp)

    # Match registrations to tables by field name
    for reg in registrations:
        for tname, table in tables.items():
            for fp in table.fields:
                if fp.field_name == reg.field_name:
                    reg.inferred_type = tname
                    table.registrations.append(reg)
                    break

    return list(tables.values())


# ── Public API ───────────────────────────────────────────────────────────────

def detect_function_pointers(files: list[dict]) -> list[dict]:
    """Find function pointer fields in structs across all C files.

    Args:
        files: List of file analysis dicts with keys 'path', 'language',
               and optionally 'source' (raw source text).

    Returns:
        List of dicts describing function pointer fields.
    """
    results: list[dict] = []
    for fa in files:
        if fa.get("language") not in ("C", "C++"):
            continue
        filepath = fa.get("path", "")
        source = fa.get("source", "")
        if not source:
            continue

        for fp in _extract_func_pointers(source, filepath):
            results.append({
                "struct": fp.struct_name,
                "field": fp.field_name,
                "return_type": fp.return_type,
                "param_types": fp.param_types,
                "file": fp.file,
                "line": fp.line,
            })

    return results


def detect_callback_registrations(files: list[dict]) -> list[dict]:
    """Find var.field = func patterns across all C files.

    Args:
        files: List of file analysis dicts with keys 'path', 'language',
               and optionally 'source' (raw source text).

    Returns:
        List of dicts describing callback registrations.
    """
    results: list[dict] = []
    for fa in files:
        if fa.get("language") not in ("C", "C++"):
            continue
        filepath = fa.get("path", "")
        source = fa.get("source", "")
        if not source:
            continue

        for reg in _extract_callback_registrations(source, filepath):
            results.append({
                "var": reg.struct_var,
                "field": reg.field_name,
                "func": reg.assigned_func,
                "file": reg.file,
                "line": reg.line,
                "inferred_type": reg.inferred_type,
            })

    return results


def detect_indirect_calls(files: list[dict]) -> list[dict]:
    """Find (*func_ptr)(args) or func_ptr(args) patterns in C files.

    Args:
        files: List of file analysis dicts with keys 'path', 'language',
               and optionally 'source' (raw source text).

    Returns:
        List of dicts describing indirect calls.
    """
    results: list[dict] = []
    for fa in files:
        if fa.get("language") not in ("C", "C++"):
            continue
        filepath = fa.get("path", "")
        source = fa.get("source", "")
        if not source:
            continue

        for ic in _extract_indirect_calls(source, filepath):
            results.append({
                "expression": ic.expression,
                "field": ic.field_name,
                "file": ic.file,
                "line": ic.line,
            })

    return results


def build_dispatch_tables(
    func_ptrs: list[dict],
    registrations: list[dict],
) -> list[dict]:
    """Group function pointer fields by struct to form dispatch tables.

    Args:
        func_ptrs: List of function pointer field dicts.
        registrations: List of callback registration dicts.

    Returns:
        List of dispatch table dicts with struct name, fields, and registrations.
    """
    fp_objs = [
        FuncPointerField(
            struct_name=fp.get("struct", fp.get("struct_name", "")),
            field_name=fp.get("field", fp.get("field_name", "")),
            return_type=fp.get("return_type", ""),
            param_types=fp.get("param_types", []),
            file=fp.get("file", ""),
            line=fp.get("line", 0),
        )
        for fp in func_ptrs
    ]
    reg_objs = [
        CallbackRegistration(
            struct_var=r.get("var", r.get("struct_var", "")),
            field_name=r.get("field", r.get("field_name", "")),
            assigned_func=r.get("func", r.get("assigned_func", "")),
            file=r.get("file", ""),
            line=r.get("line", 0),
            inferred_type=r.get("inferred_type", ""),
        )
        for r in registrations
    ]

    tables = _build_dispatch_tables(fp_objs, reg_objs)

    return [
        {
            "struct": t.struct_name,
            "fields": [
                {"name": f.field_name, "type": f.return_type}
                for f in t.fields
            ],
            "registered_callbacks": [
                {"field": r.field_name, "func": r.assigned_func}
                for r in t.registrations
            ],
        }
        for t in tables
        if len(t.fields) >= 2  # Only tables with 2+ function pointers
    ]


def enhance_call_graph(files: list[dict], repo_path: str) -> dict:
    """Main entry point: enhance the call graph with indirect call information.

    Scans C/C++ source files for function pointer patterns and returns a
    comprehensive analysis of callback-based control flow.

    Args:
        files: List of file analysis dicts. Each should have 'path' (relative)
               and 'language' keys. If 'source' is not present, the file will
               be read from disk using repo_path + path.
        repo_path: Absolute path to the repository root.

    Returns:
        Dict with keys:
        - func_pointer_fields: function pointer struct fields found
        - callback_registrations: assignments to function pointer fields
        - indirect_calls: calls through function pointers
        - dispatch_tables: grouped function pointer structs (vtables)
        - enhanced_call_edges: additional call edges (source -> target)
        - summary: counts of all detected patterns
    """
    all_func_ptrs: list[FuncPointerField] = []
    all_registrations: list[CallbackRegistration] = []
    all_indirect_calls: list[IndirectCall] = []

    for fa in files:
        if fa.get("language") not in ("C", "C++"):
            continue

        filepath = fa.get("path", "")
        source = fa.get("source", "")

        # Read source from disk if not provided in the dict
        if not source:
            full_path = os.path.join(repo_path, filepath)
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    source = f.read()
            except (OSError, UnicodeDecodeError):
                continue

        all_func_ptrs.extend(_extract_func_pointers(source, filepath))
        all_registrations.extend(_extract_callback_registrations(source, filepath))
        all_indirect_calls.extend(_extract_indirect_calls(source, filepath))

    # Build dispatch tables
    tables = _build_dispatch_tables(all_func_ptrs, all_registrations)

    # Build enhanced call edges: for each indirect call, find matching registrations
    enhanced_edges: list[dict] = []
    reg_by_field: dict[str, list[CallbackRegistration]] = defaultdict(list)
    for reg in all_registrations:
        reg_by_field[reg.field_name].append(reg)

    for ic in all_indirect_calls:
        matching_regs = reg_by_field.get(ic.field_name, [])
        for reg in matching_regs:
            enhanced_edges.append({
                "caller": ic.expression,
                "callee": reg.assigned_func,
                "type": "indirect",
                "field": ic.field_name,
                "file": ic.file,
                "line": ic.line,
            })

    return {
        "func_pointer_fields": [
            {
                "struct": fp.struct_name,
                "field": fp.field_name,
                "return_type": fp.return_type,
                "file": fp.file,
                "line": fp.line,
            }
            for fp in all_func_ptrs
        ],
        "callback_registrations": [
            {
                "var": r.struct_var,
                "field": r.field_name,
                "func": r.assigned_func,
                "file": r.file,
                "line": r.line,
                "inferred_type": r.inferred_type,
            }
            for r in all_registrations
        ],
        "indirect_calls": [
            {
                "expression": ic.expression,
                "field": ic.field_name,
                "file": ic.file,
                "line": ic.line,
            }
            for ic in all_indirect_calls
        ],
        "dispatch_tables": [
            {
                "struct": t.struct_name,
                "fields": [
                    {"name": f.field_name, "type": f.return_type}
                    for f in t.fields
                ],
                "registered_callbacks": [
                    {"field": r.field_name, "func": r.assigned_func}
                    for r in t.registrations
                ],
            }
            for t in tables
            if len(t.fields) >= 2
        ],
        "enhanced_call_edges": enhanced_edges,
        "summary": {
            "func_pointer_fields": len(all_func_ptrs),
            "callback_registrations": len(all_registrations),
            "indirect_calls": len(all_indirect_calls),
            "dispatch_tables": len([t for t in tables if len(t.fields) >= 2]),
            "enhanced_edges": len(enhanced_edges),
        },
    }
