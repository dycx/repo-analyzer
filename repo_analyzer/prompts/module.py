"""Phase 2: Module analysis prompt generation.

Generates system and user prompts for per-module code analysis.
The output must meet the 'rebuildable' (可重建) quality standard.
"""

from __future__ import annotations



def render_module_prompt(
    repo_name: str,
    module_path: str,
    file_count: int,
    symbol_index: str,
    source_code: str,
    callback_info: str,
    output_points: str,
) -> tuple[str, str]:
    """Render system and user prompts for Phase 2 module analysis.

    Args:
        repo_name: Repository name.
        module_path: Module path (e.g. "src/auth/login").
        file_count: Number of source files in this module.
        symbol_index: Pre-extracted symbol index (classes, functions, etc.).
        source_code: Source code preview for the module.
        callback_info: Callback/hook information from Phase 1.5.
        output_points: Identified output points (API endpoints, CLI commands, etc.).

    Returns:
        (system_prompt, user_prompt) tuple.
    """
    system = _build_system_prompt()
    user = _build_user_prompt(
        repo_name=repo_name,
        module_path=module_path,
        file_count=file_count,
        symbol_index=symbol_index,
        source_code=source_code,
        callback_info=callback_info,
        output_points=output_points,
    )
    return system, user


def _build_system_prompt() -> str:
    return """\
你是一名高级代码逆向工程专家，负责对代码模块进行深度分析并生成可重建级 (rebuildable) 文档。

## 核心原则

### Chain-of-Thought (思维链)
在分析每个模块时，你必须按以下步骤进行显式推理：
1. **识别**：扫描 symbol index，识别所有公开 API、类、函数和常量
2. **分类**：按职责对符号进行分组（数据模型、业务逻辑、IO 操作、配置等）
3. **关联**：追踪模块内部的调用关系和数据流向
4. **综合**：基于以上分析，生成结构化的模块文档

### Evidence Grounding (证据锚定)
- 每个分析结论必须引用具体的代码行或符号名作为证据
- 使用格式：`[证据: 文件名:行号 或 符号名]`
- 不允许凭空推测——如果信息不足，明确标注 `[推断]` 并说明理由
- 如果某个行为无法从源码确认，使用 `[待验证]` 标记

### Confidence Scoring (置信度评分)
对每个分析结论标注置信度：
- **HIGH** (高): 源码直接支持，有明确的代码证据
- **MEDIUM** (中): 基于代码模式推断，逻辑合理但非直接证据
- **LOW** (低): 猜测或经验推断，需要进一步验证

### Decomposition (分解策略)
将复杂模块拆解为以下维度进行分析：
1. **职责边界**：这个模块做什么？不做什么？
2. **公开接口**：对外暴露哪些 API？参数和返回值是什么？
3. **内部结构**：核心类/函数之间的协作关系
4. **依赖关系**：依赖哪些外部模块？被谁依赖？
5. **数据流**：输入数据如何经过处理变为输出？
6. **错误处理**：异常和错误如何被捕获和传播？
7. **副作用**：IO 操作、状态修改、外部调用等

## 输出质量标准：可重建 (Rebuildable)
你的分析文档必须足够详细，使得一名有经验的开发者仅凭此文档就能：
- 理解模块的完整职责和设计意图
- 重建模块的公开 API 接口
- 理解核心业务逻辑的实现策略
- 识别关键的实现约束和边界条件

## 输出格式
使用 Markdown 格式，包含以下章节：
- `## 模块概览` — 一句话总结 + 职责描述
- `## 公开接口` — API 列表，含签名、参数说明、返回值
- `## 核心实现` — 关键算法/逻辑的详细分析
- `## 依赖关系` — 上下游依赖图
- `## 数据流` — 主要数据处理路径
- `## 错误处理` — 异常策略
- `## 关键约束` — 实现中的重要约束和边界条件
- `## 分析备注` — 置信度为 LOW 的推断、待验证项"""


def _build_user_prompt(
    repo_name: str,
    module_path: str,
    file_count: int,
    symbol_index: str,
    source_code: str,
    callback_info: str,
    output_points: str,
) -> str:
    sections: list[str] = []

    sections.append(f"# 模块分析任务\n")
    sections.append(f"**仓库**: `{repo_name}`")
    sections.append(f"**模块路径**: `{module_path}`")
    sections.append(f"**文件数量**: {file_count}\n")

    sections.append("## 符号索引 (Symbol Index)\n")
    sections.append("以下是通过 AST 解析提取的符号列表：\n")
    sections.append(f"```\n{symbol_index}\n```\n")

    sections.append("## 源代码预览\n")
    sections.append("以下是模块的核心源代码（已截断至上下文限制）：\n")
    sections.append(f"```\n{source_code}\n```\n")

    if callback_info:
        sections.append("## 回调/Hook 信息\n")
        sections.append("以下是从 Phase 1.5 识别的回调和 Hook 模式：\n")
        sections.append(f"```\n{callback_info}\n```\n")

    if output_points:
        sections.append("## 输出点 (Output Points)\n")
        sections.append("以下是从 Phase 1.5 识别的模块输出点：\n")
        sections.append(f"```\n{output_points}\n```\n")

    sections.append("## 分析要求\n")
    sections.append("请按照系统提示中定义的分析框架，对该模块进行深度分析。")
    sections.append("确保每个结论都有证据支撑，并标注置信度。")
    sections.append("输出必须达到「可重建」质量标准。")

    return "\n".join(sections)
