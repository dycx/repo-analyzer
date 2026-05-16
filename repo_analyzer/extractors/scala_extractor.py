"""Scala language extractor using tree-sitter.

Extracts:
- import_declaration
- class_definition, trait_definition, object_definition
- function_definition (def)
- call_expression
"""

from __future__ import annotations

from typing import Any

from repo_analyzer.extractors.base import BaseExtractor, Symbol, Import, CallEdge


# Map tree-sitter node types to symbol kinds
_SCALA_KIND_MAP: dict[str, str] = {
    "class_definition": "class",
    "trait_definition": "trait",
    "object_definition": "object",
}


class ScalaExtractor(BaseExtractor):
    """Extractor for Scala source files."""

    def extract(
        self,
        tree: Any,
        source: bytes,
        filepath: str,
    ) -> tuple[list[Symbol], list[Import], list[CallEdge]]:
        """Walk the Scala AST and extract symbols, imports, and calls."""
        symbols: list[Symbol] = []
        imports: list[Import] = []
        calls: list[CallEdge] = []

        def _visitor(node: Any, _depth: int) -> None:
            ntype = node.type

            # -- Imports --------------------------------------------------
            if ntype == "import_declaration":
                text = BaseExtractor._node_text(node, source)
                imports.append(Import(
                    source=text.replace("import ", "").strip(),
                    file=filepath,
                    line=node.start_point[0] + 1,
                ))

            # -- Class / Trait / Object -----------------------------------
            elif ntype in _SCALA_KIND_MAP:
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = BaseExtractor._node_text(name_node, source)
                    kind = _SCALA_KIND_MAP[ntype]
                    symbols.append(Symbol(
                        name=name,
                        kind=kind,
                        file=filepath,
                        line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        parent="",
                    ))

            # -- Function (def) -------------------------------------------
            elif ntype == "function_definition":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = BaseExtractor._node_text(name_node, source)
                    sig = BaseExtractor._node_text(node, source).split("\n")[0].strip()[:300]
                    symbols.append(Symbol(
                        name=name,
                        kind="function",
                        file=filepath,
                        line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        signature=sig,
                    ))

            # -- Call expression ------------------------------------------
            elif ntype == "call_expression":
                func_node = node.child_by_field_name("function")
                if func_node:
                    callee = BaseExtractor._node_text(func_node, source)
                    calls.append(CallEdge(
                        caller="<file>",
                        callee=callee,
                        file=filepath,
                        line=node.start_point[0] + 1,
                    ))

        BaseExtractor._walk(tree.root_node, _visitor)
        return symbols, imports, calls
