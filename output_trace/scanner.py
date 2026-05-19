"""Repository scanning for supported source/config files."""

from __future__ import annotations

import os
from pathlib import Path


SUPPORTED_EXTENSIONS = {".py", ".java", ".scala", ".sql", ".xml"}

SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", ".env", "__pycache__",
    "node_modules", "build", "dist", "target", ".gradle", ".idea",
    ".vscode", ".cache", ".code-analysis",
}

TEST_PATH_PARTS = {
    "test", "tests", "src/test", "__tests__", "spec", "specs",
}


def iter_supported_files(repo_root: Path, include_tests: bool = False) -> list[Path]:
    """Return supported files under *repo_root* in stable order."""
    result: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [
            name for name in dirnames
            if name not in SKIP_DIRS and not name.startswith(".")
        ]
        for filename in filenames:
            path = Path(dirpath) / filename
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            rel = path.relative_to(repo_root).as_posix()
            if not include_tests and _looks_like_test_path(rel):
                continue
            result.append(path)
    return sorted(result)


def _looks_like_test_path(rel_path: str) -> bool:
    lowered = rel_path.lower()
    parts = lowered.split("/")
    if any(part in TEST_PATH_PARTS for part in parts):
        return True
    filename = parts[-1]
    return (
        filename.startswith("test_")
        or filename.endswith("_test.py")
        or filename.endswith("test.java")
        or filename.endswith("tests.java")
        or filename.endswith("spec.scala")
        or filename.endswith("suite.scala")
    )

