"""Phase 0: Repository Reconnaissance.

Quick scan to understand a codebase's structure, language composition,
build system, and entry points — without parsing code.
"""

import json
import os
import subprocess
from pathlib import Path
from collections import Counter

# ── Language detection by extension ──────────────────────────────────────────
LANG_EXT_MAP = {
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

# Files/dirs to skip during analysis
SKIP_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".tox",
    ".venv", "venv", "env", ".env", "dist", "build", "target",
    ".idea", ".vscode", ".gradle", ".m2", "vendor", "third_party",
    "external", "deps", ".cache", "egg-info", ".eggs",
}

BUILD_SYSTEM_MARKERS = {
    "CMakeLists.txt": "CMake", "Makefile": "Make", "makefile": "Make",
    "build.gradle": "Gradle", "build.gradle.kts": "Gradle (Kotlin DSL)",
    "pom.xml": "Maven", "build.sbt": "sbt", "build.sc": "Mill",
    "setup.py": "setuptools", "pyproject.toml": "pyproject",
    "requirements.txt": "pip", "Cargo.toml": "Cargo",
    "go.mod": "Go modules", "package.json": "npm",
    "meson.build": "Meson", "WORKSPACE": "Bazel", "BUILD": "Bazel",
}


def _should_skip(name: str) -> bool:
    return name.startswith(".") and name not in {".github"} or name in SKIP_DIRS


def scan_directory(
    root: Path,
    max_depth: int = 20,
) -> dict:
    """Walk the repo and collect file statistics."""
    lang_counts: Counter = Counter()
    lang_lines: Counter = Counter()
    total_files = 0
    total_dirs = 0
    build_systems: set[str] = set()
    entry_points: list[str] = []
    top_level_dirs: list[str] = []
    file_tree: dict = {}  # shallow tree for structure overview

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip dirs
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

            # Build system detection
            if fname in BUILD_SYSTEM_MARKERS:
                build_systems.add(BUILD_SYSTEM_MARKERS[fname])

            # Entry point heuristics
            if fname in {"main.py", "app.py", "manage.py", "__main__.py",
                         "Main.java", "main.c", "main.cpp"}:
                entry_points.append(rel_path)
            if "main" in fname.lower() and ext in {".py", ".java", ".c", ".cpp", ".scala"}:
                if rel_path not in entry_points:
                    entry_points.append(rel_path)

            # Language counting
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

    # Build shallow tree (depth=3)
    tree_lines = []
    for item in sorted(root.iterdir()):
        if _should_skip(item.name):
            continue
        prefix = "├── " if item != list(root.iterdir())[-1] else "└── "
        if item.is_dir():
            tree_lines.append(f"{prefix}{item.name}/")
            sub_items = [x for x in sorted(item.iterdir()) if not _should_skip(x.name)]
            for i, sub in enumerate(sub_items[:8]):  # limit to 8 items per dir
                sub_prefix = "│   " + ("├── " if i < len(sub_items) - 1 else "└── ")
                if sub.is_dir():
                    tree_lines.append(f"{sub_prefix}{sub.name}/")
                else:
                    tree_lines.append(f"{sub_prefix}{sub.name}")
            if len(sub_items) > 8:
                tree_lines.append(f"│   └── ... ({len(sub_items) - 8} more)")
        else:
            tree_lines.append(f"{prefix}{item.name}")

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


def run_phase0(repo_path: str, output_dir: str | None = None) -> dict:
    """Run Phase 0 reconnaissance on a repository.

    Args:
        repo_path: Path to the repository root.
        output_dir: Where to save metadata.json (default: repo/.code-analysis/)

    Returns:
        The metadata dict.
    """
    root = Path(repo_path).resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    out = Path(output_dir) if output_dir else root / ".code-analysis"
    out.mkdir(parents=True, exist_ok=True)

    print(f"[Phase 0] Scanning {root} ...")
    metadata = scan_directory(root)
    metadata["repo_path"] = str(root)
    metadata["repo_name"] = root.name

    # Save
    out_file = out / "metadata.json"
    with open(out_file, "w") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    # Print summary
    print(f"  Files: {metadata['total_files']}")
    print(f"  Languages: {metadata['language_distribution']}")
    print(f"  Lines: {metadata['line_counts']}")
    print(f"  Build: {metadata['build_systems']}")
    print(f"  Entry points: {metadata['entry_points'][:5]}")
    print(f"  → Saved to {out_file}")

    return metadata


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python phase0_recon.py <repo_path>")
        sys.exit(1)
    run_phase0(sys.argv[1])
