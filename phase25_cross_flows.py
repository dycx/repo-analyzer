"""Phase 2.5: Cross-module end-to-end flow extraction.

Identifies key business flows that span multiple modules and generates
Mermaid sequence diagrams showing the complete path from input to output.

Uses:
- Enhanced call graph (direct + indirect/callback edges)
- Module analyses (Phase 2 results)
- Dispatch tables (function pointer patterns)
"""

import json
from pathlib import Path
from llm_client import LLMClient


CROSS_FLOW_SYSTEM = """你是一位资深系统架构师。你的任务是从代码分析中识别跨模块的端到端业务流程，并生成精确的时序图。

**核心原则**: 每个流程图必须回答:
- 输入了什么（什么数据/事件触发）
- 经过了哪些模块的哪些函数
- 每一步做了什么转换/处理
- 最终输出了什么

**Mermaid Sequence Diagram 语法约束 (严格遵守，违反将导致渲染失败):**

1. **participants 数量 ≤ 6** — 超过则合并为模块级别:
   ✅ `participant HTTP as "HTTP Module"` (模块级)
   ❌ `participant A as "ngx_http_init"` (函数级，太细)

2. **消息数 ≤ 15 条** — 超过则合并内部步骤:
   ✅ `Client->>HTTP: process_request(req)` (合并)
   ❌ 8 条消息分别展示 parse/validate/cache/check... (太细)
   - 内部细节用 `Note right of X: description` 补充

3. **只展示跨模块调用** — 模块内部调用用 flowchart 展示，时序图只画模块边界:
   ✅ `HTTP->>Event: add_read_event(c)`
   ❌ `HTTP->>HTTP: parse_header()` (同模块内部调用)

4. **消息标签禁止嵌套引号**:
   ✅ `A->>B: func(arg=value)`  ❌ `A->>B: func(arg="value")`

5. **break 必须有匹配的 end**:
   ✅ `break error` / `end`  ❌ `break error` (缺 end)
   - break 块内至少 1 条消息

6. **alt/else 必须有匹配的 end**:
   ```
   alt success
       ...
   else error
       ...
   end
   ```

7. **回调/函数指针简化为模块级调度**:
   ✅ `Event->>Handler: via dispatch_table.process_event`
   ❌ 展示完整的回调注册链路

8. **participant 用 as 别名，标签用引号**:
   ✅ `participant A as "HTTP Module"`  ❌ `participant HTTP_Module`

9. **嵌套块规则** — 所有块类型可互相嵌套，每层必须有 end:
   ```
   alt condition
       loop every second
           A->>B: poll
           opt has_data
               B-->>A: response
           end
       end
   else error
       break fatal
           A->>B: abort
       end
   end
   ```

10. **实体编码** — 特殊字符必须转义:
    `#quot;` = `"`  `#59;` = `;`  `#amp;` = `&`

11. **分号陷阱** — 消息中的 `;` 会被解析为换行符，必须转义:
    ✅ `A->>B: config #59; key=value`  ❌ `A->>B: config; key=value`

12. **rect 块** — 用于背景高亮:
    ```
    rect rgb(200, 255, 200)
        A->>B: highlighted flow
    end
    ```

13. **line break** — 消息和注释中用 `<br/>` 换行:
    ✅ `Note over A,B: line1<br/>line2`"""

CROSS_FLOW_USER = """## 项目: {repo_name}

## 系统调用图 (关键调用关系)
{call_graph}

## 模块分析摘要
{module_summaries}

## 分派表/回调注册 (C函数指针模式)
{dispatch_tables}

## Phase 1 结构化验证数据 (Ground Truth)
{structured_context}

以下数据来自 Phase 1 的精确结构分析（tree-sitter 提取），是**已验证的事实**。
你生成的流程图中涉及的调用关系、表引用、UDF 必须与以下数据一致。
如果某个调用关系在下方数据中不存在，标注为"推测"而非确认。

---

请识别这个系统中最重要的 3-5 个端到端业务流程，为每个流程生成 Mermaid 时序图。

**选择标准**:
1. 最核心的业务流程（如: 请求处理、配置加载、Worker启动等）
2. 必须跨越至少 2 个模块
3. 只展示跨模块调用 — 模块内部的函数调用不要出现在时序图中

**简化原则** (核心):
- **participants ≤ 5** — 用模块名而非函数名作为参与者
- **消息 ≤ 10 条** — 大幅合并，每个模块只保留 1-2 条关键消息
- **内部步骤用 Note 补充** — 不要拆成独立消息
- **回调链路简化** — 只展示最终分发目标，不展示注册过程
- **标签 ≤ 20 字符** — 去掉参数详情，只保留函数名
- **用 `<details>` 折叠标签包裹每个时序图**

**输出格式** (每个流程):

## 流程 X: [流程名称]

**触发条件**: [什么事件/输入触发]
**涉及模块**: [模块1, 模块2, ...]
**最终输出**: [结果/副作用]

<details>
<summary>流程名称 (N messages)</summary>

\`\`\`mermaid
sequenceDiagram
    participant A as "ModuleA"
    participant B as "ModuleB"
    participant C as "ModuleC"
    
    A->>B: handle(req)
    Note right of B: validate, route
    B->>C: process(req)
    C-->>B: resp
    B-->>A: result
\`\`\`

</details>

**关键步骤说明**:
1. [步骤1]: 解释
2. [步骤2]: ...

---

请用中文输出，技术术语保留英文。"""


def build_callback_summary(module_data: list[dict]) -> str:
    """Build a summary of callback/dispatch table information."""
    lines = []
    
    for mod in module_data:
        callbacks = mod.get("callbacks", {})
        tables = callbacks.get("dispatch_tables", [])
        registrations = callbacks.get("callback_registrations", [])
        indirect = callbacks.get("indirect_calls", [])
        
        if not tables and not registrations and not indirect:
            continue
        
        lines.append(f"\n### {mod['module']}")
        
        if tables:
            lines.append("**分派表 (Dispatch Tables):**")
            for dt in tables:
                struct = dt.get("struct", "")
                fields = dt.get("fields", [])
                regs = dt.get("registered_callbacks", [])
                lines.append(f"- `{struct}` ({len(fields)} 个函数指针字段)")
                for f in fields[:10]:
                    lines.append(f"  - `{f['name']}` → {f.get('type', '?')}")
                if regs:
                    lines.append(f"  - 已注册回调:")
                    for r in regs[:10]:
                        lines.append(f"    - `{r['field']}` = `{r['func']}`")
        
        if registrations:
            lines.append("**回调注册:**")
            for r in registrations[:20]:
                lines.append(
                    f"  - `{r['var']}.{r['field']}` = `{r['func']}` @ {r['file']}:{r['line']}"
                )
        
        if indirect:
            lines.append("**间接调用:**")
            for ic in indirect[:15]:
                lines.append(f"  - `{ic['expression']}()` @ {ic['file']}:{ic['line']}")
    
    return "\n".join(lines) if lines else "(无回调信息)"


def run_phase25(
    repo_path: str,
    analysis_dir: Path,
    llm: LLMClient,
    repo_name: str,
    module_analyses: dict[str, str],
) -> str:
    """Run Phase 2.5: cross-module flow extraction."""
    print(f"\n[Phase 2.5] Cross-module flow extraction ...")
    
    # Load structure data for call graph
    struct_file = analysis_dir / "structure.json"
    call_graph_str = "(no call graph)"
    dispatch_str = "(no dispatch tables)"
    
    if struct_file.exists():
        with open(struct_file, encoding="utf-8") as f:
            struct_data = json.load(f)
        
        # Build call graph summary (direct + indirect)
        cg = struct_data.get("call_graph", [])
        if cg:
            cg_lines = []
            for edge in cg[:300]:
                if edge.get("type") == "indirect":
                    cg_lines.append(
                        f"  {edge['caller']} --> {edge['callee']}  "
                        f"[间接调用 via {edge.get('field', '?')}] ({edge['file']}:{edge['line']})"
                    )
                else:
                    cg_lines.append(
                        f"  {edge['caller']} --> {edge['callee']}  ({edge['file']}:{edge['line']})"
                    )
            call_graph_str = "\n".join(cg_lines)
        
        # Load dispatch tables
        callback_data = struct_data.get("callback_data", {})
        tables = callback_data.get("dispatch_tables", [])
        if tables:
            dt_lines = []
            for dt in tables:
                struct = dt.get("struct", "")
                fields = dt.get("fields", [])
                regs = dt.get("registered_callbacks", [])
                dt_lines.append(f"\n**{struct}** ({len(fields)} fields):")
                for f in fields:
                    dt_lines.append(f"  - {f['name']}: {f.get('type', '?')}")
                for r in regs:
                    dt_lines.append(f"  - {r['field']} = {r['func']}")
            dispatch_str = "\n".join(dt_lines)
    
    # Load per-module data (structure + Phase 2 analyses)
    modules_dir = analysis_dir / "modules"
    module_data = []
    if modules_dir.exists():
        for f in sorted(modules_dir.glob("*.json")):
            with open(f, encoding="utf-8") as fh:
                module_data.append(json.load(fh))

    # Build ground truth from Phase 1
    from cross_validation import (
        build_ground_truth, build_structured_context,
        validate_cross_module_calls, build_validation_summary,
    )
    ground_truth = build_ground_truth(struct_data, module_data)

    # Build structured context (replaces truncated text summaries)
    structured_ctx = build_structured_context(struct_data, module_data, ground_truth)

    # Build module analysis summaries (expanded: 2000 chars instead of 800)
    summaries = []
    for mod_name, analysis in module_analyses.items():
        # Extract key sections: 职责, 公共接口, 核心流程
        summary = _extract_key_sections(analysis, max_chars=2000)
        summaries.append(f"### {mod_name}\n{summary}")
    module_summaries = "\n\n".join(summaries)

    callback_summary = build_callback_summary(module_data)

    # Call LLM with structured ground truth
    system_prompt = CROSS_FLOW_SYSTEM
    user_prompt = CROSS_FLOW_USER.format(
        repo_name=repo_name,
        call_graph=call_graph_str,
        module_summaries=module_summaries,
        dispatch_tables=dispatch_str + "\n\n" + callback_summary,
        structured_context=structured_ctx,
    )

    try:
        response = llm.chat(system=system_prompt, user=user_prompt, max_tokens=8192)
        from main import fix_mermaid_syntax
        response = fix_mermaid_syntax(response)

        # Cross-validate against ground truth
        validation = validate_cross_module_calls(response, ground_truth)
        val_summary = build_validation_summary(validation)
        print(f"  Cross-validation: {validation.accuracy_score:.0%} accuracy "
              f"({len(validation.verified_calls)}/{len(validation.verified_calls) + len(validation.unverified_calls)} verified)")

        if validation.unverified_calls:
            print(f"  ⚠ {len(validation.unverified_calls)} unverified calls detected — "
                  f"appending validation report")

        # Append validation report to output
        response_with_val = response + "\n\n---\n\n" + val_summary

        out_file = analysis_dir / "cross_flows.md"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(response_with_val)
        print(f"  Cross-module flows → {out_file} ({len(response_with_val)} chars)")
        return response_with_val
    except Exception as e:
        print(f"  ERROR: {e}")
        return f"[cross-flow extraction failed: {e}]"


def _extract_key_sections(analysis: str, max_chars: int = 2000) -> str:
    # Extract key sections from module analysis for context building.
    # Prioritizes: 模块职责, 公共接口, 核心流程图, 核心算法
    lines = analysis.split("\n")
    sections = []
    current_section = []
    current_header = ""
    priority_headers = [
        "模块职责", "公共接口", "核心业务流程", "核心算法", "数据结构",
        "module responsibility", "public interface", "core flow", "core algorithm",
    ]

    for line in lines:
        if line.strip().startswith("#"):
            # Save previous section
            if current_section and current_header:
                is_priority = any(p in current_header.lower() for p in priority_headers)
                sections.append((current_header, "\n".join(current_section), is_priority))
            current_header = line.strip()
            current_section = [line]
        else:
            current_section.append(line)

    # Save last section
    if current_section and current_header:
        is_priority = any(p in current_header.lower() for p in priority_headers)
        sections.append((current_header, "\n".join(current_section), is_priority))

    # Sort: priority sections first
    sections.sort(key=lambda x: (0 if x[2] else 1))

    # Concatenate up to max_chars
    result = []
    total = 0
    for header, content, _ in sections:
        if total + len(content) > max_chars:
            remaining = max_chars - total
            if remaining > 200:
                result.append(content[:remaining] + "...")
            break
        result.append(content)
        total += len(content)

    return "\n".join(result) if result else analysis[:max_chars]
