"""C/C++ language extractor using tree-sitter.

Handles both C and C++ source files. Extracts:
- function_definition (name, params, return type)
- class_specifier and struct_specifier (with member fields)
- preproc_include directives
- call_expression edges
- field_declaration (struct/class members as variables)

Qualified names use ``Parent::method`` for C++ methods inside
classes/structs.
"""

from __future__ import annotations

from typing import Any

from repo_analyzer.extractors.base import BaseExtractor, Symbol, Import, CallEdge

try:
    from tree_sitter import Node
except ImportError:
    Node = Any  # type: ignore[assignment,misc]


def _node_text(node: Node, source: bytes) -> str:
    """Return the UTF-8 text of *node*, replacing undecodable bytes."""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Public extractor class
# ---------------------------------------------------------------------------

class CExtractor(BaseExtractor):
    """Extractor for C and C++ translation units."""

    # ---- helpers ----------------------------------------------------------

    @staticmethod
    def _extract_c_func_info(
        func_node: Node, decl: Node, source: bytes
    ) -> tuple[str, list[dict], str]:
        """Recursively extract function name, parameters, and return type.

        Walks through ``pointer_declarator`` wrappers until it reaches the
        ``function_declarator`` that carries the actual name and parameter
        list.  The return type is read from the ``type`` field of the
        enclosing ``function_definition``.
        """
        name = ""
        params: list[dict] = []
        ret = ""

        def _find_name_and_params(d: Node) -> None:
            nonlocal name, params
            if d.type == "function_declarator":
                # Name comes from the declarator child (may be an
                # identifier, qualified_identifier, etc.)
                child_name = d.child_by_field_name("declarator")
                if child_name:
                    raw = _node_text(child_name, source)
                    # Strip trailing pointer/reference decorations that
                    # may leak through from pointer_declarator parents.
                    name = raw.split("(")[0].strip("*& ")

                param_list = d.child_by_field_name("parameters")
                if param_list:
                    for p in param_list.children:
                        if p.type == "parameter_declaration":
                            pdecl = p.child_by_field_name("declarator")
                            ptype = p.child_by_field_name("type")
                            pname = _node_text(pdecl, source) if pdecl else ""
                            ptyp = _node_text(ptype, source) if ptype else ""
                            params.append({
                                "name": pname.split("=")[0].strip(),
                                "type": ptyp,
                            })
            elif d.type == "pointer_declarator":
                for c in d.children:
                    _find_name_and_params(c)

        _find_name_and_params(decl)

        # Return type lives on the function_definition node itself.
        type_node = func_node.child_by_field_name("type")
        if type_node:
            ret = _node_text(type_node, source)

        return name, params, ret

    # ---- main walk --------------------------------------------------------

    def extract(
        self, tree, source: bytes, filepath: str
    ) -> tuple[list[Symbol], list[Import], list[CallEdge]]:
        """Walk the AST rooted at *tree* and return extracted artefacts."""
        symbols: list[Symbol] = []
        imports: list[Import] = []
        calls: list[CallEdge] = []
        root = tree.root_node

        def _walk(node: Node, parent_name: str = "") -> None:
            # ----- function definition ------------------------------------
            if node.type == "function_definition":
                decl = node.child_by_field_name("declarator")
                if decl:
                    name, params, ret = self._extract_c_func_info(
                        node, decl, source
                    )
                    qual = f"{parent_name}::{name}" if parent_name else name
                    symbols.append(
                        Symbol(
                            name=name,
                            kind="function",
                            file=filepath,
                            line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            signature=_node_text(node, source)
                            .split("\n")[0]
                            .strip()[:300],
                            return_type=ret,
                            params=params,
                            parent=parent_name,
                        )
                    )
                    # Only recurse into the body so we don't re-visit the
                    # declarator subtree.
                    body = node.child_by_field_name("body")
                    if body:
                        _walk(body, qual)
                    return

            # ----- class / struct specifier -------------------------------
            elif node.type in ("class_specifier", "struct_specifier"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = _node_text(name_node, source)
                    qual = (
                        f"{parent_name}::{name}" if parent_name else name
                    )
                    kind = (
                        "struct"
                        if node.type == "struct_specifier"
                        else "class"
                    )
                    symbols.append(
                        Symbol(
                            name=name,
                            kind=kind,
                            file=filepath,
                            line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            parent=parent_name,
                        )
                    )
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _walk(child, qual)
                    return

            # ----- #include -----------------------------------------------
            elif node.type == "preproc_include":
                path_node = node.child_by_field_name("path")
                if path_node:
                    imports.append(
                        Import(
                            source=_node_text(path_node, source),
                            file=filepath,
                            line=node.start_point[0] + 1,
                        )
                    )

            # ----- call expression ----------------------------------------
            elif node.type == "call_expression":
                func_node = node.child_by_field_name("function")
                if func_node:
                    callee = _node_text(func_node, source)
                    calls.append(
                        CallEdge(
                            caller=parent_name or "<file>",
                            callee=callee,
                            file=filepath,
                            line=node.start_point[0] + 1,
                        )
                    )

            # ----- field declaration (struct/class member) ----------------
            elif node.type == "field_declaration":
                if parent_name:
                    decl = node.child_by_field_name("declarator")
                    type_node = node.child_by_field_name("type")
                    if decl:
                        fname = _node_text(decl, source)[:200]
                        ftyp = (
                            _node_text(type_node, source)
                            if type_node
                            else ""
                        )
                        symbols.append(
                            Symbol(
                                name=fname,
                                kind="variable",
                                file=filepath,
                                line=node.start_point[0] + 1,
                                end_line=node.end_point[0] + 1,
                                signature=f"{ftyp} {fname}",
                                parent=parent_name,
                            )
                        )

            # ----- default: recurse into children ------------------------
            for child in node.children:
                _walk(child, parent_name)

        _walk(root)
        return symbols, imports, calls
