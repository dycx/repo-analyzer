# Code Review Report — repo-analyzer

> **Date**: 2026-05-16
> **Reviewer**: Claude Code (automated)
> **Scope**: All 13 source files (7024 lines), cross-referenced with DEVELOPMENT_LOG.md

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 4 |
| HIGH | 14 |
| MEDIUM | 22 |
| **Total** | **40** |

---

## CRITICAL Issues

### C1. XSS in HTML report — unescaped heading text

**File**: `report_gen.py:254-256`

Heading text is inserted into `id` attribute and heading body without `html.escape()`. A malicious heading like `<script>alert(1)</script>` renders as raw HTML.

**Fix**: Always `html.escape()` the heading text before inline formatting, and escape the anchor value.

### C2. Mermaid securityLevel set to 'loose'

**File**: `report_gen.py:851`

`securityLevel: 'loose'` allows click events and JS execution in LLM-generated diagrams — a second XSS vector.

**Fix**: Use `securityLevel: 'strict'` or `'sandbox'`.

### C3. Swallowed exceptions hide real errors

**File**: `phase1_structure.py:938, 948`

`except Exception: pass` silently swallows all errors during embedded SQL extraction and Spark cross-reference extraction. Makes debugging impossible.

**Fix**: Log the exception instead of passing.

### C4. Silent file skip during output identification

**File**: `output_identification.py:479, 499`

`except (OSError, PermissionError): pass` during Layer 1/2 scans silently skips unreadable files.

**Fix**: Log the exception with file path.

---

## HIGH Issues

### H1. Double-walk bug in ALL 6 language extractors

**File**: `phase1_structure.py:242/318, 393/445, 525/624, 662/690`

Node types that don't `return` after processing fall through to generic child walk, causing **duplicate symbols and call edges** in the output. Affects Python, C/C++, Java, Scala extractors.

**Fix**: Add `return` after each handled case, or restructure with `elif` chains.

### H2. No recursion depth limit in AST walkers

**File**: `phase1_structure.py:221, 378, 494, 638, 704, 736`

All `_walk` functions recurse unbounded. A malformed file can crash with `RecursionError`.

**Fix**: Add `max_depth` parameter (default ~200), decrement on each recursive call.

### H3. temperature=0 silently ignored

**File**: `llm_client.py:166, 181`

`temperature or self.temperature` treats `0.0` as falsy, overriding explicit deterministic request. Same for `max_tokens`.

**Fix**: Use `temperature if temperature is not None else self.temperature`.

### H4. raise None when max_retries=0

**File**: `llm_client.py:149`

If `max_retries=0`, the loop never executes, `last_err` stays `None`, and `raise None` raises `TypeError`.

**Fix**: Guard with `if last_err is None: raise RuntimeError(...)`.

### H5. Import scoping bug in run_phase3

**File**: `main.py:603-606`

Cross-validation imports are inside `if struct_file.exists()` block but used unconditionally after. Crashes if `structure.json` doesn't exist.

**Fix**: Dedent imports to function body level.

### H6. Error placeholder pollutes Phase 3

**File**: `main.py:550-552`

Failed module analyses write `[analysis failed: ...]` to results, which gets passed to synthesis LLM as if real data.

**Fix**: Skip failed modules from results, or add a flag for downstream filtering.

### H7. Logic bug in phase25_cross_flows

**File**: `phase25_cross_flows.py:281-289`

Ground truth computation and imports are inside a loop body. Only the last iteration's value is used for `structured_ctx`.

**Fix**: Dedent lines 281-289 to be outside the loop.

### H8. Layer 2 "AST analysis" is fake

**File**: `output_identification.py:195-243, 489-498`

Layer 2 re-runs Layer 1 regex with lower confidence. The actual `_layer2_ast_scan` function is dead code.

**Fix**: Either implement real AST analysis or remove dead code and rename layer.

### H9. No HTTP connection reuse

**File**: `llm_client.py:124, 188`

New TCP connection per LLM request. 15+ module analyses = 15+ TLS handshakes.

**Fix**: Use persistent `httpx.Client` instance.

### H10. Return type mismatch

**File**: `pipeline_improvements.py:214`

`enhanced_validate` annotated `-> dict` but returns `ValidationResult`.

**Fix**: Change return type to `-> ValidationResult`.

### H11. Redundant JSON loading

**File**: `main.py:574, 610`

`structure.json` loaded twice in `run_phase3`.

**Fix**: Load once and reuse.

### H12. HTML injection in table cells

**File**: `report_gen.py:280`

`html.escape` runs before `_inline_format`, breaking markdown link conversion ordering.

**Fix**: Apply `_inline_format` first, then wrap in HTML.

### H13. Python import extraction incomplete

**File**: `phase1_structure.py:277-291`

`from os import path` not captured — only `dotted_name` nodes handled, `identifier` nodes missed.

**Fix**: Also collect `identifier` children as imported names.

### H14. Unbounded memory for large repos

**File**: `phase1_structure.py:1021-1031`

All file analyses held in memory plus duplicated call_graph/import_graph.

**Fix**: Stream results to disk or deduplicate.

---

## MEDIUM Issues

| # | Issue | File |
|---|-------|------|
| M1 | Dead code: `_REBUILD_GUIDE` nginx constant, never referenced | `main.py:841-912` |
| M2 | Incomplete `requirements.txt` — missing tree-sitter packages | `requirements.txt` |
| M3 | No automated test suite | project-wide |
| M4 | Sequential LLM calls in Phase 2 | `main.py:501-553` |
| M5 | `print()` instead of `logging` throughout | all files |
| M6 | `import re`/`import time` inside function bodies | `main.py`, `llm_client.py` |
| M7 | `import json as _json` despite module-level `json` | `main.py` |
| M8 | `__import__('time')` inline | `main.py:773` |
| M9 | Inconsistent indentation in `LLMClient.__init__` | `llm_client.py:89-98` |
| M10 | `sys.path.insert` inside runtime functions | `phase1_structure.py:726,839` |
| M11 | Parser object created per file instead of per language | `phase1_structure.py:916` |
| M12 | `_extract_python_params` misses `*args`, `**kwargs` | `phase1_structure.py:325-346` |
| M13 | Test file detection false positives | `phase1_structure.py:150-156` |
| M14 | Dead entries in `TEST_DIRS` and `_TEST_EXTENSIONS` | `phase1_structure.py:63,98-102` |
| M15 | Regex compiled inside function body on every call | `cross_validation.py:116` |
| M16 | Magic numbers without named constants | multiple files |
| M17 | `build_source_preview` reads entire large files | `main.py:125` |
| M18 | Callback regex matches any assignment | `callback_detection.py:67-68` |
| M19 | Indirect call matching by field name only | `callback_detection.py:373-384` |
| M20 | Accuracy score ignores table/UDF mismatches | `cross_validation.py:208-212` |
| M21 | `generate_html_report` is 465 lines | `report_gen.py:394-859` |
| M22 | Hardcoded CDN with no integrity hash | `report_gen.py:844` |

---

## Improvement Priorities

| Priority | Improvement | Effort | Impact |
|----------|-------------|--------|--------|
| P0 | Add pytest for core functions | 2-3 days | High |
| P0 | Fix double-walk bug in extractors | 1 day | High |
| P0 | Fix XSS in report_gen | 2 hours | High |
| P1 | Parallel module analysis | 1 day | High |
| P1 | Add recursion depth limit | 2 hours | Medium |
| P1 | Replace print() with logging | 1 day | Medium |
| P2 | Incremental analysis | 3-5 days | Medium |
| P2 | Better indirect call detection | 1 week | Medium |
| P3 | Multi-language support (Go, Rust, JS/TS) | 2-3 weeks | Medium |
| P3 | CI/CD integration | 1 week | Low |

---

## Fixes Applied in This PR

The following fixes from this review were applied on branch `fix/code-review-fixes`:

1. **C1+C2**: XSS fixes in `report_gen.py` — `html.escape()` on headings/anchors, Mermaid `securityLevel: 'strict'`
2. **C3+C4**: Replace `except Exception: pass` with logged warnings in `phase1_structure.py` and `output_identification.py`
3. **H3**: Fix `temperature=0` bug in `llm_client.py`
4. **H4**: Guard against `raise None` when `max_retries=0`
5. **H5**: Fix import scoping in `run_phase3`
6. **H6**: Skip failed modules from Phase 3 synthesis
7. **H7**: Fix loop-scoped imports in `phase25_cross_flows.py`
8. **H9**: Add persistent `httpx.Client` for connection reuse
9. **H10**: Fix return type annotation
10. **M1**: Delete dead `_REBUILD_GUIDE` constant
11. **M2**: Complete `requirements.txt`
12. **M7+M8**: Fix redundant local imports
13. **M9**: Fix inconsistent indentation in `LLMClient.__init__`
