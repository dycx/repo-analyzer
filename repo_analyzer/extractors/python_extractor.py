"""Tree-sitter based extractor for Python source files.

Extracts function definitions, class definitions, imports, function/method
calls, and module-level constant assignments.
"""

from __future__ import annotations

from typing import Any

from repo_analyzer.extractors.base import BaseExtractor, Symbol, Import, CallEdge

try:
    import tree_sitter_python as tspython
    from tree_sitter import Language
except ImportError:
    tspython = None  # type: ignore[assignment]
    Language = None  # type: ignore[assignment,misc]

_LANG = Language(tspython.language()) if Language and tspython else None


class PythonExtractor(BaseExtractor):
    """Extract symbols, imports and call edges from a Python AST."""

    # Node types we care about for top-level collection
    _TOP_LEVEL_TYPES = {
        "function_definition",
        "class_definition",
        "import_statement",
        "import_from_statement",
        "call",
        "assignment",
    }

    def extract(
        self,
        tree: Any,
        source: bytes,
        filepath: str,
    ) -> tuple[list[Symbol], list[Import], list[CallEdge]]:
        """Walk *tree* and return (symbols, imports, call-edges)."""
        symbols: list[Symbol] = []
        imports: list[Import] = []
        calls: list[CallEdge] = []

        # Current scope tracking for qualified names
        self._scope: list[str] = []
        self._source = source
        self._filepath = filepath

        root = tree.root_node
        self._walk_module(root, symbols, imports, calls)

        return symbols, imports, calls

    # ── Module-level walk ────────────────────────────────────────────────

    def _walk_module(
        self,
        node: Any,
        symbols: list[Symbol],
        imports: list[Import],
        calls: list[CallEdge],
    ) -> None:
        """Process module-level statements."""
        for child in node.children:
            ntype = child.type

            if ntype == "function_definition":
                self._extract_function(child, symbols, imports, calls)

            elif ntype == "class_definition":
                self._extract_class(child, symbols, imports, calls)

            elif ntype == "import_statement":
                self._extract_import(child, imports)

            elif ntype == "import_from_statement":
                self._extract_import_from(child, imports)

            elif ntype == "call":
                self._extract_call(child, calls, caller="<module>")

            elif ntype == "assignment":
                self._extract_assignment(child, symbols)

            elif ntype == "decorated_definition":
                # The actual definition is a child of the decorated node
                inner = child.child_by_field_name("definition")
                if inner is not None:
                    if inner.type == "function_definition":
                        self._extract_function(inner, symbols, imports, calls)
                    elif inner.type == "class_definition":
                        self._extract_class(inner, symbols, imports, calls)

    # ── Function extraction ──────────────────────────────────────────────

    def _extract_function(
        self,
        node: Any,
        symbols: list[Symbol],
        imports: list[Import],
        calls: list[CallEdge],
    ) -> None:
        """Extract a function_definition node."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = self._node_text(name_node, self._source)

        # Determine if this is a method (inside a class) or a standalone function
        parent_name = self._scope[-1] if self._scope else ""
        qualified = f"{parent_name}.{name}" if parent_name else name
        kind = "method" if parent_name else "function"

        params = self._extract_params(node)
        return_type = self._extract_return_type(node)
        docstring = self._extract_docstring(node)
        signature = self._build_signature(node)
        visibility = self._guess_visibility(name)
        is_static = self._has_decorator(node, "staticmethod")
        is_abstract = self._has_decorator(node, "abstractmethod")

        symbols.append(Symbol(
            name=qualified,
            kind=kind,
            file=self._filepath,
            line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            signature=signature,
            return_type=return_type,
            params=params,
            docstring=docstring,
            parent=parent_name,
            visibility=visibility,
            is_static=is_static,
            is_abstract=is_abstract,
        ))

        # Walk the function body for nested calls and nested defs
        body = node.child_by_field_name("body")
        if body is not None:
            self._walk_body(body, symbols, imports, calls, caller=qualified)

    # ── Class extraction ─────────────────────────────────────────────────

    def _extract_class(
        self,
        node: Any,
        symbols: list[Symbol],
        imports: list[Import],
        calls: list[CallEdge],
    ) -> None:
        """Extract a class_definition node and its members."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = self._node_text(name_node, self._source)

        parent_name = self._scope[-1] if self._scope else ""
        qualified = f"{parent_name}.{name}" if parent_name else name

        # Superclasses
        superclass_node = node.child_by_field_name("superclasses")
        bases: list[str] = []
        if superclass_node is not None:
            for arg in superclass_node.children:
                if arg.type not in ("(", ")", ","):
                    bases.append(self._node_text(arg, self._source))

        signature = self._build_signature(node)
        docstring = self._extract_docstring(node)
        visibility = self._guess_visibility(name)
        is_abstract = self._has_decorator(node, "abstractmethod")

        symbols.append(Symbol(
            name=qualified,
            kind="class",
            file=self._filepath,
            line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            signature=signature,
            return_type="",
            params=bases,
            docstring=docstring,
            parent=parent_name,
            visibility=visibility,
            is_static=False,
            is_abstract=is_abstract,
        ))

        # Enter class scope and walk the body
        self._scope.append(qualified)
        body = node.child_by_field_name("body")
        if body is not None:
            self._walk_body(body, symbols, imports, calls, caller=qualified)
        self._scope.pop()

    # ── Body walker ──────────────────────────────────────────────────────

    def _walk_body(
        self,
        node: Any,
        symbols: list[Symbol],
        imports: list[Import],
        calls: list[CallEdge],
        caller: str = "",
    ) -> None:
        """Walk a block/suite body extracting nested definitions and calls."""
        for child in node.children:
            ntype = child.type

            if ntype == "function_definition":
                self._extract_function(child, symbols, imports, calls)

            elif ntype == "class_definition":
                self._extract_class(child, symbols, imports, calls)

            elif ntype == "import_statement":
                self._extract_import(child, imports)

            elif ntype == "import_from_statement":
                self._extract_import_from(child, imports)

            elif ntype == "call":
                self._extract_call(child, calls, caller=caller)

            elif ntype == "expression_statement":
                # An expression statement may wrap a call
                expr = child.children[0] if child.children else None
                if expr is not None and expr.type == "call":
                    self._extract_call(expr, calls, caller=caller)

            elif ntype == "assignment":
                # Check if the RHS is a call
                rhs = child.child_by_field_name("right")
                if rhs is not None and rhs.type == "call":
                    self._extract_call(rhs, calls, caller=caller)

            elif ntype == "decorated_definition":
                inner = child.child_by_field_name("definition")
                if inner is not None:
                    if inner.type == "function_definition":
                        self._extract_function(inner, symbols, imports, calls)
                    elif inner.type == "class_definition":
                        self._extract_class(inner, symbols, imports, calls)

            elif ntype == "return_statement":
                # A return may wrap a call
                if child.children:
                    ret_expr = child.children[-1]
                    if ret_expr.type == "call":
                        self._extract_call(ret_expr, calls, caller=caller)

            elif ntype == "for_statement":
                body = child.child_by_field_name("body")
                if body is not None:
                    self._walk_body(body, symbols, imports, calls, caller=caller)

            elif ntype == "while_statement":
                body = child.child_by_field_name("body")
                if body is not None:
                    self._walk_body(body, symbols, imports, calls, caller=caller)

            elif ntype == "if_statement":
                for sub in child.children:
                    if sub.type == "block":
                        self._walk_body(sub, symbols, imports, calls, caller=caller)

            elif ntype == "with_statement":
                body = child.child_by_field_name("body")
                if body is not None:
                    self._walk_body(body, symbols, imports, calls, caller=caller)

            elif ntype == "try_statement":
                for sub in child.children:
                    if sub.type == "block":
                        self._walk_body(sub, symbols, imports, calls, caller=caller)

    # ── Import extraction ────────────────────────────────────────────────

    def _extract_import(self, node: Any, imports: list[Import]) -> None:
        """Extract ``import foo, bar`` statements."""
        for child in node.children:
            if child.type == "dotted_name":
                name = self._node_text(child, self._source)
                imports.append(Import(
                    source=name,
                    file=self._filepath,
                    line=node.start_point[0] + 1,
                    module=name,
                ))
            elif child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                if name_node is not None:
                    name = self._node_text(name_node, self._source)
                    imports.append(Import(
                        source=self._node_text(child, self._source),
                        file=self._filepath,
                        line=node.start_point[0] + 1,
                        module=name,
                    ))

    def _extract_import_from(self, node: Any, imports: list[Import]) -> None:
        """Extract ``from foo import bar`` statements."""
        module_node = node.child_by_field_name("module_name")
        module = ""
        if module_node is not None:
            module = self._node_text(module_node, self._source)
        elif node.children:
            # tree-sitter-python may use 'module' as field or not
            for child in node.children:
                if child.type == "dotted_name":
                    module = self._node_text(child, self._source)
                    break

        # Collect imported names
        imported_names: list[str] = []
        for child in node.children:
            if child.type == "dotted_name" and not module:
                module = self._node_text(child, self._source)
            elif child.type == "import_list":
                for name_child in child.children:
                    if name_child.type == "dotted_name":
                        imported_names.append(self._node_text(name_child, self._source))
                    elif name_child.type == "aliased_import":
                        name_node = name_child.child_by_field_name("name")
                        if name_node is not None:
                            imported_names.append(self._node_text(name_node, self._source))
                    elif name_child.type == "wildcard_import":
                        imported_names.append("*")

        if imported_names:
            for imp_name in imported_names:
                imports.append(Import(
                    source=imp_name,
                    file=self._filepath,
                    line=node.start_point[0] + 1,
                    module=module,
                ))
        else:
            # Bare ``from X import`` with no names parsed -- record the module
            imports.append(Import(
                source=self._node_text(node, self._source),
                file=self._filepath,
                line=node.start_point[0] + 1,
                module=module,
            ))

    # ── Call extraction ──────────────────────────────────────────────────

    def _extract_call(
        self,
        node: Any,
        calls: list[CallEdge],
        caller: str = "<module>",
    ) -> None:
        """Extract a call node as a CallEdge."""
        func_node = node.child_by_field_name("function")
        if func_node is None:
            return
        callee = self._node_text(func_node, self._source)
        calls.append(CallEdge(
            caller=caller,
            callee=callee,
            file=self._filepath,
            line=node.start_point[0] + 1,
        ))

    # ── Assignment (module-level constants) ──────────────────────────────

    def _extract_assignment(self, node: Any, symbols: list[Symbol]) -> None:
        """Extract module-level constant assignments (ALL_CAPS names)."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None:
            return

        # Only capture simple name assignments at module level
        if left.type != "identifier":
            return

        name = self._node_text(left, self._source)

        # Heuristic: module-level constants are typically UPPER_CASE
        if not name.isupper() and not name.startswith("_"):
            return

        value_text = ""
        if right is not None:
            value_text = self._node_text(right, self._source)

        symbols.append(Symbol(
            name=name,
            kind="constant",
            file=self._filepath,
            line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            signature=value_text,
            return_type="",
            params=[],
            docstring="",
            parent=self._scope[-1] if self._scope else "",
            visibility="public",
            is_static=False,
            is_abstract=False,
        ))

    # ── Parameter extraction ─────────────────────────────────────────────

    def _extract_params(self, node: Any) -> list[str]:
        """Extract parameter names from a function_definition node."""
        params_node = node.child_by_field_name("parameters")
        if params_node is None:
            return []

        result: list[str] = []
        for child in params_node.children:
            ptype = child.type

            if ptype in ("(", ")", ",", "comment"):
                continue

            if ptype == "identifier":
                # Simple parameter: ``def f(x):``
                result.append(self._node_text(child, self._source))

            elif ptype == "typed_parameter":
                # Typed param: ``def f(x: int):``
                # The inner identifier is the parameter name
                inner = child.children[0] if child.children else None
                if inner is not None and inner.type == "identifier":
                    result.append(self._node_text(inner, self._source))
                else:
                    # ``self`` or ``cls`` sometimes appear directly
                    result.append(self._node_text(child, self._source))

            elif ptype == "default_parameter":
                # Default param: ``def f(x=10):``
                name_node = child.child_by_field_name("name")
                if name_node is not None:
                    result.append(self._node_text(name_node, self._source))

            elif ptype == "typed_default_parameter":
                # Typed default: ``def f(x: int = 10):``
                name_node = child.child_by_field_name("name")
                if name_node is not None:
                    result.append(self._node_text(name_node, self._source))

            elif ptype == "list_splat_pattern":
                # *args
                inner = child.children[0] if child.children else None
                if inner is not None and inner.type == "identifier":
                    result.append(f"*{self._node_text(inner, self._source)}")

            elif ptype == "dictionary_splat_pattern":
                # **kwargs
                inner = child.children[0] if child.children else None
                if inner is not None and inner.type == "identifier":
                    result.append(f"**{self._node_text(inner, self._source)}")

            elif ptype == "keyword_separator":
                # The bare ``*`` separator
                pass

            elif ptype == "positional_separator":
                # The bare ``/`` separator
                pass

        return result

    # ── Docstring extraction ─────────────────────────────────────────────

    def _extract_docstring(self, node: Any) -> str:
        """Extract the docstring from a function or class body.

        Looks for a string literal as the first statement in the body.
        """
        body = node.child_by_field_name("body")
        if body is None or not body.children:
            return ""

        first_stmt = body.children[0]
        if first_stmt.type != "expression_statement":
            return ""

        expr = first_stmt.children[0] if first_stmt.children else None
        if expr is None:
            return ""

        if expr.type == "string":
            text = self._node_text(expr, self._source)
            # Strip surrounding quotes (handles triple-quoted strings)
            return text.strip()

        return ""

    # ── Return type extraction ───────────────────────────────────────────

    def _extract_return_type(self, node: Any) -> str:
        """Extract the return type annotation from a function definition."""
        ret_node = node.child_by_field_name("return_type")
        if ret_node is not None:
            return self._node_text(ret_node, self._source)
        return ""

    # ── Signature building ───────────────────────────────────────────────

    def _build_signature(self, node: Any) -> str:
        """Build a source-level signature string for a function or class.

        Returns the text from the ``def``/``class`` keyword through the
        closing colon, without the body.
        """
        # Collect the text of this node up to (and including) the colon.
        # We scan children to find the colon that ends the header.
        parts: list[str] = []
        for child in node.children:
            parts.append(self._node_text(child, self._source))
            if child.type == ":":
                break
        return " ".join(parts)

    # ── Visibility heuristic ─────────────────────────────────────────────

    @staticmethod
    def _guess_visibility(name: str) -> str:
        """Guess visibility from Python naming conventions."""
        if name.startswith("__") and name.endswith("__"):
            return "public"  # dunder methods are public by convention
        if name.startswith("__"):
            return "private"  # name-mangled
        if name.startswith("_"):
            return "protected"  # single underscore = internal use
        return "public"

    # ── Decorator helpers ────────────────────────────────────────────────

    def _has_decorator(self, node: Any, decorator_name: str) -> bool:
        """Check whether *node* is preceded by a ``@decorator_name`` decorator.

        Walks the parent's children looking for ``decorated_definition``
        wrappers.
        """
        parent = node.parent
        if parent is None:
            return False

        # If the parent is a decorated_definition, check its decorator_list
        if parent.type == "decorated_definition":
            for child in parent.children:
                if child.type == "decorator":
                    text = self._node_text(child, self._source)
                    # ``@staticmethod``, ``@abstractmethod``, etc.
                    if decorator_name in text:
                        return True
        return False
