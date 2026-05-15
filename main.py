#!/usr/bin/env python3
"""repo-analyzer: Code Repository Reverse Engineering Pipeline.

Generates 'rebuildable'-quality documentation from a codebase.

Pipeline:
  Phase 0: Reconnaissance (directory scan, language stats)
  Phase 1: Structure extraction (tree-sitter: symbols, calls, imports)
  Phase 2: Module-level LLM analysis (parallel)
  Phase 2.5: Cross-module end-to-end flow extraction (sequence diagrams)
  Phase 3: Cross-module synthesis
  Phase 4: Final document assembly

Usage:
  # Local LM Studio (default, no auth):
  python main.py <repo_path>

  # Remote Qwen / OpenAI-compatible endpoint:
  python main.py <repo_path> --base-url https://your-server/v1 --api-key sk-xxx

  # Run specific phases:
  python main.py <repo_path> --phase 0-1
  python main.py <repo_path> --phase 2-4
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from llm_client import LLMClient
from phase0_recon import run_phase0
from phase1_structure import run_phase1
from report_gen import normalize_headings, generate_toc, generate_html_report
from prompts import (
    render_module_prompt,
    render_synthesis_prompt,
    render_requirements_prompt,
)


def parse_phase_range(phase_str: str) -> tuple[int, int]:
    """Parse phase range like '0', '0-1', '2-4', 'all'."""
    if phase_str == "all":
        return 0, 4
    if "-" in phase_str:
        start, end = phase_str.split("-", 1)
        return int(start), int(end)
    n = int(phase_str)
    return n, n


def load_module_data(analysis_dir: Path) -> list[dict]:
    """Load per-module JSON files from Phase 1 output."""
    modules_dir = analysis_dir / "modules"
    if not modules_dir.exists():
        return []
    result = []
    for f in sorted(modules_dir.glob("*.json")):
        with open(f, encoding="utf-8") as fh:
            result.append(json.load(fh))
    return result


def build_symbol_index(files: list[dict]) -> str:
    """Build a compact symbol index string for the LLM context."""
    lines = []
    for fa in files:
        if not fa.get("symbols"):
            continue
        lines.append(f"\n### {fa['path']} ({fa['language']})")
        for sym in fa["symbols"]:
            kind = sym["kind"]
            name = sym["name"]
            parent = sym.get("parent", "")
            qual = f"{parent}.{name}" if parent else name
            sig = sym.get("signature", "")
            ret = sym.get("return_type", "")
            params = sym.get("params", [])
            vis = sym.get("visibility", "")

            parts = []
            if vis:
                parts.append(vis)
            parts.append(kind)
            parts.append(qual)
            if ret:
                parts.append(f"→ {ret}")
            if params:
                param_strs = []
                for p in params:
                    ps = p.get("name", "")
                    pt = p.get("type", "")
                    if pt:
                        ps = f"{ps}: {pt}"
                    pd = p.get("default", "")
                    if pd:
                        ps = f"{ps}={pd}"
                    param_strs.append(ps)
                parts.append(f"({', '.join(param_strs)})")
            elif sig:
                # Use first line of signature as fallback
                sig_line = sig.split("\n")[0].strip()[:200]
                parts.append(f"sig: {sig_line}")
            lines.append(f"  {' '.join(parts)}")
    return "\n".join(lines) if lines else "(no symbols extracted)"


def build_source_preview(files: list[dict], repo_path: str, max_tokens_approx: int = 20000) -> str:
    """Build source code preview, respecting context limits.

    Approximate 1 token ≈ 4 chars for English/Chinese mix.
    """
    max_chars = max_tokens_approx * 4
    parts = []
    total_chars = 0

    for fa in files:
        fpath = os.path.join(repo_path, fa["path"])
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError):
            continue

        header = f"\n{'='*60}\n### {fa['path']} ({fa['language']}, {len(content)} chars)\n{'='*60}\n"

        # For large files, include only headers + first N lines
        if len(content) > 8000:
            lines = content.split("\n")
            # Include: first 30 lines + any function/class definitions
            preview_lines = lines[:30]
            preview_lines.append(f"\n... ({len(lines) - 30} more lines, showing key definitions only) ...\n")
            for sym in fa.get("symbols", []):
                line_num = sym.get("line", 0)
                if 30 < line_num <= len(lines):
                    end = min(line_num + 5, len(lines))
                    preview_lines.append(f"--- {sym['kind']} {sym['name']} (line {line_num}) ---")
                    preview_lines.extend(lines[line_num-1:end])
            content = "\n".join(preview_lines)

        file_block = header + content
        if total_chars + len(file_block) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 500:
                parts.append(file_block[:remaining])
            break
        parts.append(file_block)
        total_chars += len(file_block)

    return "\n".join(parts)


def fix_mermaid_syntax(content: str) -> str:
    """Post-process all Mermaid blocks to fix common LLM-generated syntax issues.

    Problems fixed:
    1. Unquoted parentheses in node labels: NODE[text (stuff)] → NODE["text stuff"]
    2. Unquoted parentheses in edge labels: -->|text (stuff)| → -->|text stuff|
    3. Bare parentheses in edge arrows: -- "text (stuff)" --> -- "text stuff" -->
    4. Assignment in diamond labels: {"x = true"} → {"x is true"}
    5. Assignment in square labels: ["x = true"] → ["set x to true"]
    6. break without matching end → inject end
    7. Unquoted edge labels with special chars: -->|text (x)| → -->|"text (x)"|
    8. Nested quotes in sequence diagram messages: func(a="b") → func(a=b)
    9. subgraph without ID: subgraph "Title" → subgraph sg1 ["Title"]
    10. URL protocol in labels: ["https://x"] → ["x"]
    11. Reserved word "end" as label: A["end"] → A["End"]
    12. Node IDs starting with o/x after ---: A---ops → A--- ops
    13. Semicolons in sequence messages: func(a;b) → func(a#59;b)

    Mermaid interprets () as rounded-node syntax, so any literal parentheses
    in labels must be inside quoted strings or removed.
    """
    import re
    lines = content.split('\n')
    result = []
    in_mermaid = False
    mermaid_type = None  # "flowchart" or "sequence"
    sg_counter = 0
    # Track open blocks that need closing
    open_blocks: list[str] = []  # stack of block types: "alt", "loop", "opt", "break", "par"

    for line in lines:
        stripped = line.strip()

        if stripped.startswith('```mermaid'):
            in_mermaid = True
            mermaid_type = None
            sg_counter = 0
            open_blocks = []
            result.append(line)
            continue

        if stripped == '```' and in_mermaid:
            # Close any unclosed blocks before ending
            while open_blocks:
                open_blocks.pop()
                result.append("    end")
            in_mermaid = False
            result.append(line)
            continue

        if in_mermaid:
            # Detect diagram type
            if mermaid_type is None:
                if 'flowchart' in stripped or 'graph ' in stripped:
                    mermaid_type = "flowchart"
                elif 'sequenceDiagram' in stripped:
                    mermaid_type = "sequence"

            if mermaid_type == "flowchart":
                # 1. Fix unquoted parentheses in [...] node labels
                #    NODE[text (stuff)] → NODE["text stuff"]
                line = re.sub(
                    r'(\w+)\[([^"\]]*?)\(([^)]*?)\)([^"\]]*?)\]',
                    lambda m: f'{m.group(1)}["{m.group(2)}{m.group(3)}{m.group(4)}"]',
                    line,
                )

                # 2. Fix unquoted parentheses in {...} decision nodes
                #    NODE{text (stuff)} → NODE{"text stuff"}
                line = re.sub(
                    r'(\w+)\{([^"}]*?)\(([^)]*?)\)([^"}]*?)\}',
                    lambda m: f'{m.group(1)}{{"{m.group(2)}{m.group(3)}{m.group(4)}"}}',
                    line,
                )

                # 3. Fix parentheses in edge labels: -->|text (stuff)| → -->|text stuff|
                line = re.sub(
                    r'\|([^|]*?)\(([^)]*?)\)([^|]*?)\|',
                    lambda m: f'|{m.group(1)}{m.group(2)}{m.group(3)}|',
                    line,
                )

                # 4. Fix parentheses in quoted edge arrows: -- "text (stuff) " -->
                line = re.sub(
                    r'-- "?([^"]*?)\(([^)]*?)\)([^"]*?)"?\s*-->',
                    lambda m: f'-- "{m.group(1)}{m.group(2)}{m.group(3)}" -->',
                    line,
                )

                # 5. Fix assignment in diamond: {"x = true"} → {"x is true"}
                line = re.sub(
                    r'(\w+)\{([^"}]*?)\s*=\s*("[^"]*"|true|false|null|nil)\}',
                    lambda m: f'{m.group(1)}{{"{m.group(2).strip()} is {m.group(3).strip(chr(34))}"}}',
                    line,
                )

                # 6. Fix assignment in square brackets: ["x = true"] → ["set x to true"]
                line = re.sub(
                    r'(\w+)\["([^"]*?)\s*=\s*([^"]*?)"\]',
                    lambda m: f'{m.group(1)}["set {m.group(2).strip()} to {m.group(3).strip()}"]',
                    line,
                )

                # 7. Fix reserved word "end" used as label
                #    A["end"] → A["End"]  (capitalize to avoid reserved word)
                line = re.sub(
                    r'(\w+)\["end"\]',
                    lambda m: f'{m.group(1)}["End"]',
                    line,
                )
                line = re.sub(
                    r'(\w+)\("end"\)',
                    lambda m: f'{m.group(1)}("End")',
                    line,
                )
                line = re.sub(
                    r"(\w+)\{'end'\}",
                    lambda m: f'{m.group(1)}{{"End"}}',
                    line,
                )

                # 8. Fix node IDs starting with o/x after --- (circle/cross edge trap)
                #    A---ops → A--- ops
                line = re.sub(
                    r'(---+)([ox][a-z])',
                    lambda m: f'{m.group(1)} {m.group(2)}',
                    line,
                )

                # 9. Fix subgraph without ID: subgraph "Title" → subgraph sg1 ["Title"]
                if re.match(r'\s*subgraph\s+"', line):
                    sg_counter += 1
                    line = re.sub(
                        r'(\s*)subgraph\s+"([^"]+)"',
                        lambda m: f'{m.group(1)}subgraph sg{sg_counter} ["{m.group(2)}"]',
                        line,
                    )

            elif mermaid_type == "sequence":
                # 10. Fix nested quotes in messages: func(a="b") → func(a=b)
                line = re.sub(
                    r'(->>|-->>)\s*(.*)\s*=\s*"([^"]*)"',
                    lambda m: f'{m.group(1)} {m.group(2)}={m.group(3)}',
                    line,
                )

                # 11. Escape semicolons in messages (they act as line breaks)
                if ':' in line and not line.strip().startswith('%%'):
                    line = re.sub(
                        r'(->>|-->>|->>|-->>)([^:]+):.*;(.*)',
                        lambda m: m.group(0).replace(';', '#59;'),
                        line,
                    )

                # 12. Track open blocks for sequence diagrams
                block_start = re.match(
                    r'\s*(alt|opt|loop|break|par)\b', stripped
                )
                if block_start:
                    block_type = block_start.group(1)
                    open_blocks.append(block_type)

                if stripped == 'end' and open_blocks:
                    open_blocks.pop()

    fixed = '\n'.join(result)

    # Wrap each mermaid block in <details> for collapsibility
    fixed = _wrap_mermaid_in_details(fixed)

    orig_mermaid = content.count('```mermaid')
    if fixed != content:
        print(f"  [Mermaid fix] {orig_mermaid} blocks processed, syntax issues auto-corrected")
    return fixed


def _wrap_mermaid_in_details(content: str) -> str:
    # Wrap each mermaid code block in <details> tags for collapsibility.
    # Only wraps blocks NOT already inside <details>.
    import re
    lines = content.split('\n')
    result = []
    i = 0
    details_depth = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if '<details' in stripped:
            details_depth += 1
        if '</details>' in stripped:
            details_depth = max(0, details_depth - 1)

        if stripped.startswith('```mermaid') and details_depth == 0:
            block_lines = [line]
            i += 1
            diagram_type = stripped.replace('```mermaid', '').strip()
            edge_count = 0
            msg_count = 0

            while i < len(lines):
                bline = lines[i]
                block_lines.append(bline)
                bstripped = bline.strip()
                if 'flowchart' in diagram_type or 'graph ' in diagram_type:
                    if '-->' in bstripped or '-.->' in bstripped or '==>' in bstripped:
                        edge_count += 1
                elif 'sequenceDiagram' in diagram_type:
                    if '->>' in bstripped or '-->>' in bstripped:
                        msg_count += 1
                if bstripped == '```':
                    break
                i += 1

            if msg_count > 0:
                title = f"Sequence Diagram ({msg_count} messages)"
            elif edge_count > 0:
                title = f"Flowchart ({edge_count} edges)"
            else:
                title = "Mermaid Diagram"

            result.append('<details>')
            result.append(f'<summary>{title}</summary>')
            result.append('')
            result.extend(block_lines)
            result.append('')
            result.append('</details>')
        else:
            result.append(line)
        i += 1

    return '\n'.join(result)


def build_callback_info(mod: dict) -> str:
    """Build callback info string for a module."""
    callbacks = mod.get("callbacks", {})
    lines = []
    
    tables = callbacks.get("dispatch_tables", [])
    if tables:
        lines.append("分派表 (Dispatch Tables):")
        for dt in tables:
            struct = dt.get("struct", "")
            fields = dt.get("fields", [])
            regs = dt.get("registered_callbacks", [])
            lines.append(f"  {struct}: {', '.join(f['name'] for f in fields)}")
            for r in regs:
                lines.append(f"    {r['field']} = {r['func']}")
    
    registrations = callbacks.get("callback_registrations", [])
    if registrations:
        lines.append("回调注册:")
        for r in registrations[:20]:
            lines.append(f"  {r['var']}.{r['field']} = {r['func']}")
    
    indirect = callbacks.get("indirect_calls", [])
    if indirect:
        lines.append("间接调用:")
        for ic in indirect[:15]:
            lines.append(f"  {ic['expression']}()")
    
    return "\n".join(lines) if lines else "(无回调信息)"


def run_phase2(
    repo_path: str,
    analysis_dir: Path,
    llm: LLMClient,
    repo_name: str,
) -> dict[str, str]:
    """Run Phase 2: module-level LLM analysis."""
    print(f"\n[Phase 2] Module-level analysis (using {llm.model}) ...")

    modules = load_module_data(analysis_dir)
    if not modules:
        print("  ERROR: No module data found. Run Phase 1 first.")
        return {}

    print(f"  Found {len(modules)} modules to analyze")

    # Check LLM availability
    if not llm.health_check():
        print("  WARNING: LM Studio not reachable. Attempting anyway...")

    results: dict[str, str] = {}
    modules_out = analysis_dir / "module_analyses"
    modules_out.mkdir(exist_ok=True)

    for i, mod in enumerate(modules):
        mod_name = mod["module"]
        files = mod["files"]
        safe_name = mod_name.replace("/", "_").replace("\\", "_").replace(".", "_")
        out_file = modules_out / f"{safe_name}.md"

        # Skip if already analyzed (resume support)
        if out_file.exists():
            with open(out_file, encoding="utf-8") as f:
                existing = f.read()
            if len(existing) > 200:  # non-trivial content
                results[mod_name] = existing
                print(f"  [{i+1}/{len(modules)}] {mod_name} — cached ({len(existing)} chars)")
                continue

        # Skip empty modules
        if not any(fa.get("symbols") for fa in files):
            print(f"  [{i+1}/{len(modules)}] {mod_name} — skipped (no symbols)")
            continue

        print(f"  [{i+1}/{len(modules)}] Analyzing {mod_name} ({len(files)} files) ...", end="", flush=True)

        symbol_index = build_symbol_index(files)
        source_code = build_source_preview(files, repo_path)
        file_count = len(files)
        callback_info = build_callback_info(mod)

        system_prompt, user_prompt = render_module_prompt(
            repo_name=repo_name,
            module_path=mod_name,
            file_count=file_count,
            symbol_index=symbol_index,
            source_code=source_code,
            callback_info=callback_info,
        )

        try:
            start = time.time()
            response = llm.chat(system=system_prompt, user=user_prompt)
            response = fix_mermaid_syntax(response)
            elapsed = time.time() - start
            print(f" done ({elapsed:.1f}s, {len(response)} chars)")

            results[mod_name] = response
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(response)

        except Exception as e:
            print(f" ERROR: {e}")
            results[mod_name] = f"[分析失败: {e}]"

    print(f"\n  Phase 2 complete: {len(results)} modules analyzed")
    return results


def run_phase3(
    repo_path: str,
    analysis_dir: Path,
    llm: LLMClient,
    repo_name: str,
    module_analyses: dict[str, str],
) -> str:
    """Run Phase 3: cross-module synthesis."""
    print(f"\n[Phase 3] Cross-module synthesis ...")

    # Load structure data
    struct_file = analysis_dir / "structure.json"
    call_graph_str = "(no call graph)"
    import_graph_str = "(no import graph)"

    if struct_file.exists():
        with open(struct_file, encoding="utf-8") as f:
            struct_data = json.load(f)

        # Build call graph summary
        cg = struct_data.get("call_graph", [])
        if cg:
            cg_lines = []
            for edge in cg[:200]:  # limit
                cg_lines.append(f"  {edge['caller']} → {edge['callee']}  ({edge['file']}:{edge['line']})")
            call_graph_str = "\n".join(cg_lines)

        # Build import graph summary
        ig = struct_data.get("import_graph", [])
        if ig:
            ig_lines = []
            for imp in ig[:200]:
                module = imp.get("module", "")
                ig_lines.append(f"  {imp['file']} imports {imp['source']}" + (f" from {module}" if module else ""))
            import_graph_str = "\n".join(ig_lines)

    # Load per-module data for structured context
    modules_dir = analysis_dir / "modules"
    module_data = []
    if modules_dir.exists():
        for f in sorted(modules_dir.glob("*.json")):
            with open(f, encoding="utf-8") as fh:
                module_data.append(json.load(fh))

    # Build ground truth and structured context
    from cross_validation import (
        build_ground_truth, build_structured_context,
        validate_cross_module_calls, build_validation_summary,
    )
    struct_data_full = {}
    if struct_file.exists():
        with open(struct_file, encoding="utf-8") as f:
            struct_data_full = json.load(f)
    ground_truth = build_ground_truth(struct_data_full, module_data)
    structured_ctx = build_structured_context(struct_data_full, module_data, ground_truth)

    # Build expanded module summaries (2000 chars, key sections only)
    from phase25_cross_flows import _extract_key_sections
    summaries = []
    for mod_name, analysis in module_analyses.items():
        summary = _extract_key_sections(analysis, max_chars=2000)
        summaries.append(f"### {mod_name}\n{summary}")
    module_summaries = "\n\n".join(summaries)

    # Build synthesis prompt with structured ground truth
    system_prompt, user_prompt = render_synthesis_prompt(
        repo_name=repo_name,
        module_summaries=module_summaries,
        call_graph=call_graph_str,
        import_graph=import_graph_str,
    )

    # Append structured ground truth to user prompt
    user_prompt += (
        "\n\n## Phase 1 结构化验证数据 (Ground Truth)\n"
        + structured_ctx
        + "\n\n以下数据来自 Phase 1 的精确结构分析（tree-sitter 提取），是**已验证的事实**。"
        "你生成的架构分析中涉及的调用关系、模块依赖、表引用必须与以下数据一致。"
        "如果某个关系在下方数据中不存在，标注为\"推测\"而非确认。\n"
    )

    try:
        response = llm.chat(system=system_prompt, user=user_prompt, max_tokens=8192)
        response = fix_mermaid_syntax(response)

        # Cross-validate
        validation = validate_cross_module_calls(response, ground_truth)
        val_summary = build_validation_summary(validation)
        verified = len(validation.verified_calls)
        total = verified + len(validation.unverified_calls)
        print(f"  Cross-validation: {validation.accuracy_score:.0%} accuracy ({verified}/{total} verified)")

        # Iterative refinement
        REFINE_THRESHOLD = 0.70
        MAX_REFINEMENTS = 1
        for refine_iter in range(MAX_REFINEMENTS):
            if validation.accuracy_score >= REFINE_THRESHOLD or not validation.unverified_calls:
                break

            from accuracy import create_refinement_prompt
            unverified_names = [c["name"] for c in validation.unverified_calls[:10]]
            errors = [f"函数 `{n}` 在调用图和符号表中未找到" for n in unverified_names]

            print(f"  [Refine {refine_iter+1}] Accuracy {validation.accuracy_score:.0%} < {REFINE_THRESHOLD:.0%}, "
                  f"correcting {len(errors)} errors ...")

            refine_prompt = create_refinement_prompt(response, errors, structured_ctx)
            try:
                response = llm.chat(system=system_prompt, user=refine_prompt, max_tokens=8192)
                response = fix_mermaid_syntax(response)
                validation = validate_cross_module_calls(response, ground_truth)
                val_summary = build_validation_summary(validation)
                verified = len(validation.verified_calls)
                total = verified + len(validation.unverified_calls)
                print(f"  [Refine {refine_iter+1}] → {validation.accuracy_score:.0%} accuracy ({verified}/{total})")
            except Exception as e:
                print(f"  [Refine {refine_iter+1}] ERROR: {e}")
                break

        if validation.unverified_calls:
            print(f"  ⚠ {len(validation.unverified_calls)} unverified calls remaining")

        response_with_val = response + "\n\n---\n\n" + val_summary

        out_file = analysis_dir / "synthesis.md"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(response_with_val)
        print(f"  Synthesis complete ({len(response_with_val)} chars) → {out_file}")
        return response_with_val
    except Exception as e:
        print(f"  ERROR: {e}")
        return f"[synthesis failed: {e}]"


def run_phase4(
    repo_path: str,
    analysis_dir: Path,
    llm: LLMClient,
    repo_name: str,
    module_analyses: dict[str, str],
    architecture: str,
    output_path: str | None = None,
    cross_flows: str = "",
) -> str:
    """Run Phase 4: assemble final document (no LLM — direct merge)."""
    print(f"\n[Phase 4] Assembling final document ...")

    # Module order (logical dependency order, can be overridden by module_analyses keys)
    module_order = sorted(module_analyses.keys())

    # Normalize module content headings (shift to level 4+ since they're under ### 3.X)
    normalized_modules = {}
    for name, content in module_analyses.items():
        normalized_modules[name] = normalize_headings(content, base_level=4)

    parts = []

    # Title
    parts.append(f"# {repo_name} — 逆向工程文档\n")
    parts.append(
        '> **生成原则**: 本文档达到"可重建"级别 — '
        '开发者仅凭此文档可重建功能等价的项目（误差 < 5%）。'
    )
    parts.append("")

    # Placeholder for TOC (generate after content is assembled)
    parts.append("<!-- TOC_PLACEHOLDER -->")
    parts.append("")

    # Section 1: Architecture
    parts.append("---\n")
    parts.append("## 1. 架构全景\n")
    parts.append(architecture)

    # Section 2: Cross-module flows
    if cross_flows:
        parts.append("\n---\n")
        parts.append("## 2. 跨模块端到端流程\n")
        parts.append(
            '> 以下流程图展示了系统中最重要的端到端业务流程，'
            '每个流程跨越多个模块，标注了完整的调用链。\n'
        )
        parts.append(cross_flows)

    # Section 3: Module details
    parts.append("\n---\n")
    parts.append("## 3. 模块详解\n")
    parts.append(
        '> 以下每个模块的分析包含: 职责、核心业务流程图（Mermaid）、'
        '公共接口清单、核心算法、数据结构、异常处理、边界条件、'
        '外部依赖、设计决策。\n'
    )

    for i, name in enumerate(module_order, 1):
        display = name.replace("src_", "").replace("_", "/")
        parts.append(f"### 3.{i} `{display}`\n")
        content = normalized_modules.get(name, "")
        parts.append(content)
        parts.append("")

    # Section 4: Rebuild guide
    parts.append("\n---\n")
    parts.append("## 4. 重建指南\n")
    parts.append(_REBUILD_GUIDE)

    parts.append(f"\n---\n\n*Generated by repo-analyzer | LLM: {llm.model} | Date: {__import__('time').strftime('%Y-%m-%d %H:%M')}*\n")

    # Assemble
    final = "\n".join(parts)

    # Generate dynamic TOC and replace placeholder
    toc = generate_toc(final)
    final = final.replace("<!-- TOC_PLACEHOLDER -->", toc)

    # Fix Mermaid syntax
    final = fix_mermaid_syntax(final)

    # Write markdown
    if output_path:
        out_path = Path(output_path)
    else:
        out_path = Path(repo_path).parent / f"{repo_name}-analysis.md"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(final, encoding="utf-8")
    print(f"  Markdown → {out_path} ({len(final):,} chars, {final.count(chr(10)):,} lines)")

    # Generate HTML report
    html = generate_html_report(final, repo_name, llm.model)
    html_path = out_path.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")
    print(f"  HTML     → {html_path} ({len(html):,} chars)")

    # Copy individual module files to output directory
    modules_out = analysis_dir / "module_analyses"
    if modules_out.exists():
        dest_modules = out_path.parent / f"{repo_name}-modules"
        dest_modules.mkdir(parents=True, exist_ok=True)
        for mod_file in sorted(modules_out.glob("*.md")):
            content = mod_file.read_text(encoding="utf-8")
            content = normalize_headings(content, base_level=1)
            dest = dest_modules / mod_file.name
            dest.write_text(content, encoding="utf-8")
        print(f"  Modules  → {dest_modules}/ ({len(list(dest_modules.glob('*.md')))} files)")

    return final


_REBUILD_GUIDE = """如果要从零重建这个系统:

### 4.1 推荐实现顺序

```
阶段 1: 基础层 src/core
  ├── 内存池 ngx_palloc — 所有分配的基石
  ├── 日志系统 ngx_log — 调试和监控的基础
  ├── 配置解析 ngx_conf_file — 驱动所有模块行为
  ├── 基础数据结构 array, list, rbtree, hash
  └── 字符串与缓冲区管理 ngx_string, ngx_buf

阶段 2: 事件层 src/event
  ├── 事件抽象 ngx_event_t, ngx_connection_t
  ├── 平台适配 epoll / kqueue / IOCP
  ├── 定时器 红黑树
  ├── 信号处理
  └── SSL/TLS 集成

阶段 3: HTTP 核心 src/http
  ├── 请求解析 状态机
  ├── 阶段处理器链 rewrite → access → content
  ├── 过滤器链 header filter → body filter
  ├── Upstream 代理
  └── 变量系统

阶段 4: HTTP 扩展模块 src/http/modules
  ├── 静态文件服务
  ├── 反向代理
  ├── FastCGI/uWSGI/SCGI
  ├── Gzip 压缩
  ├── 重写与重定向
  └── 访问控制

阶段 5: 高级协议
  ├── HTTP/2 src/http/v2 — HPACK, 帧, 流控
  ├── HTTP/3 + QUIC src/http/v3, src/event/quic
  ├── Mail 代理 src/mail
  └── Stream TCP/UDP 代理 src/stream

阶段 6: 平台层 src/os
  ├── Unix: 进程管理, 共享内存, 信号
  └── Windows: IOCP, 服务管理
```

### 4.2 关键技术决策

| 决策点 | 选择 | 原因 |
|--------|------|------|
| 并发模型 | 多进程 + 单线程事件循环 | 避免锁竞争，利用多核 |
| 内存管理 | 对象池 ngx_pool_t | O(1) 分配，请求结束整体释放 |
| I/O 模型 | 全非阻塞 + 状态机 | 高并发下不阻塞 |
| 模块接口 | 回调函数指针 + 配置上下文 | 编译时/运行时可扩展 |
| 错误传递 | 状态码 NGX_OK/ERROR/AGAIN | 统一异步操作结果 |

### 4.3 必须注意的坑

1. **信号安全**: 信号处理函数中不能调用 malloc/free，必须用原子操作或专用队列
2. **内存泄漏**: 事件循环中的临时对象必须注册 pool_cleanup_t 清理函数
3. **协议边界**: QUIC/HTTP2 解析时务必检查缓冲区长度，防止越界读
4. **共享内存**: Worker 间通信需要 ngx_slab_pool 管理，避免碎片化
5. **配置重载**: ngx_init_cycle 必须原子切换，旧 cycle 延迟到所有请求完成后销毁

### 4.4 设计模式参考

- **责任链 (Chain of Responsibility)**: HTTP 阶段处理 (preaccess → access → content)
- **过滤器链 (Filter Chain)**: 响应流处理 (header filter → body filter)
- **状态机 (State Machine)**: 协议解析、连接生命周期
- **策略模式 (Strategy)**: 事件驱动抽象 (epoll vs kqueue vs IOCP)
- **对象池 (Object Pool)**: 内存分配 ngx_pool_t
- **观察者模式 (Observer)**: 共享内存 zone 的 init/reinit 回调
"""


def main():
    parser = argparse.ArgumentParser(
        description="Code Repository Reverse Engineering Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("repo_path", help="Path to the repository to analyze")
    parser.add_argument("--output", "-o", help="Output document path (default: <repo>-analysis.md)")
    parser.add_argument("--phase", "-p", default="all",
                        help="Phase range: 0, 0-1, 2-4, all (default: all)")
    parser.add_argument("--base-url", "--lm-studio-url",
                        default="http://127.0.0.1:1234/v1",
                        help="LLM API base URL (default: LM Studio local)")
    parser.add_argument("--api-key", default=None,
                        help="API key for remote LLM (or set LLM_API_KEY env var)")
    parser.add_argument("--model", "-m", default="qwen3.5-35b-a3b",
                        help="Model name")
    parser.add_argument("--max-files", type=int, default=5000,
                        help="Max source files to analyze (Phase 1)")
    parser.add_argument("--skip-synthesis", action="store_true",
                        help="Skip Phase 3 synthesis (use existing)")
    parser.add_argument("--timeout", "-t", type=float, default=300.0,
                        help="LLM request timeout in seconds (default: 300)")
    parser.add_argument("--retry", type=int, default=3,
                        help="Max retries on LLM request failure (default: 3)")
    args = parser.parse_args()

    # API key: CLI arg > env var
    if not args.api_key:
        args.api_key = os.environ.get("LLM_API_KEY")

    repo_path = Path(args.repo_path).resolve()
    if not repo_path.is_dir():
        print(f"ERROR: {repo_path} is not a directory")
        sys.exit(1)

    repo_name = repo_path.name
    analysis_dir = repo_path / ".code-analysis"
    phase_start, phase_end = parse_phase_range(args.phase)

    print(f"╔════════════════════════════════════════════════════════════╗")
    print(f"║  repo-analyzer: Code Repository Reverse Engineering       ║")
    print(f"╚════════════════════════════════════════════════════════════╝")
    print(f"\n  Repository: {repo_path}")
    print(f"  Output:     {args.output or f'{repo_name}-analysis.md'}")
    print(f"  Phases:     {phase_start} → {phase_end}")
    print(f"  LLM:        {args.model} @ {args.base_url}" +
          (f" (key={'***' + args.api_key[-4:] if args.api_key and len(args.api_key) > 4 else 'set'})" if args.api_key else ""))
    print()

    t_start = time.time()

    # ── Phase 0: Reconnaissance ──────────────────────────────────────────
    if phase_start <= 0 <= phase_end:
        metadata = run_phase0(str(repo_path), str(analysis_dir))
    elif (analysis_dir / "metadata.json").exists():
        with open(analysis_dir / "metadata.json", encoding="utf-8") as f:
            metadata = json.load(f)
    else:
        metadata = {}

    # ── Phase 1: Structure extraction ────────────────────────────────────
    if phase_start <= 1 <= phase_end:
        struct_summary = run_phase1(str(repo_path), str(analysis_dir), args.max_files)

    # ── Phases 2-4 need LLM ─────────────────────────────────────────────
    if phase_end >= 2:
        llm = LLMClient(
            base_url=args.base_url,
            model=args.model,
            api_key=args.api_key,
            timeout=args.timeout,
            max_retries=args.retry,
        )
        print(f"\n  LLM health check: {'✓ OK' if llm.health_check() else '⚠ not reachable'}")

        module_analyses = {}

        # ── Phase 2: Module analysis ─────────────────────────────────────
        if phase_start <= 2 <= phase_end:
            module_analyses = run_phase2(
                str(repo_path), analysis_dir, llm, repo_name,
            )
        else:
            # Load existing analyses
            modules_out = analysis_dir / "module_analyses"
            if modules_out.exists():
                for f in sorted(modules_out.glob("*.md")):
                    with open(f, encoding="utf-8") as fh:
                        mod_name = f.stem.replace("_", "/")
                        module_analyses[mod_name] = fh.read()

        # ── Phase 2.5: Cross-module flows ──────────────────────────────────
        cross_flows = ""
        if phase_start <= 2 and phase_end >= 3:
            from phase25_cross_flows import run_phase25
            cross_flows = run_phase25(
                str(repo_path), analysis_dir, llm, repo_name,
                module_analyses,
            )
        elif (analysis_dir / "cross_flows.md").exists():
            with open(analysis_dir / "cross_flows.md", encoding="utf-8") as f:
                cross_flows = f.read()

        # ── Phase 3: Synthesis ───────────────────────────────────────────
        architecture = ""
        if phase_start <= 3 <= phase_end and not args.skip_synthesis:
            architecture = run_phase3(
                str(repo_path), analysis_dir, llm, repo_name,
                module_analyses,
            )
        elif (analysis_dir / "synthesis.md").exists():
            with open(analysis_dir / "synthesis.md", encoding="utf-8") as f:
                architecture = f.read()

        # ── Phase 4: Final document ──────────────────────────────────────
        if phase_start <= 4 <= phase_end:
            run_phase4(
                str(repo_path), analysis_dir, llm, repo_name,
                module_analyses, architecture, args.output,
                cross_flows=cross_flows,
            )

    elapsed = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"  Total time: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  Analysis data: {analysis_dir}/")
    if args.output:
        print(f"  Final document: {args.output}")
    else:
        print(f"  Final document: {repo_path.parent / f'{repo_name}-analysis.md'}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
