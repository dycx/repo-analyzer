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

**Mermaid 语法约束** (严格遵守):
- 节点标签中禁止使用括号 () — Mermaid 会将其解析为圆角节点语法
- 使用引号包裹标签: participant C as "Client"
- 路径用空格替代括号: src/http 而非 (src/http)
- 消息标签中不要用特殊字符"""

CROSS_FLOW_USER = """## 项目: {repo_name}

## 系统调用图 (关键调用关系)
{call_graph}

## 模块分析摘要
{module_summaries}

## 分派表/回调注册 (C函数指针模式)
{dispatch_tables}

---

请识别这个系统中最重要的 3-5 个端到端业务流程，为每个流程生成 Mermaid 时序图。

**要求**:
1. 选择最核心的业务流程（如: HTTP请求处理、配置加载、Worker进程启动等）
2. 每个流程必须跨越至少 2 个模块
3. 时序图必须展示完整的调用链，包括回调/函数指针的间接调用
4. 每个消息箭头必须标注具体函数名（不要泛化为"处理请求"）
5. 在关键分支点标注条件

**输出格式** (每个流程):

## 流程 X: [流程名称]

**触发条件**: [什么事件/输入触发这个流程]
**涉及模块**: [模块1, 模块2, ...]
**最终输出**: [这个流程完成后的结果/副作用]

```mermaid
sequenceDiagram
    participant A as "模块A"
    participant B as "模块B"
    participant C as "模块C"
    
    A->>B: 具体函数名(params)
    Note right of B: 做什么处理
    B->>C: 具体函数名(params)
    alt 成功路径
        C-->>B: 返回结果
        B-->>A: 返回结果
    else 错误路径
        C-->>B: 错误码
        B-->>A: 错误处理
    end
```

**逐步说明**:
1. [步骤1]: 详细解释这一步做了什么，输入是什么，输出是什么
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
    
    # Build module summaries
    summaries = []
    for mod_name, analysis in module_analyses.items():
        summary = analysis[:800]
        if len(analysis) > 800:
            summary += "..."
        summaries.append(f"### {mod_name}\n{summary}")
    module_summaries = "\n\n".join(summaries)
    
    # Also load per-module callback data
    modules_dir = analysis_dir / "modules"
    module_data = []
    if modules_dir.exists():
        for f in sorted(modules_dir.glob("*.json")):
            with open(f, encoding="utf-8") as fh:
                module_data.append(json.load(fh))
    
    callback_summary = build_callback_summary(module_data)
    
    # Call LLM
    system_prompt = CROSS_FLOW_SYSTEM
    user_prompt = CROSS_FLOW_USER.format(
        repo_name=repo_name,
        call_graph=call_graph_str,
        module_summaries=module_summaries,
        dispatch_tables=dispatch_str + "\n\n" + callback_summary,
    )
    
    try:
        response = llm.chat(system=system_prompt, user=user_prompt, max_tokens=8192)
        # Fix Mermaid syntax issues from LLM output
        from main import fix_mermaid_syntax
        response = fix_mermaid_syntax(response)
        out_file = analysis_dir / "cross_flows.md"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(response)
        print(f"  Cross-module flows → {out_file} ({len(response)} chars)")
        return response
    except Exception as e:
        print(f"  ERROR: {e}")
        return f"[cross-flow extraction failed: {e}]"
