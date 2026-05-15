"""LLM accuracy improvement framework for repo-analyzer.

Implements 7 techniques to reduce hallucination and improve analysis quality:
1. Chain-of-Thought (CoT) — force step-by-step reasoning before conclusions
2. Evidence Grounding — require citations to specific source code lines
3. Self-Critique — LLM reviews its own output for errors
4. Confidence Scoring — each claim tagged with confidence level
5. Structured Output — JSON mode for reliable parsing
6. Iterative Refinement — feed validation errors back for correction
7. Decomposition — break complex analysis into focused sub-tasks
"""


# ── 1. Chain-of-Thought (CoT) ──────────────────────────────────────────────

COT_SYSTEM_ADDON = """
**Chain-of-Thought 要求** — 在输出最终结论前，必须先展示推理过程：

对每个分析结论，按以下步骤推理：
1. **观察** — 我在源码中看到了什么（引用具体文件和行号）
2. **推理** — 基于观察，这意味着什么（逻辑推导）
3. **结论** — 最终判断（基于推理链）

输出格式：
```
### [分析项名称]

**观察**: 在 `file.c:42` 中看到了 `func_A` 调用 `func_B`...
**推理**: 这表明模块 A 依赖模块 B 的处理结果...
**结论**: 模块 A → 模块 B 存在数据依赖关系
```

不要跳过观察和推理步骤直接给出结论。
"""


# ── 2. Evidence Grounding ───────────────────────────────────────────────────

GROUNDING_SYSTEM_ADDON = """
**证据引用要求** — 每个分析结论必须引用具体的源码证据：

**必须遵守**：
- 每个函数/类的描述必须引用 `文件名:行号`
- 每个调用关系必须标注 caller 和 callee 的具体位置
- 每个数据流必须标注数据的来源和去向（文件+行号）
- 不确定的推断必须标注"推测"并说明依据

**格式**：
- 函数引用: `func_name` @ `file.c:42`
- 调用关系: `caller` @ `a.c:10` → `callee` @ `b.c:20`
- 表引用: `table_name` @ `config.xml:15`

**禁止**：
- 不要泛泛描述（如"模块负责处理请求"）
- 不要编造不存在的函数或调用关系
- 如果无法确定，明确标注为"待确认"
"""


# ── 3. Self-Critique ────────────────────────────────────────────────────────

SELF_CRITIQUE_PROMPT = """
## 自我审查

在输出最终分析之前，请按以下清单审查你的分析：

1. **调用关系验证** — 你提到的每个调用关系，是否在提供的调用图中存在？
2. **函数存在性** — 你提到的每个函数/类，是否在符号索引中存在？
3. **表引用验证** — 你提到的每个表名，是否在 SQL 分析中存在？
4. **UDF 验证** — 你提到的每个 UDF，是否在 UDF 定义清单中存在？
5. **逻辑一致性** — 你的分析中是否有自相矛盾的地方？
6. **完整性** — 是否遗漏了重要的分支或错误路径？
7. **Mermaid 语法** — 流程图/时序图是否符合 Mermaid 语法规则？

对审查中发现的每个问题，修正后再输出最终版本。

输出格式：
```
### 自我审查结果
- ✓ 调用关系: X/Y 已验证
- ⚠ 修正: [描述修正内容]
- ✓ 语法检查: 通过

### 最终分析
（修正后的完整分析）
```
"""


# ── 4. Confidence Scoring ───────────────────────────────────────────────────

CONFIDENCE_SYSTEM_ADDON = """
**置信度标注要求** — 对每个分析结论标注置信度：

**置信度等级**：
- 🟢 **确定** (high) — 有直接源码证据，可验证
- 🟡 **高度可能** (medium) — 基于多个间接证据的合理推断
- 🔴 **推测** (low) — 基于模式匹配或经验推断，需要进一步验证

**标注格式**：
在每个结论后添加置信度标签：
- `函数 A 调用函数 B [🟢 确定]` — 调用图中存在
- `模块 X 可能依赖缓存 [🟡 高度可能]` — 基于代码模式推断
- `可能存在性能瓶颈 [🔴 推测]` — 基于架构推断

**统计要求** — 在分析末尾添加置信度统计：
```
### 置信度统计
- 🟢 确定: X 个结论
- 🟡 高度可能: Y 个结论
- 🔴 推测: Z 个结论
- 总体可信度: X/(X+Y+Z)
```
"""


# ── 5. Decomposition ────────────────────────────────────────────────────────

DECOMPOSITION_SYSTEM_ADDON = """
**任务分解要求** — 对于复杂模块，按子任务逐步分析：

**分解步骤**：
1. **接口层** — 先识别公共接口（对外暴露的函数/类）
2. **数据层** — 识别数据结构和数据流
3. **控制层** — 识别控制流和决策逻辑
4. **错误层** — 识别错误处理和边界条件
5. **依赖层** — 识别外部依赖和跨模块调用

每个子任务独立分析，最后汇总。
"""


# ── 6. Prompt Templates ────────────────────────────────────────────────────

def enhance_system_prompt(base_prompt: str, techniques: list[str] = None) -> str:
    """Enhance a system prompt with accuracy techniques.

    Args:
        base_prompt: Original system prompt
        techniques: List of technique names to apply. None = all.
            Options: "cot", "grounding", "critique", "confidence", "decomposition"

    Returns:
        Enhanced system prompt
    """
    if techniques is None:
        techniques = ["cot", "grounding", "confidence", "decomposition"]

    addons = {
        "cot": COT_SYSTEM_ADDON,
        "grounding": GROUNDING_SYSTEM_ADDON,
        "confidence": CONFIDENCE_SYSTEM_ADDON,
        "decomposition": DECOMPOSITION_SYSTEM_ADDON,
    }

    parts = [base_prompt]
    for tech in techniques:
        if tech in addons:
            parts.append(addons[tech])

    return "\n".join(parts)


def create_self_critique_prompt(original_output: str, ground_truth_summary: str) -> str:
    """Create a self-critique prompt that asks the LLM to review its own output.

    Args:
        original_output: The LLM's original analysis output
        ground_truth_summary: Summary of Phase 1 verified facts

    Returns:
        A prompt that asks the LLM to critique and fix its output
    """
    return f"""以下是之前的分析输出，请按以下要求审查和修正：

## 审查要求
1. 检查每个调用关系是否在调用图中存在
2. 检查每个函数名是否在符号索引中存在
3. 检查每个表名是否在 SQL 分析中存在
4. 检查 Mermaid 语法是否正确
5. 标注修正内容

## Phase 1 验证数据
{ground_truth_summary}

## 待审查的分析
{original_output}

## 请输出修正后的完整分析
（保持原有结构，修正错误，标注置信度）
"""


# ── 7. Iterative Refinement ─────────────────────────────────────────────────

def create_refinement_prompt(
    original_output: str,
    validation_errors: list[str],
    ground_truth: str,
) -> str:
    """Create a refinement prompt that feeds validation errors back to the LLM.

    Args:
        original_output: The LLM's original output
        validation_errors: List of validation error descriptions
        ground_truth: Phase 1 ground truth data

    Returns:
        A prompt that asks the LLM to fix specific errors
    """
    errors_text = "\n".join(f"  {i+1}. {e}" for i, e in enumerate(validation_errors))

    return f"""交叉验证发现以下问题，请修正：

## 发现的问题
{errors_text}

## Phase 1 验证数据
{ground_truth}

## 原始分析
{original_output}

## 请修正上述问题并输出完整的修正版本
要求：
- 修正所有标记的问题
- 对于无法在验证数据中找到的调用关系，标注为 [推测]
- 保持分析的整体结构不变
- 添加置信度标注
"""


# ── 8. Technique Application Guide ──────────────────────────────────────────

TECHNIQUE_GUIDE = """
# LLM 精确性技术应用指南

## 各阶段推荐技术组合

| 阶段 | CoT | Grounding | Critique | Confidence | Decomposition |
|------|-----|-----------|----------|------------|---------------|
| Phase 2 (模块分析) | ✓ | ✓ | ✓ | ✓ | ✓ |
| Phase 2.5 (跨模块流) | ✓ | ✓ | - | ✓ | - |
| Phase 3 (架构综合) | ✓ | ✓ | ✓ | ✓ | - |
| 交叉验证后修正 | - | - | - | ✓ | - |

## 核心原则

1. **Grounding > Generation** — 提供充分的结构化数据，让 LLM 基于事实推理而非自由发挥
2. **Verify > Trust** — 交叉验证每个结论，不信任 LLM 的自我声明
3. **Decompose > Monolith** — 复杂任务拆分为简单子任务
4. **Iterate > Once** — 验证-修正循环比单次生成更可靠
5. **Confidence > Assumption** — 标注置信度，区分事实和推测

## Token 成本预估

| 技术 | 额外 Token | 精确性提升 |
|------|-----------|-----------|
| CoT | +20-30% | 中 |
| Grounding | +10-15% | 高 |
| Self-Critique | +100% (二次调用) | 高 |
| Confidence | +5-10% | 低 (但提升可读性) |
| Decomposition | +30-50% | 中 |
| Iterative Refinement | +50-100% (per iteration) | 高 |
"""
