"""Java language extractor using tree-sitter.

Extracts:
- import_declaration (including static imports)
- class_declaration (with superclass and interface information)
- interface_declaration
- method_declaration (params, return type, modifiers, visibility, is_static,
  is_abstract)
- method_invocation (with ``object.method`` qualified names)
- field_declaration (class fields as variables)

Qualified names use ``Parent.method`` for methods inside classes / interfaces.
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

class JavaExtractor(BaseExtractor):
    """Extractor for Java compilation units."""

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
            # ----- import declaration -------------------------------------
            if node.type == "import_declaration":
                text = _node_text(node, source)
                # Strip ``import`` / ``static`` keywords and trailing
                # semicolon.
                parts = (
                    text.replace("import ", "")
                    .replace("static ", "")
                    .rstrip(";")
                    .strip()
                )
                imports.append(
                    Import(
                        source=parts,
                        file=filepath,
                        line=node.start_point[0] + 1,
                    )
                )

            # ----- class declaration --------------------------------------
            elif node.type == "class_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = _node_text(name_node, source)
                    qual = (
                        f"{parent_name}.{name}" if parent_name else name
                    )

                    # Collect superclass and interfaces.
                    bases: list[str] = []
                    super_node = node.child_by_field_name("superclass")
                    if super_node:
                        bases.append(_node_text(super_node, source))
                    interfaces_node = node.child_by_field_name("interfaces")
                    if interfaces_node:
                        bases.append(
                            _node_text(interfaces_node, source)
                        )

                    sig = f"class {name}"
                    if bases:
                        sig += f" extends/implements {', '.join(bases)}"

                    symbols.append(
                        Symbol(
                            name=name,
                            kind="class",
                            file=filepath,
                            line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            signature=sig,
                            parent=parent_name,
                        )
                    )

                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            _walk(child, qual)
                    return

            # ----- interface declaration -----------------------------------
            elif node.type == "interface_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = _node_text(name_node, source)
                    qual = (
                        f"{parent_name}.{name}" if parent_name else name
                    )
                    symbols.append(
                        Symbol(
                            name=name,
                            kind="interface",
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

            # ----- method declaration --------------------------------------
            elif node.type == "method_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = _node_text(name_node, source)
                    qual = (
                        f"{parent_name}.{name}" if parent_name else name
                    )

                    # -- parameters ----------------------------------------
                    params_node = node.child_by_field_name("parameters")
                    params: list[dict] = []
                    if params_node:
                        for p in params_node.children:
                            if p.type == "formal_parameter":
                                pname = ""
                                ptype = ""
                                for c in p.children:
                                    if c.type == "identifier":
                                        pname = _node_text(c, source)
                                    elif c.type in (
                                        "type_identifier",
                                        "integral_type",
                                        "boolean_type",
                                        "void_type",
                                        "generic_type",
                                    ):
                                        ptype = _node_text(c, source)
                                params.append(
                                    {"name": pname, "type": ptype}
                                )

                    # -- return type ----------------------------------------
                    ret_node = node.child_by_field_name("type")
                    ret = (
                        _node_text(ret_node, source) if ret_node else ""
                    )

                    # -- modifiers -----------------------------------------
                    mods: list[str] = []
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

                    symbols.append(
                        Symbol(
                            name=name,
                            kind="method",
                            file=filepath,
                            line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            signature=_node_text(node, source)
                            .split("\n")[0]
                            .strip()[:300],
                            return_type=ret,
                            params=params,
                            parent=parent_name,
                            visibility=vis,
                            is_static=is_static,
                            is_abstract=is_abstract,
                        )
                    )

                    # Walk the method body for nested calls.
                    body = node.child_by_field_name("body")
                    if body:
                        _walk(body, qual)
                    return

            # ----- method invocation --------------------------------------
            elif node.type == "method_invocation":
                obj_node = node.child_by_field_name("object")
                name_node = node.child_by_field_name("name")
                if name_node:
                    callee = _node_text(name_node, source)
                    if obj_node:
                        callee = (
                            f"{_node_text(obj_node, source)}.{callee}"
                        )
                    calls.append(
                        CallEdge(
                            caller=parent_name or "<class>",
                            callee=callee,
                            file=filepath,
                            line=node.start_point[0] + 1,
                        )
                    )

            # ----- field declaration --------------------------------------
            elif node.type == "field_declaration":
                if parent_name:
                    for c in node.children:
                        if c.type == "variable_declarator":
                            fname_node = c.child_by_field_name("name")
                            if fname_node:
                                symbols.append(
                                    Symbol(
                                        name=_node_text(
                                            fname_node, source
                                        ),
                                        kind="variable",
                                        file=filepath,
                                        line=node.start_point[0] + 1,
                                        end_line=node.end_point[0] + 1,
                                        parent=parent_name,
                                    )
                                )

            # ----- default: recurse into children -------------------------
            for child in node.children:
                _walk(child, parent_name)

        _walk(root)
        return symbols, imports, calls
