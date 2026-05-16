"""Phase 0: Repository Reconnaissance.

Quick scan to understand a codebase's structure, language composition,
build system, and entry points — without parsing code.
"""

from __future__ import annotations


import json
import logging
import os
from collections import Counter
from pathlib import Path

from repo_analyzer.config import Config

logger = logging.getLogger("repo_analyzer.phase0")

LANG_EXT_MAP: dict[str, str] = {
    ".c": "C", ".h": "C",
    ".cc": "C++", ".cpp": "C++", ".cxx": "C++", ".hpp": "C++", ".hxx": "C++",
    ".java": "Java",
    ".scala": "Scala", ".sc": "Scala",
    ".py": "Python",
    ".sql": "SQL",
    ".js": "JavaScript", ".ts": "TypeScript",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby",
    ".xml": "XML", ".yaml": "YAML", ".yml": "YAML", ".json": "JSON",
    ".proto": "Protobuf", ".thrift": "Thrift",
}

SKIP_DIRS: set[str] = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".tox",
    ".venv", "venv", "env", ".env", "dist", "build", "target",
    ".idea", ".vscode", ".gradle", ".m2", "vendor", "third_party",
    "external", "deps", ".cache", "egg-info", ".eggs",
}

BUILD_SYSTEM_MARKERS: dict[str, str] = {
    "CMakeLists.txt": "CMake", "Makefile": "Make", "makefile": "Make",
    "build.gradle": "Gradle", "build.gradle.kts": "Gradle (Kotlin DSL)",
    "pom.xml": "Maven", "build.sbt": "sbt", "build.sc": "Mill",
    "setup.py": "setuptools", "pyproject.toml": "pyproject",
    "requirements.txt": "pip", "Cargo.toml": "Cargo",
    "go.mod": "Go modules", "package.json": "npm",
    "meson.build": "Meson", "WORKSPACE": "Bazel", "BUILD": "Bazel",
}


def _should_skip(name: str) -> bool:
    if name.startswith(".") and name not in {".github"}:
        return True
    return name in SKIP_DIRS


def scan_directory(root: Path) -> dict:
    """Walk the repo and collect file statistics."""
    lang_counts: Counter[str] = Counter()
    lang_lines: Counter[str] = Counter()
    total_files = 0
    total_dirs = 0
    build_systems: set[str] = set()
    entry_points: list[str] = []
    top_level_dirs: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _should_skip(d)]

        rel_dir = os.path.relpath(dirpath, root)
        depth = rel_dir.count(os.sep) + 1 if rel_dir != "." else 0

        if depth == 1:
            top_level_dirs.extend(dirnames)

        for fname in filenames:
            if _should_skip(fname):
                continue

            fpath = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(fpath, root)
            ext = os.path.splitext(fname)[1].lower()

            if fname in BUILD_SYSTEM_MARKERS:
                build_systems.add(BUILD_SYSTEM_MARKERS[fname])

            if fname in {
                "main.py", "app.py", "manage.py", "__main__.py",
                "Main.java", "main.c", "main.cpp",
            }:
                entry_points.append(rel_path)
            if "main" in fname.lower() and ext in {".py", ".java", ".c", ".cpp", ".scala"}:
                if rel_path not in entry_points:
                    entry_points.append(rel_path)

            lang = LANG_EXT_MAP.get(ext)
            if lang:
                lang_counts[lang] += 1
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        lang_lines[lang] += sum(1 for _ in f)
                except (OSError, UnicodeDecodeError):
                    pass

            total_files += 1

        total_dirs += len(dirnames)

    tree_lines = _build_tree(root)

    return {
        "total_files": total_files,
        "total_dirs": total_dirs,
        "language_distribution": dict(lang_counts.most_common()),
        "line_counts": dict(lang_lines.most_common()),
        "build_systems": sorted(build_systems),
        "entry_points": entry_points[:20],
        "top_level_dirs": sorted(top_level_dirs),
        "directory_tree": "\n".join(tree_lines),
    }


def _build_tree(root: Path) -> list[str]:
    """Build a shallow directory tree string."""
    tree_lines: list[str] = []
    items = [x for x in sorted(root.iterdir()) if not _should_skip(x.name)]
    for idx, item in enumerate(items):
        is_last = idx == len(items) - 1
        prefix = "└── " if is_last else "├── "
        if item.is_dir():
            tree_lines.append(f"{prefix}{item.name}/")
            sub_items = [x for x in sorted(item.iterdir()) if not _should_skip(x.name)]
            for si, sub in enumerate(sub_items[:8]):
                sub_is_last = si == len(sub_items) - 1
                sub_prefix = "│   " + ("└── " if sub_is_last else "├── ")
                if sub.is_dir():
                    tree_lines.append(f"{sub_prefix}{sub.name}/")
                else:
                    tree_lines.append(f"{sub_prefix}{sub.name}")
            if len(sub_items) > 8:
                tree_lines.append(f"│   └── ... ({len(sub_items) - 8} more)")
        else:
            tree_lines.append(f"{prefix}{item.name}")
    return tree_lines


def run_phase0(cfg: Config) -> dict:
    """Run Phase 0 reconnaissance on a repository."""
    root = cfg.repo_path
    out = cfg.analysis_dir
    out.mkdir(parents=True, exist_ok=True)

    logger.info("[Phase 0] Scanning %s ...", root)
    metadata = scan_directory(root)
    metadata["repo_path"] = str(root)
    metadata["repo_name"] = root.name

    out_file = out / "metadata.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    logger.info("  Files: %d", metadata["total_files"])
    logger.info("  Languages: %s", metadata["language_distribution"])
    logger.info("  Build: %s", metadata["build_systems"])
    logger.info("  -> Saved to %s", out_file)

    return metadata
