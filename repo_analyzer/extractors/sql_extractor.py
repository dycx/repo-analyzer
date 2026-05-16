"""SQL language extractor using tree-sitter.

Extracts SQL statements (SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP)
from parsed SQL files.
"""

from __future__ import annotations

from typing import Any

from repo_analyzer.extractors.base import BaseExtractor, Symbol, Import, CallEdge


# SQL statement keywords we care about
_SQL_KEYWORDS = frozenset({
    "SELECT", "INSERT", "UPDATE", "DELETE",
    "CREATE", "ALTER", "DROP",
})


class SqlExtractor(BaseExtractor):
    """Extractor for SQL source files."""

    def extract(
        self,
        tree: Any,
        source: bytes,
        filepath: str,
    ) -> tuple[list[Symbol], list[Import], list[CallEdge]]:
        """Walk the SQL AST and extract statement-level symbols."""
        symbols: list[Symbol] = []
        imports: list[Import] = []
        calls: list[CallEdge] = []

        def _visitor(node: Any, _depth: int) -> None:
            if node.type != "statement":
                return

            text = BaseExtractor._node_text(node, source).strip()
            if not text:
                return

            first_word = text.split()[0].upper()
            if first_word not in _SQL_KEYWORDS:
                return

            line = node.start_point[0] + 1
            symbols.append(Symbol(
                name=f"SQL_{first_word}_{line}",
                kind="sql_statement",
                file=filepath,
                line=line,
                end_line=node.end_point[0] + 1,
                signature=text[:500],
            ))

        BaseExtractor._walk(tree.root_node, _visitor)
        return symbols, imports, calls
