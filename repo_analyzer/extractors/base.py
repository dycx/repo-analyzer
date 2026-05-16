"""Abstract base class and shared data classes for language extractors.

Every language-specific extractor subclasses ``BaseExtractor`` and implements
the ``extract()`` method.  The base class provides a depth-limited AST walker
and common node-text helpers so each extractor can focus on language-specific
pattern matching.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class Symbol:
    """A single symbol definition (function, class, method, variable, ...)."""

    name: str = ""
    kind: str = ""          # function | method | class | variable | constant | ...
    file: str = ""
    line: int = 0
    end_line: int = 0
    signature: str = ""
    return_type: str = ""
    params: list[str] = field(default_factory=list)
    docstring: str = ""
    parent: str = ""        # enclosing class / namespace, if any
    visibility: str = ""    # public | private | protected | internal | ...
    is_static: bool = False
    is_abstract: bool = False

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Import:
    """An import / include statement."""

    source: str = ""    # the raw text of the import
    file: str = ""
    line: int = 0
    module: str = ""    # resolved module path, when available

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CallEdge:
    """A directed edge from a caller to a callee."""

    caller: str = ""
    callee: str = ""
    file: str = ""
    line: int = 0

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FileAnalysis:
    """Complete analysis result for a single source file."""

    path: str = ""
    language: str = ""
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    calls: list[CallEdge] = field(default_factory=list)
    sql_stmts: list[str] = field(default_factory=list)
    spark_cross_ref: list[str] = field(default_factory=list)
    error: str = ""

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


# ── Abstract base extractor ──────────────────────────────────────────────────


class BaseExtractor(ABC):
    """Contract that every language extractor must satisfy.

    Subclasses implement ``extract(tree, source, filepath)`` and may freely
    use the helper methods ``_walk`` and ``_node_text``.
    """

    @abstractmethod
    def extract(
        self,
        tree: Any,
        source: bytes,
        filepath: str,
    ) -> tuple[list[Symbol], list[Import], list[CallEdge]]:
        """Walk *tree* and return (symbols, imports, call-edges).

        Parameters
        ----------
        tree:
            A tree-sitter ``Tree`` object (already parsed).
        source:
            The raw source bytes that were parsed.
        filepath:
            Relative path of the file being analysed.
        """

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _walk(
        node: Any,
        callback: Callable[[Any, int], None],
        max_depth: int = 50,
        _depth: int = 0,
    ) -> None:
        """Depth-limited pre-order walk of a tree-sitter AST.

        *callback* receives ``(node, depth)`` for every visited node.
        Walking stops when *max_depth* is exceeded (children of nodes at
        that depth are skipped).
        """
        if _depth > max_depth:
            return
        callback(node, _depth)
        for child in node.children:
            BaseExtractor._walk(child, callback, max_depth, _depth + 1)

    @staticmethod
    def _node_text(node: Any, source: bytes) -> str:
        """Return the UTF-8 decoded text for *node* from *source*."""
        return source[node.start_byte : node.end_byte].decode(
            "utf-8", errors="replace"
        )


# ── Test-file detection ──────────────────────────────────────────────────────

_TEST_DIRS = frozenset({
    "test", "tests", "testing", "__tests__", "spec", "specs",
    "test_fixtures", "testdata", "test_data", "test-resources",
    "src/test", "src/tests",
})

_TEST_FILE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^test_\w+\.py$"),
    re.compile(r"^\w+_test\.py$"),
    re.compile(r"^tests?\.py$"),
    re.compile(r"^\w+Test\.java$"),
    re.compile(r"^\w+Tests\.java$"),
    re.compile(r"^\w+Spec\.scala$"),
    re.compile(r"^\w+Test\.scala$"),
    re.compile(r"^\w+Suite\.scala$"),
    re.compile(r"^\w+\.test\.(js|ts|jsx|tsx)$"),
    re.compile(r"^\w+\.spec\.(js|ts|jsx|tsx)$"),
    re.compile(r"^\w+[-_]test\.(js|ts)$"),
    re.compile(r"^\w+_test\.go$"),
    re.compile(r"^test_\w+\.rs$"),
    re.compile(r"^\w+_test\.(c|cpp|cc|cxx)$"),
    re.compile(r"^\w+_tests\.(c|cpp|cc|cxx)$"),
    re.compile(r"^test_\w+\.(c|cpp|cc|cxx)$"),
    re.compile(r"^\w+_spec\.rb$"),
    re.compile(r"^\w+_test\.rb$"),
    re.compile(r"^\w+Test\.php$"),
]

_TEST_EXTENSIONS = frozenset({
    ".test.js", ".test.ts", ".test.jsx", ".test.tsx",
    ".spec.js", ".spec.ts", ".spec.jsx", ".spec.tsx",
    ".test.py", ".spec.py",
})

_TEST_CODE_MARKERS: dict[str, list[str]] = {
    "python": ["import unittest", "import pytest", "from unittest", "from pytest",
               "@pytest.fixture", "@pytest.mark", "def test_", "class Test"],
    "java": ["@Test", "@BeforeEach", "@AfterEach", "@BeforeAll", "@AfterAll",
             "import org.junit", "import org.testng", "import static org.junit"],
    "scala": ["import org.scalatest", "import org.specs2"],
    "javascript": ["describe(", "it(", "test(", "expect("],
    "go": ['import.*testing"', "func Test"],
    "rust": ["#[test]", "#[cfg(test)]"],
    "ruby": ["require.*rspec", "describe.*do", "RSpec.describe"],
}


def is_test_file(filepath: str, content: str | None = None) -> bool:
    """Detect if a file is a test file based on path, name, and optionally content.

    Uses multiple signals:
    1. Directory path contains a test directory name
    2. File name matches test patterns
    3. File extension matches test extensions
    4. Content contains test framework markers (if content provided)
    """
    normalized = filepath.replace("\\", "/")
    parts = normalized.split("/")
    fname = parts[-1] if parts else filepath

    for part in parts[:-1]:
        if part.lower() in _TEST_DIRS:
            return True

    for pattern in _TEST_FILE_PATTERNS:
        if pattern.match(fname):
            return True

    ext_lower = fname[fname.rfind("."):] if "." in fname else ""
    if ext_lower in _TEST_EXTENSIONS:
            return True

    if content:
        content_lower = content.lower()[:5000]
        for lang_markers in _TEST_CODE_MARKERS.values():
            for marker in lang_markers:
                if marker.lower() in content_lower:
                    return True

    return False
