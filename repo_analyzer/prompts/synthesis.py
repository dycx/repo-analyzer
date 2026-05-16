"""Phase 3: Architecture synthesis prompt generation.

Generates system and user prompts for synthesizing all module analyses
into a comprehensive architecture document.
"""

from __future__ import annotations



def render_synthesis_prompt(
    repo_name: str,
    module_summaries: str,
    call_graph: str,
    import_graph: str,
) -> tuple[str, str]:
    """Render system and user prompts for Phase 3 architecture synthesis.

    Args:
        repo_name: Repository name.
        module_summaries: Concatenated module analysis results.
        call_graph: Module-level call graph.
        import_graph: Module-level import dependency graph.

    Returns:
        (system_prompt, user_prompt) tuple.
    """
    system = _build_system_prompt()
    user = _build_user_prompt(
        repo_name=repo_name,
        module_summaries=module_summaries,
        call_graph=call_graph,
        import_graph=import_graph,
    )
    return system, user


def _build_system_prompt() -> str:
    return """\
你是一名资深软件架构师，负责将分散的模块分析综合为一份完整的架构文档。

## Self-Critique (自我批判) 技术
在生成最终文档之前，你必须执行以下自我审查步骤：

### 第一步：一致性检查
- 各模块分析之间是否存在矛盾？
- 同一个模块在不同上下文中的描述是否一致？
- 调用关系图是否与模块分析中的依赖描述吻合？

### 第二步：完整性检查
- 是否所有主要模块都被覆盖？
- 关键的数据流路径是否被完整描述？
- 错误处理策略是否在架构层面有统一描述？

### 第三步：抽象层级检查
- 架构描述是否在正确的抽象层级？（不应过于细节，也不应过于笼统）
- 是否避免了重复模块分析中已有的细节？
- 是否提供了模块分析中缺少的全局视角？

### 第四步：修正与补充
- 对发现的矛盾，选择更可信的一方并标注
- 对缺失的部分，基于已有信息进行合理推断并标注置信度
- 对抽象层级不当的内容进行调整

## 架构分析维度

### 1. 系统全景
- 仓库的总体定位和核心价值
- 主要技术栈和架构风格（如 MVC、微服务、事件驱动等）
- 设计哲学和核心原则

### 2. 分层架构
- 识别系统的分层结构（表示层、业务层、数据层等）
- 各层的职责边界和通信方式
- 层间依赖规则和例外

### 3. 模块地图
- 模块分类（按功能域、按技术职责等）
- 核心模块 vs 辅助模块
- 模块间的耦合度分析

### 4. 数据架构
- 核心数据模型
- 数据流向（输入 → 处理 → 输出）
- 数据存储策略

### 5. 控制流架构
- 请求处理主路径
- 事件驱动/消息传递机制
- 并发和异步处理策略

### 6. 扩展点与约束
- 系统的扩展点（插件、钩子、配置等）
- 关键的技术约束和限制
- 已知的技术债务

### 7. 安全架构（如适用）
- 认证和授权机制
- 数据保护策略
- 安全边界

## 输出格式
使用 Markdown 格式，结构清晰，适合作为项目架构文档的基线。
每个章节应包含：
- 概述（1-2 段）
- 关键发现（带证据引用）
- 架构图（如适用，使用 Mermaid）"""


def _build_user_prompt(
    repo_name: str,
    module_summaries: str,
    call_graph: str,
    import_graph: str,
) -> str:
    sections: list[str] = []

    sections.append("# 架构综合分析任务\n")
    sections.append(f"**仓库**: `{repo_name}`\n")

    sections.append("## 模块分析结果\n")
    sections.append("以下是所有模块的详细分析（来自 Phase 2）：\n")
    sections.append(module_summaries)
    sections.append("")

    sections.append("## 模块调用图 (Call Graph)\n")
    sections.append("以下是模块间的调用关系：\n")
    sections.append(f"```\n{call_graph}\n```\n")

    sections.append("## 模块导入图 (Import Graph)\n")
    sections.append("以下是模块间的导入依赖关系：\n")
    sections.append(f"```\n{import_graph}\n```\n")

    sections.append("## 综合要求\n")
    sections.append("1. 基于以上模块分析结果，生成完整的架构文档")
    sections.append("2. 在综合前执行 Self-Critique 自我审查流程")
    sections.append("3. 识别系统的核心架构模式和设计决策")
    sections.append("4. 分析模块间的依赖关系和数据流")
    sections.append("5. 识别架构层面的约束、扩展点和潜在风险")
    sections.append("6. 输出达到「可重建」质量标准——开发者应能据此理解系统全貌")
    sections.append("7. 使用 Mermaid 图表辅助说明关键架构关系")

    return "\n".join(sections)
