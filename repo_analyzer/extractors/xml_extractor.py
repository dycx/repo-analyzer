"""XML language extractor using tree-sitter.

Extracts:
- XML elements (with attributes and text content)
- Embedded SQL detected in text content
- SQL function calls from embedded SQL via regex
"""

from __future__ import annotations

import re
from typing import Any

from repo_analyzer.extractors.base import BaseExtractor, Symbol, Import, CallEdge


# SQL keywords that indicate embedded SQL
_SQL_KEYWORDS = frozenset({
    "SELECT", "INSERT", "UPDATE", "DELETE",
    "CREATE", "ALTER", "DROP", "WITH",
})

# Regex to extract function calls from SQL text
# Matches: func_name(...) possibly qualified like schema.func_name
_SQL_FUNC_RE = re.compile(r'\b([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)?)\s*\(')

# SQL keywords that look like function calls but aren't
_SQL_STOPWORDS = frozenset({
    "select", "from", "where", "group", "by", "order", "having",
    "join", "left", "right", "inner", "outer", "full", "cross",
    "on", "and", "or", "not", "in", "between", "like", "is",
    "null", "true", "false", "case", "when", "then", "else", "end",
    "insert", "into", "values", "update", "set", "delete", "create",
    "alter", "drop", "table", "view", "index", "as", "distinct",
    "all", "union", "intersect", "except", "limit", "offset",
    "asc", "desc", "nulls", "first", "last", "with", "recursive",
    "lateral", "unnest", "window", "over", "partition", "rows",
    "range", "unbounded", "preceding", "following", "current",
    "row", "merge", "using", "matched", "cache", "uncache",
    "explain", "describe", "show", "use", "add", "file", "jar",
    "refresh", "reset", "msck", "repair", "load", "data",
    "overwrite", "local", "inpath", "stored", "format", "location",
    "partitioned", "clustered", "sorted", "buckets", "serde",
    "properties", "temporary", "temp", "function", "macro",
})


class XmlExtractor(BaseExtractor):
    """Extractor for XML files."""

    def extract(
        self,
        tree: Any,
        source: bytes,
        filepath: str,
    ) -> tuple[list[Symbol], list[Import], list[CallEdge]]:
        """Walk the XML AST and extract elements, embedded SQL, and SQL calls."""
        symbols: list[Symbol] = []
        imports: list[Import] = []
        calls: list[CallEdge] = []
        seen_sql_funcs: set[str] = set()

        def _walk_xml(node: Any, parent_path: str = "") -> None:
            """Recursively walk the XML tree, tracking element paths."""
            if node.type == "element":
                _handle_element(node, parent_path)
            elif node.type == "content":
                for child in node.children:
                    _walk_xml(child, parent_path)
            elif node.type == "document":
                for child in node.children:
                    _walk_xml(child, parent_path)

        def _handle_element(node: Any, parent_path: str) -> None:
            """Extract an XML element: name, attributes, embedded SQL."""
            # Find element name from STag -> Name
            name_node = None
            stag_node = None
            for child in node.children:
                if child.type == "STag":
                    stag_node = child
                    for sub in child.children:
                        if sub.type == "Name":
                            name_node = sub
                            break
                    break

            if not name_node:
                for child in node.children:
                    _walk_xml(child, parent_path)
                return

            elem_name = BaseExtractor._node_text(name_node, source)
            elem_path = f"{parent_path}/{elem_name}" if parent_path else elem_name

            # Extract attributes from STag
            attrs: dict[str, str] = {}
            if stag_node:
                for sub in stag_node.children:
                    if sub.type == "Attribute":
                        attr_name = ""
                        attr_val = ""
                        for achild in sub.children:
                            if achild.type == "Name":
                                attr_name = BaseExtractor._node_text(achild, source)
                            elif achild.type == "AttValue":
                                raw = BaseExtractor._node_text(achild, source)
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
            text_content = _extract_text(node)

            if text_content and len(text_content) > 20:
                first_word = text_content.split()[0].upper() if text_content.split() else ""
                if first_word in _SQL_KEYWORDS:
                    line = node.start_point[0] + 1
                    symbols.append(Symbol(
                        name=f"SQL_{elem_name}_{line}",
                        kind="sql_in_xml",
                        file=filepath,
                        line=line,
                        end_line=node.end_point[0] + 1,
                        signature=text_content[:500],
                        parent=elem_path,
                    ))

                    # Extract SQL function calls from embedded SQL
                    _extract_sql_calls(text_content, elem_path, node)

            # Recurse into child elements
            for child in node.children:
                _walk_xml(child, elem_path)

        def _extract_text(node: Any) -> str:
            """Extract CharData text content from an element's content."""
            parts: list[str] = []
            for child in node.children:
                if child.type == "content":
                    for sub in child.children:
                        if sub.type == "CharData":
                            parts.append(BaseExtractor._node_text(sub, source))
            return "".join(parts).strip()

        def _extract_sql_calls(sql_text: str, elem_path: str, node: Any) -> None:
            """Extract function calls from embedded SQL text using regex."""
            for m in _SQL_FUNC_RE.finditer(sql_text):
                func_name = m.group(1)
                name_lower = func_name.lower()

                if name_lower in _SQL_STOPWORDS:
                    continue

                if name_lower in seen_sql_funcs:
                    continue
                seen_sql_funcs.add(name_lower)

                calls.append(CallEdge(
                    caller=elem_path,
                    callee=func_name,
                    file=filepath,
                    line=node.start_point[0] + 1,
                ))

        _walk_xml(tree.root_node, "")
        return symbols, imports, calls
