"""Phase 2.5: Cross-module flow analysis prompt generation.

Generates system and user prompts for identifying end-to-end data/control
flows across multiple modules, with Mermaid sequence diagrams.
"""

from __future__ import annotations



def render_cross_flow_prompt(
    repo_name: str,
    call_graph: str,
    module_summaries: str,
    dispatch_tables: str,
    structured_context: str,
) -> tuple[str, str]:
    """Render system and user prompts for Phase 2.5 cross-module flow analysis.

    Args:
        repo_name: Repository name.
        call_graph: Inter-module call graph (edges).
        module_summaries: Concatenated module analysis summaries.
        dispatch_tables: Dispatch/routing tables extracted from code.
        structured_context: Additional structured context (entry points, etc.).

    Returns:
        (system_prompt, user_prompt) tuple.
    """
    system = _build_system_prompt()
    user = _build_user_prompt(
        repo_name=repo_name,
        call_graph=call_graph,
        module_summaries=module_summaries,
        dispatch_tables=dispatch_tables,
        structured_context=structured_context,
    )
    return system, user


def _build_system_prompt() -> str:
    return """\
你是一名系统架构分析师，负责从模块级分析中提取跨模块的端到端数据流和控制流，并生成 Mermaid 序列图。

## 分析目标
识别 3-5 个最重要的端到端流程，这些流程应当：
1. 涵盖系统的主要功能路径
2. 跨越多个模块，体现模块间的协作关系
3. 对理解系统整体行为最有价值

## Mermaid 序列图语法规则（共 13 条）

### 基础结构
1. **必须使用 ```mermaid 代码块** 包裹图表
2. **第一行必须是 `sequenceDiagram`**
3. **每个图表必须有 title**：使用 `title 流程名称` 语法

### 参与者规则
4. **参与者数量 ≤ 5**：每个序列图最多 5 个参与方（participant）
5. **参与者必须是模块级**：使用模块名而非函数名（如 `API网关` 而非 `handle_request()`）
6. **参与者 ID 只能包含字母、数字和下划线**：中文名称用 `as` 别名（如 `A as API网关`）

### 消息规则
7. **消息数量 ≤ 10**：每个序列图最多 10 条消息，保持简洁
8. **消息文本中不能包含特殊字符**：避免 `;`、`[`、`]`、`(`、`)`、`"` 等
9. **使用标准箭头**：`->>` 表示实线，`-->>` 表示虚线（回复）

### 结构规则
10. **激活/停用必须配对**：每个 `+` 必须有对应的 `-`
11. **注释使用 Note 关键字**：`Note over A: 描述文本` 或 `Note left of A: 描述文本`
12. **不要使用嵌套引用**：消息文本中不要包含引号
13. **循环和条件使用标准语法**：`loop`、`alt`、`opt` 等块必须正确闭合

## 输出格式
对每个识别的流程，输出：
1. **流程名称**：简洁描述性标题
2. **触发条件**：什么情况下触发该流程
3. **流程描述**：文字描述各步骤
4. **Mermaid 序列图**：用 ```mermaid 代码块包裹
5. **关键决策点**：流程中的分支和条件判断

将每个 Mermaid 图表用 `<details>` 标签包裹以便折叠：
```html
<details>
<summary>流程名称 — 序列图</summary>

```mermaid
sequenceDiagram
    ...
```

</details>
```"""


def _build_user_prompt(
    repo_name: str,
    call_graph: str,
    module_summaries: str,
    dispatch_tables: str,
    structured_context: str,
) -> str:
    sections: list[str] = []

    sections.append("# 跨模块流程分析任务\n")
    sections.append(f"**仓库**: `{repo_name}`\n")

    sections.append("## 模块间调用图 (Call Graph)\n")
    sections.append("以下是已识别的模块间调用关系：\n")
    sections.append(f"```\n{call_graph}\n```\n")

    sections.append("## 模块分析摘要\n")
    sections.append("以下是各模块的分析摘要（来自 Phase 2）：\n")
    sections.append(module_summaries)
    sections.append("")

    if dispatch_tables:
        sections.append("## 调度表 (Dispatch Tables)\n")
        sections.append("以下是从代码中提取的路由/调度表：\n")
        sections.append(f"```\n{dispatch_tables}\n```\n")

    if structured_context:
        sections.append("## 结构化上下文\n")
        sections.append("以下是入口点和关键结构信息：\n")
        sections.append(f"```\n{structured_context}\n```\n")

    sections.append("## 分析要求\n")
    sections.append("1. 识别 3-5 个最重要的端到端流程")
    sections.append("2. 每个流程必须跨越至少 2 个模块")
    sections.append("3. 为每个流程生成 Mermaid 序列图")
    sections.append("4. 严格遵守系统提示中的 13 条 Mermaid 语法规则")
    sections.append("5. 每个图表参与者 ≤ 5，消息 ≤ 10")
    sections.append("6. 用 `<details>` 标签包裹每个 Mermaid 图表")
    sections.append("7. 图表参与者使用模块级名称，不使用函数名")

    return "\n".join(sections)
