"""Phase 1: Structure Extraction via tree-sitter.

Parses source files into ASTs and extracts symbols, call graphs,
imports, SQL statements, and callback patterns.
"""

from __future__ import annotations


import json
import logging
import os
import re
from dataclasses import asdict
from pathlib import Path

from repo_analyzer.config import Config
from repo_analyzer.extractors.base import FileAnalysis
from repo_analyzer.extractors.c_extractor import CExtractor
from repo_analyzer.extractors.java_extractor import JavaExtractor
from repo_analyzer.extractors.python_extractor import PythonExtractor
from repo_analyzer.extractors.scala_extractor import ScalaExtractor
from repo_analyzer.extractors.sql_extractor import SqlExtractor
from repo_analyzer.extractors.xml_extractor import XmlExtractor

logger = logging.getLogger("repo_analyzer.phase1")

# Lazy-load tree-sitter — the base package and each language grammar are
# optional; Phase 1 degrades gracefully when they're missing.
try:
    from tree_sitter import Language, Parser
except ImportError:
    Language = None  # type: ignore[assignment,misc]
    Parser = None  # type: ignore[assignment,misc]

_LANG_MODULES = {
    "C": ("tree_sitter_c", "language"),
    "C++": ("tree_sitter_cpp", "language"),
    "Java": ("tree_sitter_java", "language"),
    "Python": ("tree_sitter_python", "language"),
    "Scala": ("tree_sitter_scala", "language"),
    "SQL": ("tree_sitter_sql", "language"),
    "XML": ("tree_sitter_xml", "language_xml"),
}

LANGUAGES: dict = {}
if Language is not None:
    import importlib
    for _lang_name, (_mod_name, _func_name) in _LANG_MODULES.items():
        try:
            _mod = importlib.import_module(_mod_name)
            LANGUAGES[_lang_name] = Language(getattr(_mod, _func_name)())
        except ImportError:
            logger.debug("tree-sitter grammar not installed: %s", _mod_name)

_ALL_EXT_TO_LANG: dict[str, str] = {
    ".c": "C", ".h": "C",
    ".cc": "C++", ".cpp": "C++", ".cxx": "C++", ".hpp": "C++", ".hxx": "C++",
    ".java": "Java",
    ".scala": "Scala", ".sc": "Scala",
    ".py": "Python",
    ".sql": "SQL",
    ".xml": "XML", ".xsd": "XML", ".xsl": "XML", ".xslt": "XML",
}

# Only include extensions for languages whose tree-sitter grammars are installed.
EXT_TO_LANG: dict[str, str] = {
    ext: lang for ext, lang in _ALL_EXT_TO_LANG.items() if lang in LANGUAGES
}

SKIP_DIRS: set[str] = {
    ".git", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", "target", ".gradle", ".idea", ".vscode", "vendor",
    "third_party", "external", "deps", ".cache",
}

EXTRACTORS = {
    "C": CExtractor(),
    "C++": CExtractor(),
    "Java": JavaExtractor(),
    "Python": PythonExtractor(),
    "Scala": ScalaExtractor(),
    "SQL": SqlExtractor(),
    "XML": XmlExtractor(),
}

_SQL_PATTERN = re.compile(
    r"""(?:["'])(\s*(?:SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\s+.+?)(?:["'])""",
    re.IGNORECASE | re.DOTALL,
)


def _extract_embedded_sql(filepath: str, source_text: str) -> list[dict]:
    """Find SQL strings embedded in non-SQL source files."""
    results = []
    for m in _SQL_PATTERN.finditer(source_text):
        sql = m.group(1).strip()
        if len(sql) > 20:
            line_num = source_text[:m.start()].count("\n") + 1
            results.append({"sql": sql[:500], "file": filepath, "line": line_num})
    return results


def analyze_file(filepath: str, repo_root: str) -> FileAnalysis:
    """Analyze a single source file with tree-sitter."""
    rel = os.path.relpath(filepath, repo_root)
    ext = os.path.splitext(filepath)[1].lower()
    lang = EXT_TO_LANG.get(ext)

    if not lang:
        return FileAnalysis(path=rel, language="unknown")

    try:
        with open(filepath, "rb") as f:
            source = f.read()
    except (OSError, PermissionError) as e:
        return FileAnalysis(path=rel, language=lang, error=str(e))

    if len(source) > 2_000_000:
        return FileAnalysis(path=rel, language=lang, error="file too large")

    try:
        parser = Parser(LANGUAGES[lang])
        tree = parser.parse(source)
    except Exception as e:
        return FileAnalysis(path=rel, language=lang, error=f"parse error: {e}")

    extractor = EXTRACTORS.get(lang)
    if not extractor:
        return FileAnalysis(path=rel, language=lang)

    try:
        syms, imps, calls = extractor.extract(tree, source, rel)
    except Exception as e:
        return FileAnalysis(path=rel, language=lang, error=f"extract error: {e}")

    sql_stmts: list[dict] = []
    if lang != "SQL":
        try:
            source_text = source.decode("utf-8", errors="ignore")
            sql_stmts = _extract_embedded_sql(rel, source_text)
        except Exception as e:
            logger.warning("Embedded SQL extraction failed for %s: %s", rel, e)

    spark_ref: list[dict] = []
    if lang in ("Scala", "Java"):
        try:
            from repo_analyzer.analysis.spark import detect_udfs_in_source, detect_xml_loaders
            source_text = source.decode("utf-8", errors="ignore")
            udfs = detect_udfs_in_source(rel, source_text)
            xml_loaders = detect_xml_loaders(rel, source_text)
            if udfs or xml_loaders:
                spark_ref = [{
                    "udfs": [
                        {"name": u.name, "class": u.class_name, "file": u.file,
                         "line": u.line, "type": u.registration_type}
                        for u in udfs
                    ],
                    "xml_loaders": [
                        {"xml_file": r.xml_file, "loader_file": r.loader_file,
                         "line": r.loader_line, "method": r.loader_method, "context": r.context}
                        for r in xml_loaders
                    ],
                }]
        except Exception as e:
            logger.warning("Spark cross-ref failed for %s: %s", rel, e)

    return FileAnalysis(
        path=rel, language=lang,
        symbols=[asdict(s) for s in syms],
        imports=[asdict(i) for i in imps],
        calls=[asdict(c) for c in calls],
        sql_stmts=sql_stmts,
        spark_cross_ref=spark_ref,
    )


def run_phase1(cfg: Config) -> dict:
    """Run Phase 1 structure extraction on all source files."""
    root = cfg.repo_path
    out = cfg.analysis_dir
    out.mkdir(parents=True, exist_ok=True)

    logger.info("[Phase 1] Extracting structure from %s ...", root)

    source_files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in EXT_TO_LANG:
                source_files.append(os.path.join(dirpath, fname))

    logger.info("  Found %d source files", len(source_files))

    if cfg.skip_tests:
        from repo_analyzer.extractors.base import is_test_file
        original = len(source_files)
        filtered = []
        for fpath in source_files:
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(5000)
                rel = os.path.relpath(fpath, str(root))
                if not is_test_file(rel, content):
                    filtered.append(fpath)
            except (OSError, PermissionError):
                filtered.append(fpath)
        source_files = filtered
        logger.info("  Skipped %d test files, remaining: %d", original - len(source_files), len(source_files))

    if len(source_files) > cfg.max_files:
        logger.info("  Capping at %d files", cfg.max_files)
        source_files = source_files[:cfg.max_files]

    all_analysis: list[dict] = []
    total_syms = 0
    errors = 0

    for i, fpath in enumerate(source_files):
        if (i + 1) % 100 == 0:
            logger.info("  Progress: %d/%d files ...", i + 1, len(source_files))
        result = analyze_file(fpath, str(root))
        all_analysis.append(asdict(result))
        total_syms += len(result.symbols)
        if result.error:
            errors += 1

    logger.info("  Enhancing call graph (callback detection) ...")
    from repo_analyzer.extractors.callback import enhance_call_graph
    callback_data = enhance_call_graph(all_analysis, str(root))
    cb_summary = callback_data["summary"]
    logger.info("    Function pointer fields: %d", cb_summary["func_pointer_fields"])
    logger.info("    Callback registrations: %d", cb_summary["callback_registrations"])
    logger.info("    Indirect calls: %d", cb_summary["indirect_calls"])
    logger.info("    Enhanced edges: %d", cb_summary["enhanced_edges"])

    modules: dict[str, list[dict]] = {}
    for fa in all_analysis:
        dir_name = os.path.dirname(fa["path"]) or "<root>"
        modules.setdefault(dir_name, []).append(fa)

    call_graph: list[dict] = []
    import_graph: list[dict] = []
    for fa in all_analysis:
        call_graph.extend(fa["calls"])
        import_graph.extend(fa["imports"])
    call_graph.extend(callback_data.get("enhanced_call_edges", []))

    summary = {
        "total_files_analyzed": len(all_analysis),
        "total_symbols": total_syms,
        "total_calls": len(call_graph),
        "errors": errors,
        "modules": {k: len(v) for k, v in modules.items()},
        "module_count": len(modules),
        "callback_detection": cb_summary,
    }

    out_file = out / "structure.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "summary": summary,
            "files": all_analysis,
            "module_groups": list(modules.keys()),
            "call_graph": call_graph[:5000],
            "import_graph": import_graph[:5000],
            "callback_data": {
                "dispatch_tables": callback_data.get("dispatch_tables", []),
                "func_pointer_fields": callback_data.get("func_pointer_fields", [])[:500],
                "callback_registrations": callback_data.get("callback_registrations", [])[:500],
                "indirect_calls": callback_data.get("indirect_calls", [])[:500],
            },
        }, f, indent=1, ensure_ascii=False)

    modules_dir = out / "modules"
    modules_dir.mkdir(exist_ok=True)
    for mod_name, files in modules.items():
        safe_name = mod_name.replace("/", "_").replace("\\", "_").replace(".", "_")
        mod_file = modules_dir / f"{safe_name}.json"
        mod_files_set = {fa["path"] for fa in files}
        mod_callbacks = {
            "dispatch_tables": [
                dt for dt in callback_data.get("dispatch_tables", [])
                if any(fp.get("file") in mod_files_set
                       for fp in callback_data.get("func_pointer_fields", [])
                       if fp.get("struct") == dt.get("struct"))
            ],
            "callback_registrations": [
                r for r in callback_data.get("callback_registrations", [])
                if r.get("file") in mod_files_set
            ],
            "indirect_calls": [
                ic for ic in callback_data.get("indirect_calls", [])
                if ic.get("file") in mod_files_set
            ],
        }
        with open(mod_file, "w", encoding="utf-8") as f:
            json.dump(
                {"module": mod_name, "files": files, "callbacks": mod_callbacks},
                f, indent=1, ensure_ascii=False,
            )

    logger.info("  Files analyzed: %d", summary["total_files_analyzed"])
    logger.info("  Symbols: %d", total_syms)
    logger.info("  Call edges: %d", len(call_graph))
    logger.info("  Modules: %d", summary["module_count"])
    logger.info("  -> Saved to %s", out_file)

    return summary
