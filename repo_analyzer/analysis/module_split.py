"""Auto-split large modules for manageable LLM analysis.

When a module contains too many files to fit in a single LLM context
window, this module splits it into smaller groups using directory
boundaries, merges tiny groups, and falls back to file-count chunking
when needed.
"""

from __future__ import annotations


import logging
import os
from collections import defaultdict

logger = logging.getLogger("repo_analyzer.analysis.module_split")


def _group_by_subdirectory(files: list[str]) -> dict[str, list[str]]:
    """Group files by their immediate subdirectory relative to module root.

    Files at the root level are placed in a ``__root__`` group.

    Parameters
    ----------
    files : list[str]
        Relative file paths.

    Returns
    -------
    dict[str, list[str]]
        Mapping of subdirectory name to file list.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for f in files:
        parts = f.replace("\\", "/").split("/")
        if len(parts) <= 1:
            groups["__root__"].append(f)
        else:
            groups[parts[0]].append(f)
    return dict(groups)


def _merge_small_groups(
    groups: dict[str, list[str]],
    min_size: int = 3,
) -> dict[str, list[str]]:
    """Merge groups smaller than *min_size* into an ``__other__`` bucket.

    Parameters
    ----------
    groups : dict[str, list[str]]
        Subdirectory groups from :func:`_group_by_subdirectory`.
    min_size : int
        Minimum number of files to keep a group separate.

    Returns
    -------
    dict[str, list[str]]
        Merged groups.
    """
    merged: dict[str, list[str]] = {}
    other: list[str] = []

    for name, files in groups.items():
        if len(files) < min_size:
            other.extend(files)
        else:
            merged[name] = files

    if other:
        # Merge into the smallest existing group if it would not exceed 2x min
        # Otherwise create __other__
        if merged:
            smallest_key = min(merged, key=lambda k: len(merged[k]))
            if len(merged[smallest_key]) + len(other) <= min_size * 5:
                merged[smallest_key].extend(other)
            else:
                merged["__other__"] = other
        else:
            merged["__other__"] = other

    return merged


def _chunk_by_count(
    files: list[str],
    chunk_size: int = 20,
) -> list[list[str]]:
    """Split a flat file list into fixed-size chunks.

    Parameters
    ----------
    files : list[str]
        Files to split.
    chunk_size : int
        Maximum files per chunk.

    Returns
    -------
    list[list[str]]
        List of file chunks.
    """
    return [files[i : i + chunk_size] for i in range(0, len(files), chunk_size)]


def auto_split_modules(
    modules: list[dict],
    max_files: int = 10,
) -> list[dict]:
    """Automatically split large modules into smaller analysis units.

    Split strategy (in order):
    1. Group files by immediate subdirectory.
    2. Merge groups with fewer than 3 files.
    3. If any group still exceeds *max_files*, fall back to file-count
       chunking for that group.
    4. Modules with <= *max_files* files are returned unchanged.

    Parameters
    ----------
    modules : list[dict]
        Module definitions. Each must have at least ``module`` (str) and
        ``files`` (list[str]) keys.  ``callbacks`` (list) is optional.
    max_files : int
        Maximum files per output module.

    Returns
    -------
    list[dict]
        Split modules, each with keys ``module``, ``files``, ``callbacks``.
    """
    result: list[dict] = []

    for mod in modules:
        name = mod.get("module", "unknown")
        files = mod.get("files", [])
        callbacks = mod.get("callbacks", [])

        if not files:
            result.append({
                "module": name,
                "files": [],
                "callbacks": callbacks,
            })
            continue

        # Small enough — pass through
        if len(files) <= max_files:
            result.append({
                "module": name,
                "files": list(files),
                "callbacks": callbacks,
            })
            continue

        logger.info(
            "Splitting module '%s' (%d files, max=%d)",
            name, len(files), max_files,
        )

        # Step 1: Group by subdirectory
        groups = _group_by_subdirectory(files)

        # Step 2: Merge small groups
        if len(groups) > 1:
            groups = _merge_small_groups(groups)

        # Step 3: Split oversized groups by count
        part_idx = 0
        for group_name, group_files in sorted(groups.items()):
            if len(group_files) <= max_files:
                suffix = f"__{group_name}" if group_name != "__root__" else ""
                part_name = f"{name}{suffix}"
                result.append({
                    "module": part_name,
                    "files": group_files,
                    "callbacks": callbacks if part_idx == 0 else [],
                })
                part_idx += 1
            else:
                # Chunk oversized group
                chunks = _chunk_by_count(group_files, chunk_size=max_files)
                for ci, chunk in enumerate(chunks):
                    suffix = f"__{group_name}" if group_name != "__root__" else ""
                    if len(chunks) > 1:
                        suffix += f"_part{ci}"
                    part_name = f"{name}{suffix}"
                    result.append({
                        "module": part_name,
                        "files": chunk,
                        "callbacks": callbacks if part_idx == 0 and ci == 0 else [],
                    })
                    part_idx += 1

        logger.info(
            "  -> Split into %d modules",
            part_idx,
        )

    return result
