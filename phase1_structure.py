"""Phase 1: Structure Extraction via tree-sitter.

Parses source files into ASTs and extracts:
- Symbol definitions (functions, classes, methods, variables)
- Function signatures (parameters, return types)
- Import/include relationships
- Function call relationships (caller → callee)
- SQL statements embedded in code

All extraction is deterministic (no LLM involved).
"""

import json
import os
import re
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any

import tree_sitter_c as tsc
import tree_sitter_cpp as tscpp
import tree_sitter_java as tsjava
import tree_sitter_python as tspython
import tree_sitter_scala as tsscala
import tree_sitter_sql as tssql
import tree_sitter_xml as tsxml
from tree_sitter import Language, Parser

# ── Language setup ───────────────────────────────────────────────────────────

LANGUAGES = {
    "C": Language(tsc.language()),
    "C++": Language(tscpp.language()),
    "Java": Language(tsjava.language()),
    "Python": Language(tspython.language()),
    "Scala": Language(tsscala.language()),
    "SQL": Language(tssql.language()),
    "XML": Language(tsxml.language_xml()),
}

EXT_TO_LANG = {
    ".c": "C", ".h": "C",
    ".cc": "C++", ".cpp": "C++", ".cxx": "C++", ".hpp": "C++", ".hxx": "C++",
    ".java": "Java",
    ".scala": "Scala", ".sc": "Scala",
    ".py": "Python",
    ".sql": "SQL",
    ".xml": "XML", ".xsd": "XML", ".xsl": "XML", ".xslt": "XML",
}

SKIP_DIRS = {
    ".git", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", "target", ".gradle", ".idea", ".vscode", "vendor",
    "third_party", "external", "deps", ".cache",
}

# ── Test file detection ─────────────────────────────────────────────────────

# Directory names that indicate test code
TEST_DIRS = {
    "test", "tests", "testing", "__tests__", "spec", "specs",
    "test_fixtures", "testdata", "test_data", "test-resources",
    "src/test", "src/tests",
}

# File name patterns (regex) that indicate test files
_TEST_FILE_PATTERNS = [
    # Python: pytest / unittest
    re.compile(r'^test_\w+\.py$'),
    re.compile(r'^\w+_test\.py$'),
    re.compile(r'^tests?\.py$'),
    # Java / Scala: JUnit / TestNG / ScalaTest
    re.compile(r'^\w+Test\.java$'),
    re.compile(r'^\w+Tests\.java$'),
    re.compile(r'^\w+Spec\.scala$'),
    re.compile(r'^\w+Test\.scala$'),
    re.compile(r'^\w+Suite\.scala$'),
    # JavaScript / TypeScript: Jest / Mocha / Vitest
    re.compile(r'^\w+\.test\.(js|ts|jsx|tsx)$'),
    re.compile(r'^\w+\.spec\.(js|ts|jsx|tsx)$'),
    re.compile(r'^\w+[-_]test\.(js|ts)$'),
    # Go
    re.compile(r'^\w+_test\.go$'),
    # Rust
    re.compile(r'^test_\w+\.rs$'),
    # C / C++: Google Test / Catch2
    re.compile(r'^\w+_test\.(c|cpp|cc|cxx)$'),
    re.compile(r'^\w+_tests\.(c|cpp|cc|cxx)$'),
    re.compile(r'^test_\w+\.(c|cpp|cc|cxx)$'),
    # Ruby: RSpec / Minitest
    re.compile(r'^\w+_spec\.rb$'),
    re.compile(r'^\w+_test\.rb$'),
    # PHP: PHPUnit
    re.compile(r'^\w+Test\.php$'),
]

# File extensions commonly used for test files
_TEST_EXTENSIONS = {
    ".test.js", ".test.ts", ".test.jsx", ".test.tsx",
    ".spec.js", ".spec.ts", ".spec.jsx", ".spec.tsx",
    ".test.py", ".spec.py",
}

# Inline markers in source code that indicate test code
_TEST_CODE_MARKERS = {
    "python": ["import unittest", "import pytest", "from unittest", "from pytest",
               "@pytest.fixture", "@pytest.mark", "def test_", "class Test"],
    "java": ["@Test", "@BeforeEach", "@AfterEach", "@BeforeAll", "@AfterAll",
             "import org.junit", "import org.testng", "import static org.junit"],
    "scala": ["import org.scalatest", "import org.specs2",
              "class.*Spec.*extends", "class.*Suite.*extends"],
    "javascript": ["describe(", "it(", "test(", "expect(",
                   "import.*from.*jest", "import.*from.*vitest"],
    "go": ['import.*testing"', "func Test"],
    "rust": ["#[test]", "#[cfg(test)]"],
    "ruby": ["require.*rspec", "describe.*do", "RSpec.describe"],
}


def is_test_file(filepath: str, content: str = None) -> bool:
    """Detect if a file is a test file based on path, name, and optionally content.

    Uses multiple signals:
    1. Directory path contains a test directory name
    2. File name matches test patterns
    3. File extension matches test extensions
    4. Content contains test framework markers (if content provided)
    """
    # Normalize path separators
    normalized = filepath.replace("\\", "/")
    parts = normalized.split("/")
    fname = parts[-1] if parts else filepath

    # Check if inside a test directory
    for part in parts[:-1]:
        if part.lower() in TEST_DIRS:
            return True

    # Check file name patterns
    for pattern in _TEST_FILE_PATTERNS:
        if pattern.match(fname):
            return True

    # Check file extensions
    ext_lower = fname[fname.rfind("."):] if "." in fname else ""
    if ext_lower in _TEST_EXTENSIONS:
        return True

    # Check content markers
    if content:
        content_lower = content.lower()[:5000]  # only check first 5KB
        for lang_markers in _TEST_CODE_MARKERS.values():
            for marker in lang_markers:
                if marker.lower() in content_lower:
                    return True

    return False


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class Symbol:
    name: str
    kind: str  # function, class, method, variable, interface, enum, struct
    file: str
    line: int
    end_line: int
    signature: str = ""
    return_type: str = ""
    params: list[dict] = field(default_factory=list)
    docstring: str = ""
    parent: str = ""  # enclosing class/namespace
    visibility: str = ""  # public/private/protected
    is_static: bool = False
    is_abstract: bool = False


@dataclass
class Import:
    source: str  # what is imported
    file: str
    line: int
    module: str = ""  # from which module


@dataclass
class CallEdge:
    caller: str  # qualified name
    callee: str
    file: str
    line: int


@dataclass
class FileAnalysis:
    path: str
    language: str
    symbols: list[dict] = field(default_factory=list)
    imports: list[dict] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    sql_stmts: list[dict] = field(default_factory=list)
    spark_cross_ref: list[dict] = field(default_factory=list)
    error: str = ""


# ── Per-language extractors ──────────────────────────────────────────────────

def _node_text(node, source: bytes) -> str:
    """Get the text of a tree-sitter node."""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _extract_python(tree, source: bytes, filepath: str) -> tuple[list[Symbol], list[Import], list[CallEdge]]:
    """Extract symbols, imports, and calls from Python AST."""
    symbols = []
    imports = []
    calls = []
    root = tree.root_node

    def _walk(node, parent_name=""):
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            params_node = node.child_by_field_name("parameters")
            ret_node = node.child_by_field_name("return_type")
            if name_node:
                name = _node_text(name_node, source)
                qual = f"{parent_name}.{name}" if parent_name else name
                sig = _node_text(node, source).split("\n")[0]
                params = _extract_python_params(params_node, source) if params_node else []
                ret = _node_text(ret_node, source) if ret_node else ""
                # Extract docstring
                docstring = _extract_python_docstring(node, source)
                symbols.append(Symbol(
                    name=name, kind="method" if parent_name else "function",
                    file=filepath, line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1, signature=sig,
                    return_type=ret, params=params, docstring=docstring,
                    parent=parent_name,
                ))
                # Walk body for nested defs and calls
                for child in node.children:
                    _walk(child, qual)
                return  # already walked children

        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                qual = f"{parent_name}.{name}" if parent_name else name
                # Get base classes
                bases = []
                for child in node.children:
                    if child.type == "argument_list":
                        for arg in child.children:
                            if arg.type == "identifier":
                                bases.append(_node_text(arg, source))
                sig = f"class {name}" + (f"({', '.join(bases)})" if bases else "")
                docstring = _extract_python_docstring(node, source)
                symbols.append(Symbol(
                    name=name, kind="class", file=filepath,
                    line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                    signature=sig, docstring=docstring, parent=parent_name,
                ))
                for child in node.children:
                    _walk(child, qual)
                return

        elif node.type == "import_statement":
            for child in node.children:
                if child.type == "dotted_name":
                    imports.append(Import(
                        source=_node_text(child, source), file=filepath,
                        line=node.start_point[0] + 1,
                    ))

        elif node.type == "import_from_statement":
            module = ""
            names = []
            for child in node.children:
                if child.type == "dotted_name" and not module:
                    module = _node_text(child, source)
                elif child.type == "dotted_name":
                    names.append(_node_text(child, source))
                elif child.type == "wildcard_import":
                    names.append("*")
            for n in names or ["*"]:
                imports.append(Import(
                    source=n, file=filepath,
                    line=node.start_point[0] + 1, module=module,
                ))

        elif node.type == "call":
            func_node = node.child_by_field_name("function")
            if func_node:
                callee = _node_text(func_node, source)
                calls.append(CallEdge(
                    caller=parent_name or "<module>", callee=callee,
                    file=filepath, line=node.start_point[0] + 1,
                ))

        elif node.type == "assignment":
            # Module-level or class-level constants
            if not parent_name:
                left = node.child_by_field_name("left")
                if left and left.type == "identifier":
                    name = _node_text(left, source)
                    if name.isupper() or name.startswith("_"):
                        right = node.child_by_field_name("right")
                        val = _node_text(right, source)[:200] if right else ""
                        symbols.append(Symbol(
                            name=name, kind="variable", file=filepath,
                            line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            signature=f"{name} = {val}",
                        ))

        for child in node.children:
            _walk(child, parent_name)

    _walk(root)
    return symbols, imports, calls


def _extract_python_params(params_node, source: bytes) -> list[dict]:
    params = []
    if not params_node:
        return params
    for child in params_node.children:
        if child.type == "identifier":
            params.append({"name": _node_text(child, source)})
        elif child.type == "typed_parameter":
            name_n = child.child_by_field_name("name")
            type_n = child.child_by_field_name("type")
            params.append({
                "name": _node_text(name_n, source) if name_n else "",
                "type": _node_text(type_n, source) if type_n else "",
            })
        elif child.type == "default_parameter":
            name_n = child.child_by_field_name("name")
            val_n = child.child_by_field_name("value")
            p = {"name": _node_text(name_n, source) if name_n else ""}
            if val_n:
                p["default"] = _node_text(val_n, source)[:100]
            params.append(p)
    return params


def _extract_python_docstring(node, source: bytes) -> str:
    """Extract the docstring from a function/class body."""
    body = None
    for child in node.children:
        if child.type == "block":
            body = child
            break
    if not body:
        return ""
    for child in body.children:
        if child.type == "expression_statement":
            expr = child.children[0] if child.children else None
            if expr and expr.type == "string":
                text = _node_text(expr, source)
                # Strip quotes
                for q in ['"""', "'''", '"', "'"]:
                    if text.startswith(q) and text.endswith(q):
                        return text[len(q):-len(q)].strip()
                return text
    return ""


def _extract_c_cpp(tree, source: bytes, filepath: str) -> tuple[list[Symbol], list[Import], list[CallEdge]]:
    """Extract from C/C++ AST."""
    symbols = []
    imports = []
    calls = []
    root = tree.root_node

    def _walk(node, parent_name=""):
        if node.type == "function_definition":
            # Get declarator for function name and params
            decl = node.child_by_field_name("declarator")
            if decl:
                name, params, ret = _extract_c_func_info(node, decl, source)
                qual = f"{parent_name}::{name}" if parent_name else name
                symbols.append(Symbol(
                    name=name, kind="function", file=filepath,
                    line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                    signature=_node_text(node, source).split("\n")[0].strip()[:300],
                    return_type=ret, params=params, parent=parent_name,
                ))
                # Walk body for calls and nested
                body = node.child_by_field_name("body")
                if body:
                    _walk(body, qual)
                return

        elif node.type in ("class_specifier", "struct_specifier"):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                qual = f"{parent_name}::{name}" if parent_name else name
                symbols.append(Symbol(
                    name=name, kind="struct" if node.type == "struct_specifier" else "class",
                    file=filepath, line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1, parent=parent_name,
                ))
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        _walk(child, qual)
                return

        elif node.type == "preproc_include":
            path_node = node.child_by_field_name("path")
            if path_node:
                imports.append(Import(
                    source=_node_text(path_node, source), file=filepath,
                    line=node.start_point[0] + 1,
                ))

        elif node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                callee = _node_text(func_node, source)
                calls.append(CallEdge(
                    caller=parent_name or "<file>", callee=callee,
                    file=filepath, line=node.start_point[0] + 1,
                ))

        elif node.type == "field_declaration":
            # Class/struct members
            if parent_name:
                decl = node.child_by_field_name("declarator")
                type_node = node.child_by_field_name("type")
                if decl:
                    name = _node_text(decl, source)[:200]
                    typ = _node_text(type_node, source) if type_node else ""
                    symbols.append(Symbol(
                        name=name, kind="variable", file=filepath,
                        line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        signature=f"{typ} {name}", parent=parent_name,
                    ))

        for child in node.children:
            _walk(child, parent_name)

    _walk(root)
    return symbols, imports, calls


def _extract_c_func_info(func_node, decl, source: bytes) -> tuple[str, list[dict], str]:
    """Extract function name, params, return type from C/C++ function definition."""
    name = ""
    params = []
    ret = ""

    # Find the function_declarator
    def _find_name_and_params(d):
        nonlocal name, params
        if d.type in ("function_declarator",):
            child_name = d.child_by_field_name("declarator")
            if child_name:
                name = _node_text(child_name, source).split("(")[0].strip("*& ")
            param_list = d.child_by_field_name("parameters")
            if param_list:
                for p in param_list.children:
                    if p.type == "parameter_declaration":
                        pdecl = p.child_by_field_name("declarator")
                        ptype = p.child_by_field_name("type")
                        pname = _node_text(pdecl, source) if pdecl else ""
                        ptyp = _node_text(ptype, source) if ptype else ""
                        params.append({"name": pname.split("=")[0].strip(),
                                       "type": ptyp})
        elif d.type == "pointer_declarator":
            for c in d.children:
                _find_name_and_params(c)

    _find_name_and_params(decl)
    # Return type: from the function_definition's type child
    type_node = func_node.child_by_field_name("type")
    if type_node:
        ret = _node_text(type_node, source)
    return name, params, ret


def _extract_java(tree, source: bytes, filepath: str) -> tuple[list[Symbol], list[Import], list[CallEdge]]:
    """Extract from Java AST."""
    symbols = []
    imports = []
    calls = []
    root = tree.root_node

    def _walk(node, parent_name=""):
        if node.type == "import_declaration":
            text = _node_text(node, source)
            # import com.foo.Bar;  or import static com.foo.Bar.method;
            parts = text.replace("import ", "").replace("static ", "").rstrip(";").strip()
            imports.append(Import(
                source=parts, file=filepath,
                line=node.start_point[0] + 1,
            ))

        elif node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                qual = f"{parent_name}.{name}" if parent_name else name
                # Get superclass/interfaces
                super_node = node.child_by_field_name("superclass")
                interfaces_node = node.child_by_field_name("interfaces")
                bases = []
                if super_node:
                    bases.append(_node_text(super_node, source))
                if interfaces_node:
                    bases.append(_node_text(interfaces_node, source))
                symbols.append(Symbol(
                    name=name, kind="class", file=filepath,
                    line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                    signature=f"class {name}" + (f" extends/implements {', '.join(bases)}" if bases else ""),
                    parent=parent_name,
                ))
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        _walk(child, qual)
                return

        elif node.type == "interface_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                qual = f"{parent_name}.{name}" if parent_name else name
                symbols.append(Symbol(
                    name=name, kind="interface", file=filepath,
                    line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                    parent=parent_name,
                ))
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        _walk(child, qual)
                return

        elif node.type == "method_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                qual = f"{parent_name}.{name}" if parent_name else name
                # Parameters
                params_node = node.child_by_field_name("parameters")
                params = []
                if params_node:
                    for p in params_node.children:
                        if p.type == "formal_parameter":
                            pname = ""
                            ptype = ""
                            for c in p.children:
                                if c.type == "identifier":
                                    pname = _node_text(c, source)
                                elif c.type in ("type_identifier", "integral_type", "boolean_type",
                                                 "void_type", "generic_type"):
                                    ptype = _node_text(c, source)
                            params.append({"name": pname, "type": ptype})
                # Return type
                ret_node = node.child_by_field_name("type")
                ret = _node_text(ret_node, source) if ret_node else ""
                # Modifiers
                mods = []
                is_static = False
                is_abstract = False
                for c in node.children:
                    if c.type == "modifiers":
                        for m in c.children:
                            mods.append(_node_text(m, source))
                            if m.text == b"static":
                                is_static = True
                            if m.text == b"abstract":
                                is_abstract = True
                vis = ""
                for m in mods:
                    if m in ("public", "private", "protected"):
                        vis = m
                symbols.append(Symbol(
                    name=name, kind="method", file=filepath,
                    line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                    signature=_node_text(node, source).split("\n")[0].strip()[:300],
                    return_type=ret, params=params, parent=parent_name,
                    visibility=vis, is_static=is_static, is_abstract=is_abstract,
                ))
                # Walk body for calls
                body = node.child_by_field_name("body")
                if body:
                    _walk(body, qual)
                return

        elif node.type == "method_invocation":
            obj_node = node.child_by_field_name("object")
            name_node = node.child_by_field_name("name")
            if name_node:
                callee = _node_text(name_node, source)
                if obj_node:
                    callee = f"{_node_text(obj_node, source)}.{callee}"
                calls.append(CallEdge(
                    caller=parent_name or "<class>", callee=callee,
                    file=filepath, line=node.start_point[0] + 1,
                ))

        elif node.type == "field_declaration":
            # Class fields
            if parent_name:
                for c in node.children:
                    if c.type == "variable_declarator":
                        name_n = c.child_by_field_name("name")
                        if name_n:
                            symbols.append(Symbol(
                                name=_node_text(name_n, source),
                                kind="variable", file=filepath,
                                line=node.start_point[0] + 1,
                                end_line=node.end_point[0] + 1,
                                parent=parent_name,
                            ))

        for child in node.children:
            _walk(child, parent_name)

    _walk(root)
    return symbols, imports, calls


def _extract_scala(tree, source: bytes, filepath: str) -> tuple[list[Symbol], list[Import], list[CallEdge]]:
    """Extract from Scala AST (best-effort)."""
    symbols = []
    imports = []
    calls = []
    root = tree.root_node

    def _walk(node, parent_name=""):
        if node.type == "import_declaration":
            text = _node_text(node, source)
            imports.append(Import(
                source=text.replace("import ", "").strip(),
                file=filepath, line=node.start_point[0] + 1,
            ))

        elif node.type in ("class_definition", "trait_definition", "object_definition"):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                kind = {"class_definition": "class", "trait_definition": "trait",
                        "object_definition": "object"}.get(node.type, "class")
                qual = f"{parent_name}.{name}" if parent_name else name
                symbols.append(Symbol(
                    name=name, kind=kind, file=filepath,
                    line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                    parent=parent_name,
                ))
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        _walk(child, qual)
                return

        elif node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                qual = f"{parent_name}.{name}" if parent_name else name
                symbols.append(Symbol(
                    name=name, kind="method" if parent_name else "function",
                    file=filepath, line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    signature=_node_text(node, source).split("\n")[0].strip()[:300],
                    parent=parent_name,
                ))
                body = node.child_by_field_name("body")
                if body:
                    _walk(body, qual)
                return

        elif node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                callee = _node_text(func_node, source)
                calls.append(CallEdge(
                    caller=parent_name or "<file>", callee=callee,
                    file=filepath, line=node.start_point[0] + 1,
                ))

        for child in node.children:
            _walk(child, parent_name)

    _walk(root)
    return symbols, imports, calls


def _extract_sql(tree, source: bytes, filepath: str) -> tuple[list[Symbol], list[Import], list[CallEdge]]:
    """Extract table names and operation types from SQL."""
    symbols = []
    imports = []
    calls = []
    root = tree.root_node

    def _walk(node):
        text = _node_text(node, source)
        if node.type == "statement" and text.strip():
            first_word = text.strip().split()[0].upper() if text.strip() else ""
            if first_word in ("SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"):
                symbols.append(Symbol(
                    name=f"SQL_{first_word}_{node.start_point[0]+1}",
                    kind="sql_statement", file=filepath,
                    line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                    signature=text.strip()[:500],
                ))

        for child in node.children:
            _walk(child)

    _walk(root)
    return symbols, imports, calls


def _extract_xml(tree, source: bytes, filepath: str) -> tuple[list[Symbol], list[Import], list[CallEdge]]:
    """Extract XML elements, attributes, embedded SQL, and UDF references."""
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from spark_analysis import extract_sql_functions, analyze_spark_sql

    symbols = []
    imports = []
    calls = []
    root = tree.root_node

    # Walk XML tree and collect elements with their text content
    def _walk(node, parent_path=""):
        if node.type == "element":
            # Get element name
            name_node = None
            for child in node.children:
                if child.type == "STag":
                    for sub in child.children:
                        if sub.type == "Name":
                            name_node = sub
                            break
                    break

            if name_node:
                elem_name = _node_text(name_node, source)
                elem_path = f"{parent_path}/{elem_name}" if parent_path else elem_name

                # Extract attributes
                attrs = {}
                for child in node.children:
                    if child.type == "STag":
                        for sub in child.children:
                            if sub.type == "Attribute":
                                attr_name = ""
                                attr_val = ""
                                for achild in sub.children:
                                    if achild.type == "Name":
                                        attr_name = _node_text(achild, source)
                                    elif achild.type == "AttValue":
                                        raw = _node_text(achild, source)
                                        attr_val = raw.strip('"').strip("'")
                                if attr_name:
                                    attrs[attr_name] = attr_val

                # Build signature from element + attributes
                attr_str = ", ".join(f"{k}={v}" for k, v in attrs.items()) if attrs else ""
                sig = f"<{elem_name}" + (f" {attr_str}" if attr_str else "") + ">"

                symbols.append(Symbol(
                    name=elem_name,
                    kind="xml_element",
                    file=filepath,
                    line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    signature=sig[:500],
                    parent=parent_path,
                ))

                # Extract text content for SQL analysis
                text_content = ""
                for child in node.children:
                    if child.type == "content":
                        for sub in child.children:
                            if sub.type == "CharData":
                                text_content += _node_text(sub, source)

                text_content = text_content.strip()
                if text_content and len(text_content) > 20:
                    # Check if it looks like SQL
                    first_word = text_content.split()[0].upper() if text_content.split() else ""
                    if first_word in ("SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "WITH"):
                        # Add as SQL symbol
                        symbols.append(Symbol(
                            name=f"SQL_{elem_name}_{node.start_point[0]+1}",
                            kind="sql_in_xml",
                            file=filepath,
                            line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            signature=text_content[:500],
                            parent=elem_path,
                        ))

                        # Extract function calls from SQL
                        sql_calls = extract_sql_functions(
                            text_content, filepath, node.start_point[0]
                        )
                        for sc in sql_calls:
                            calls.append(CallEdge(
                                caller=elem_path,
                                callee=sc.name,
                                file=filepath,
                                line=sc.line,
                            ))

                # Recurse into children
                for child in node.children:
                    _walk(child, elem_path)
            else:
                for child in node.children:
                    _walk(child, parent_path)
        elif node.type == "content":
            for child in node.children:
                _walk(child, parent_path)
        elif node.type == "document":
            for child in node.children:
                _walk(child, parent_path)

    _walk(root)
    return symbols, imports, calls


# Also detect UDF registrations and XML loaders in Scala/Java files
def _extract_spark_cross_ref(filepath: str, source_text: str) -> dict:
    """Extract Spark UDF definitions and XML loader references from Scala/Java."""
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from spark_analysis import detect_udfs_in_source, detect_xml_loaders

    udfs = detect_udfs_in_source(filepath, source_text)
    xml_loaders = detect_xml_loaders(filepath, source_text)

    return {
        "udfs": [
            {"name": u.name, "class": u.class_name, "file": u.file,
             "line": u.line, "type": u.registration_type}
            for u in udfs
        ],
        "xml_loaders": [
            {"xml_file": r.xml_file, "loader_file": r.loader_file,
             "line": r.loader_line, "method": r.loader_method, "context": r.context}
            for r in xml_loaders
        ],
    }


EXTRACTORS = {
    "C": _extract_c_cpp,
    "C++": _extract_c_cpp,
    "Java": _extract_java,
    "Python": _extract_python,
    "Scala": _extract_scala,
    "SQL": _extract_sql,
    "XML": _extract_xml,
}


# ── SQL extraction from embedded strings ─────────────────────────────────────

_SQL_PATTERN = re.compile(
    r"""(?:["'])(\s*(?:SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\s+.+?)(?:["'])""",
    re.IGNORECASE | re.DOTALL,
)


def _extract_embedded_sql(filepath: str, source_text: str) -> list[dict]:
    """Find SQL strings embedded in non-SQL source files."""
    results = []
    for m in _SQL_PATTERN.finditer(source_text):
        sql = m.group(1).strip()
        if len(sql) > 20:  # skip trivial matches
            line_num = source_text[:m.start()].count("\n") + 1
            results.append({
                "sql": sql[:500],
                "file": filepath,
                "line": line_num,
            })
    return results


# ── Main extraction ──────────────────────────────────────────────────────────

def analyze_file(filepath: str, repo_root: str) -> FileAnalysis:
    """Analyze a single source file with tree-sitter."""
    rel = os.path.relpath(filepath, repo_root)
    ext = os.path.splitext(filepath)[1].lower()
    lang = EXT_TO_LANG.get(ext)

    if not lang:
        return FileAnalysis(path=rel, language="unknown")

    try:
        with open(filepath, "rb") as f:
            source = f.read()
    except (OSError, PermissionError) as e:
        return FileAnalysis(path=rel, language=lang, error=str(e))

    if len(source) > 2_000_000:  # 2MB limit
        return FileAnalysis(path=rel, language=lang, error="file too large")

    try:
        parser = Parser(LANGUAGES[lang])
        tree = parser.parse(source)
    except Exception as e:
        return FileAnalysis(path=rel, language=lang, error=f"parse error: {e}")

    extractor = EXTRACTORS.get(lang)
    if not extractor:
        return FileAnalysis(path=rel, language=lang)

    try:
        syms, imps, calls = extractor(tree, source, rel)
    except Exception as e:
        return FileAnalysis(path=rel, language=lang, error=f"extract error: {e}")

    # Embedded SQL extraction for non-SQL files
    sql_stmts = []
    if lang != "SQL":
        try:
            source_text = source.decode("utf-8", errors="ignore")
            sql_stmts = _extract_embedded_sql(rel, source_text)
        except Exception:
            pass

    # Spark cross-reference for Scala/Java files
    spark_ref = []
    if lang in ("Scala", "Java"):
        try:
            source_text = source.decode("utf-8", errors="ignore")
            spark_data = _extract_spark_cross_ref(rel, source_text)
            if spark_data.get("udfs") or spark_data.get("xml_loaders"):
                spark_ref = [spark_data]
        except Exception:
            pass

    return FileAnalysis(
        path=rel, language=lang,
        symbols=[asdict(s) for s in syms],
        imports=[asdict(i) for i in imps],
        calls=[asdict(c) for c in calls],
        sql_stmts=sql_stmts,
        spark_cross_ref=spark_ref,
    )


def run_phase1(repo_path: str, output_dir: str | None = None, max_files: int = 5000,
               skip_tests: bool = False) -> dict:
    """Run Phase 1 structure extraction on all source files.

    Args:
        repo_path: path to the repository
        output_dir: output directory for analysis data
        max_files: maximum number of files to analyze
        skip_tests: if True, skip test files (auto-detects pytest, JUnit, Jest, etc.)

    Returns a summary dict with all extracted data.
    """
    root = Path(repo_path).resolve()
    out = Path(output_dir) if output_dir else root / ".code-analysis"
    out.mkdir(parents=True, exist_ok=True)

    # Load metadata from Phase 0
    meta_file = out / "metadata.json"
    if meta_file.exists():
        with open(meta_file, encoding="utf-8") as f:
            metadata = json.load(f)
    else:
        metadata = {}

    print(f"[Phase 1] Extracting structure from {root} ...")

    # Collect all source files
    source_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in EXT_TO_LANG:
                fpath = os.path.join(dirpath, fname)
                source_files.append(fpath)

    print(f"  Found {len(source_files)} source files")

    # Filter out test files if requested
    if skip_tests:
        original_count = len(source_files)
        filtered = []
        for fpath in source_files:
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read(5000)  # read first 5KB for marker detection
                rel = os.path.relpath(fpath, str(root))
                if not is_test_file(rel, content):
                    filtered.append(fpath)
            except (OSError, PermissionError):
                filtered.append(fpath)  # keep if can't read
        source_files = filtered
        skipped = original_count - len(source_files)
        print(f"  Skipped {skipped} test files (--skip-tests)")
        print(f"  Remaining: {len(source_files)} files")

    if len(source_files) > max_files:
        print(f"  Capping at {max_files} files")
        source_files = source_files[:max_files]

    # Analyze each file
    all_analysis: list[dict] = []
    total_syms = 0
    total_imports = 0
    total_calls = 0
    errors = 0

    for i, fpath in enumerate(source_files):
        if (i + 1) % 100 == 0:
            print(f"  Progress: {i+1}/{len(source_files)} files ...")
        result = analyze_file(fpath, str(root))
        all_analysis.append(asdict(result))
        total_syms += len(result.symbols)
        total_imports += len(result.imports)
        total_calls += len(result.calls)
        if result.error:
            errors += 1

    # ── Enhanced call graph: callback/function pointer detection ──────────
    print(f"  Enhancing call graph (callback detection) ...")
    from callback_detection import enhance_call_graph
    callback_data = enhance_call_graph(all_analysis, str(root))
    cb_summary = callback_data['summary']
    print(f"    Function pointer fields: {cb_summary['func_pointer_fields']}")
    print(f"    Callback registrations: {cb_summary['callback_registrations']}")
    print(f"    Indirect calls: {cb_summary['indirect_calls']}")
    print(f"    Dispatch tables: {cb_summary['dispatch_tables']}")
    print(f"    Enhanced edges: {cb_summary['enhanced_edges']}")

    # Build module grouping (by directory)
    modules: dict[str, list[dict]] = {}
    for fa in all_analysis:
        dir_name = os.path.dirname(fa["path"])
        if not dir_name:
            dir_name = "<root>"
        if dir_name not in modules:
            modules[dir_name] = []
        modules[dir_name].append(fa)

    # Build global symbol index
    global_symbols: dict[str, list[dict]] = {}
    for fa in all_analysis:
        for sym in fa["symbols"]:
            key = sym["name"]
            if key not in global_symbols:
                global_symbols[key] = []
            global_symbols[key].append(sym)

    # Build call graph (direct + enhanced indirect)
    call_graph: list[dict] = []
    for fa in all_analysis:
        call_graph.extend(fa["calls"])
    # Add enhanced edges
    call_graph.extend(callback_data.get("enhanced_call_edges", []))

    # Build import graph
    import_graph: list[dict] = []
    for fa in all_analysis:
        import_graph.extend(fa["imports"])

    summary = {
        "total_files_analyzed": len(all_analysis),
        "total_symbols": total_syms,
        "total_imports": total_imports,
        "total_calls": total_calls,
        "errors": errors,
        "modules": {k: len(v) for k, v in modules.items()},
        "module_count": len(modules),
        "callback_detection": cb_summary,
    }

    # Save full analysis
    out_file = out / "structure.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "summary": summary,
            "files": all_analysis,
            "module_groups": list(modules.keys()),
            "call_graph": call_graph[:5000],  # cap to avoid huge files
            "import_graph": import_graph[:5000],
            "callback_data": {
                "dispatch_tables": callback_data.get("dispatch_tables", []),
                "func_pointer_fields": callback_data.get("func_pointer_fields", [])[:500],
                "callback_registrations": callback_data.get("callback_registrations", [])[:500],
                "indirect_calls": callback_data.get("indirect_calls", [])[:500],
                "java_dispatch": callback_data.get("java_dispatch", [])[:200],
            },
        }, f, indent=1, ensure_ascii=False)

    # Save per-module files for Phase 2
    modules_dir = out / "modules"
    modules_dir.mkdir(exist_ok=True)
    for mod_name, files in modules.items():
        safe_name = mod_name.replace("/", "_").replace("\\", "_").replace(".", "_")
        mod_file = modules_dir / f"{safe_name}.json"
        # Include callback data relevant to this module
        mod_files_set = {fa["path"] for fa in files}
        mod_callbacks = {
            "dispatch_tables": [dt for dt in callback_data.get("dispatch_tables", [])
                                if any(fp.get("file") in mod_files_set 
                                       for fp in callback_data.get("func_pointer_fields", [])
                                       if fp.get("struct") == dt.get("struct"))],
            "callback_registrations": [r for r in callback_data.get("callback_registrations", [])
                                       if r.get("file") in mod_files_set],
            "indirect_calls": [ic for ic in callback_data.get("indirect_calls", [])
                               if ic.get("file") in mod_files_set],
        }
        with open(mod_file, "w", encoding="utf-8") as f:
            json.dump({"module": mod_name, "files": files, "callbacks": mod_callbacks},
                      f, indent=1, ensure_ascii=False)

    print(f"\n  Summary:")
    print(f"    Files analyzed: {summary['total_files_analyzed']}")
    print(f"    Symbols: {summary['total_symbols']}")
    print(f"    Imports: {summary['total_imports']}")
    print(f"    Call edges (direct): {summary['total_calls']}")
    print(f"    Call edges (indirect): {cb_summary['enhanced_edges']}")
    print(f"    Modules (dirs): {summary['module_count']}")
    print(f"    Errors: {summary['errors']}")
    print(f"  → Saved to {out_file}")
    print(f"  → Module data in {modules_dir}/")

    return summary


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python phase1_structure.py <repo_path>")
        sys.exit(1)
    run_phase1(sys.argv[1])
