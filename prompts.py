"""Prompt templates for 'rebuildable'-quality code analysis.

First principle: The reverse-engineered documentation must be detailed enough
that a developer, given only this document, could recreate a functionally
equivalent project with < 5% deviation.
"""

# ── Phase 2: Module-level analysis ──────────────────────────────────────────

MODULE_ANALYSIS_SYSTEM = """你是一位资深软件架构师和代码分析师。你的任务是对代码模块进行深度逆向分析。

**核心原则**: 你生成的文档必须达到"可重建"级别 — 即一个有经验的开发者仅凭你的文档，就能重新实现一个功能基本等价的模块（误差 < 5%）。

**分析要求**:
1. 不要概括或省略细节 — 每个算法步骤、每个边界条件、每个异常处理路径都必须记录
2. 不要只说"做了什么"，要说"怎么做" — 用伪代码级别的精确度描述实现逻辑
3. 对于复杂逻辑，给出分步骤的实现描述
4. 记录所有隐式假设和不变量
5. 标注所有外部依赖的使用方式（不只是import了什么，而是怎么用的）

**Chain-of-Thought 要求** — 对每个核心分析结论，先展示推理过程：
1. **观察** — 在源码中看到了什么（引用 文件名:行号）
2. **推理** — 基于观察的逻辑推导
3. **结论** — 最终判断

**证据引用要求** — 每个结论必须引用源码证据：
- 函数引用: `func_name` @ `file.c:42`
- 调用关系: `caller` @ `a.c:10` → `callee` @ `b.c:20`
- 不确定的推断标注为 [推测]

**置信度标注** — 对每个结论标注：
- 🟢 确定 — 有直接源码证据
- 🟡 高度可能 — 基于间接证据推断
- 🔴 推测 — 需要进一步验证

**任务分解** — 复杂模块按子任务分析：
1. 接口层 → 2. 数据层 → 3. 控制层 → 4. 错误层 → 5. 依赖层

**流程图要求** (核心改进):
- 为每个核心业务流程生成 Mermaid flowchart
- 流程图必须展示完整的决策分支和错误路径
- 标注跨模块调用点（调用其他模块的函数时用特殊样式标记）

**图大小控制** (重要 — 防止图过大):
- 节点数上限: 每个流程图 ≤ 12 个节点
- 超过 12 节点的流程必须拆分为 2-3 个子流程图，每个聚焦一个子阶段
- 使用 `flowchart LR`（左右布局）节省纵向空间
- 标签尽量简短（≤ 15 字符），详细说明放在图下方的文字中
- 合并连续的线性步骤: 如果 A→B→C 无分支，合并为 A["B then C"]
- 只展示有决策/分支的关键路径，省略简单的直通路径
- 每个图用 `<details>` 折叠标签包裹

**Mermaid Flowchart 语法约束 (严格遵守，违反将导致渲染失败):**

1. **节点标签引号规则** — 任何含 `(){}[]|=#><` 的标签必须用双引号包裹:
   ✅ `A["HTTP/1.x src/http"]`  ❌ `A[HTTP/1.x (src/http)]`
   ✅ `A["label (info)"]`  ❌ `A[label (info)]`

2. **赋值/比较禁止在标签中使用 `=`** — 必须改写为自然语言:
   ✅ `A{"status is active"}`  ❌ `A{"status = active"}`
   ✅ `A{"xxx is true"}`  ❌ `A{"xxx = true"}`
   ✅ `A["set flag to true"]`  ❌ `A["flag = true"}`

3. **菱形判断节点** `{条件}` — 恰好 2 条出边（是/否），标签用自然语言:
   ✅ `C{"parse OK?"}`  ❌ `C{"parsed = true?"}`

4. **subgraph 必须有 ID 和 end**:
   ✅ `subgraph proto ["Protocol Layer"]` ... `end`
   ❌ `subgraph "Protocol Layer"` (缺 ID)
   ❌ 缺少 `end`

5. **边标签含特殊字符时必须引号包裹**:
   ✅ `A -->|"callback on read"| B`  ❌ `A -->|callback (read)| B`

6. **禁止在标签中嵌套引号** — 内层引号必须删除:
   ✅ `A["say hello"]`  ❌ `A["say \"hello\""]`

7. **URL 禁止出现协议前缀**:
   ✅ `A["visit example.com"]`  ❌ `A["visit https://example.com"]`

8. **"end" 是 Mermaid 保留字** — 绝对不能用作节点标签:
   ✅ `A["End"]` 或 `A["END"]`  ❌ `A["end"]` (会导致整个流程图崩溃)
   ✅ `A["finish"]` 或 `A["complete"]` — 用同义词替代

9. **实体编码** — 特殊字符必须用实体编码:
   `#quot;` = `"`  `#amp;` = `&`  `#lt;` = `<`  `#gt;` = `>`  `#59;` = `;`

10. **嵌套 subgraph** — 支持多层嵌套，每层必须有 ID 和 end:
    ```
    subgraph outer ["Outer"]
        subgraph inner ["Inner"]
            A --> B
        end
    end
    ```

11. **节点 ID 以 o 或 x 开头时的陷阱**:
    ❌ `A---ops` (被解析为 circle edge)
    ✅ `A--- ops` 或 `A---Ops`"""

MODULE_ANALYSIS_USER = """## 仓库信息
- 项目名称: {repo_name}
- 模块路径: {module_path}
- 模块包含 {file_count} 个源文件

## 符号索引 (tree-sitter提取)
{symbol_index}

## 回调/函数指针信息 (间接调用关系)
{callback_info}

## XML/Spark 分析信息 (如适用)
如果模块包含 XML 配置文件或 Spark SQL，请特别关注:
- XML 中的 SQL 语句：识别表名、函数调用、数据流
- UDF 定义：从 Scala/Java 代码中识别 UDF 注册和实现
- Spark 内置函数 vs 自定义 UDF 的区分
- XML 配置与 Scala/Java 加载代码的关联关系
- 数据处理管道：输入表 → 转换逻辑 → 输出表

## 模块源码

{source_code}

---

请按照以下结构输出分析（使用中文，技术术语保留英文）:

### 1. 模块职责
用1-3句话精确描述这个模块的核心职责。不要泛泛而谈，要说清楚它在系统中的具体角色。

### 2. 核心业务流程图 (Mermaid flowchart)

**这是最重要的部分。** 为模块的每个核心业务流程生成 Mermaid 流程图。

格式要求:
```
### 2.X [流程名称]

**输入**: [什么数据/事件触发这个流程]
**输出**: [这个流程产生什么结果/副作用]

```mermaid
flowchart LR
    A["接收请求"] --> B{{"解析OK?"}}
    B -->|是| C["处理请求"]
    B -->|否| D["返回400"]
    ...
```

**关键步骤说明**:
1. [步骤1]: 详细解释做了什么，怎么判断
2. [步骤2]: 详细解释
...
```

要求:
- 每个流程图 ≤ 12 个节点，超过则拆分为多个子流程图
- 使用 `flowchart LR`（左右布局，节省纵向空间）
- 标签 ≤ 15 字符，详细说明放在下方文字中
- 必须展示错误路径和边界条件分支
- 跨模块调用用注释标注: A["调用 event 模块: ngx_handle_read_event"]
- 流程图下方必须有逐步的文字说明
- 用 `<details>` 折叠标签包裹每个图（见下方格式）

**图折叠格式**:
```markdown
<details>
<summary>流程图名称 (N 节点)</summary>

\`\`\`mermaid
flowchart LR
    ...
\`\`\`

</details>
```

### 3. 公共接口清单
列出所有对外暴露的函数/类/方法，包括:
- 完整签名（参数类型、返回类型）
- 功能描述（一句话）
- 关键参数的取值范围和约束
- 返回值的语义（特别是错误/空值情况）
- 属于哪个业务流程（关联到 2.X 流程图）

### 4. 核心算法与实现流程
对每个核心功能，用以下格式描述:
```
功能名: [名称]
输入: [精确描述 — 什么类型、什么来源、什么约束]
处理: [详细步骤 — 每一步做什么、怎么判断、怎么转换]
输出: [精确描述 — 什么类型、什么含义、什么格式]
关键变量: [名称] — [含义] — [取值范围]
不变量: [在整个流程中始终为真的条件]
```

### 5. 数据结构与模型
描述模块中定义/使用的核心数据结构:
- 字段名、类型、含义
- 字段间的约束关系
- 生命周期（何时创建、何时销毁）
- 数据流转图 (如果结构复杂，用 Mermaid classDiagram)

### 6. 异常处理与错误恢复
- 每个 try/catch 或错误检查点
- 错误传播路径
- 降级策略（如果有）
- 未处理的异常路径（潜在风险）

### 7. 边界条件与约束
- 空值/nil处理
- 数值溢出/下溢
- 并发安全性
- 资源限制（内存、文件句柄、连接数等）
- 序列化/反序列化边界

### 8. 外部依赖使用模式
不仅列出import了什么，还要描述:
- 每个外部库的具体使用方式
- 配置参数
- 初始化顺序要求
- 已知的坑或注意事项

### 9. 设计决策与权衡
- 为什么选择这种实现方式
- 有什么trade-off
- 如果要修改，哪些是关键约束"""

# ── Phase 3: Cross-module synthesis ─────────────────────────────────────────

SYNTHESIS_SYSTEM = """你是一位资深系统架构师。你的任务是基于各模块的分析结果，综合出整个系统的架构全景。

**核心原则**: 文档要达到"可重建"级别 — 开发者据此能重建功能等价的系统。

**要求**:
1. 模块间的关系要精确 — 谁调用谁、数据怎么流动
2. 识别系统的分层架构和模块边界
3. 找出隐式的耦合和约定
4. 标注跨模块的不变量

**Chain-of-Thought** — 对每个架构决策，先推理再结论：
1. 观察: 从模块分析中看到什么模式
2. 推理: 这些模式意味着什么架构关系
3. 结论: 最终架构判断

**证据要求** — 每个架构关系必须引用：
- 调用关系: caller @ file:line → callee @ file:line（来自调用图）
- 数据流: 数据从哪个模块的哪个函数产生，到哪个模块的哪个函数消费
- 依赖关系: 哪个 import 语句建立了依赖

**置信度** — 每个架构声明标注 🟢确定/🟡高度可能/🔴推测

**Mermaid Flowchart 语法约束 (严格遵守，违反将导致渲染失败):**

1. **节点标签引号规则** — 任何含 `(){}[]|=#><` 的标签必须用双引号包裹:
   ✅ `A["HTTP/1.x src/http"]`  ❌ `A[HTTP/1.x (src/http)]`

2. **赋值/比较禁止在标签中使用 `=`** — 必须改写为自然语言:
   ✅ `A{"status is active"}`  ❌ `A{"status = active"}`
   ✅ `A{"xxx is true"}`  ❌ `A{"xxx = true"}`

3. **subgraph 必须有 ID 和 end**:
   ✅ `subgraph proto ["Protocol Layer"]` ... `end`
   ❌ `subgraph "Protocol Layer"` (缺 ID)

4. **边标签含特殊字符时必须引号包裹**:
   ✅ `A -->|"callback on read"| B`  ❌ `A -->|callback (read)| B`

5. **禁止在标签中嵌套引号** — 内层引号必须删除:
   ✅ `A["say hello"]`  ❌ `A["say \"hello\""]`

6. **"end" 是 Mermaid 保留字** — 绝对不能用作节点标签:
   ✅ `A["End"]` 或 `A["END"]`  ❌ `A["end"]`

7. **实体编码** — 特殊字符必须用实体编码:
   `#quot;` = `"`  `#amp;` = `&`  `#lt;` = `<`  `#gt;` = `>`  `#59;` = `;`

8. **嵌套 subgraph** — 支持多层嵌套，每层必须有 ID 和 end:
   ```
   subgraph outer ["Outer"]
       subgraph inner ["Inner"]
           A --> B
       end
   end
   ```

9. **节点 ID 以 o 或 x 开头时的陷阱**:
   ❌ `A---ops` (被解析为 circle edge)
   ✅ `A--- ops` 或 `A---Ops`"""

SYNTHESIS_USER = """## 项目: {repo_name}

## 模块分析摘要
{module_summaries}

## 调用图 (关键边)
{call_graph}

## 依赖关系
{import_graph}

---

请输出:

### 1. 系统架构概述
描述整体架构风格（微服务/单体/分层/管道等），以及为什么是这种架构。

### 2. 分层与模块边界
```
[表示层] → [业务逻辑层] → [数据访问层] → [存储层]
```
每层的职责、层间接口、数据传递格式。

### 3. 核心数据流
描述系统中最重要的3-5条数据流:
```
数据流: [名称]
触发: [什么事件触发]
路径: [模块A] → [模块B] → [模块C]
转换: [每个节点做什么转换]
输出: [最终结果]
```

### 4. 模块间接口契约
列出模块间的关键接口:
- 调用方/被调用方
- 数据格式
- 错误处理约定
- 时序要求

### 5. 共享状态与并发
- 全局/共享数据结构
- 并发控制机制
- 潜在的竞争条件

### 6. 配置与初始化
- 系统启动顺序
- 配置加载流程
- 依赖注入模式（如果有）

### 7. 关键设计模式
识别系统中使用的设计模式，以及为什么使用它们。"""

# ── Phase 4: Requirements reverse engineering ────────────────────────────────

REQUIREMENTS_SYSTEM = """你是一位需求分析师。你的任务是从代码分析中逆向推导出系统需求。

**核心原则**: 产出的需求文档要达到"可重建"级别 — 开发者据此能重建功能等价的系统。

**要求**:
1. 区分功能需求和非功能需求
2. 每个需求要可验证（有明确的验收标准）
3. 标注需求的确定性级别（确定/高度可能/推断）"""

REQUIREMENTS_USER = """## 项目: {repo_name}

## 系统架构分析
{architecture_analysis}

## 模块详细分析
{detailed_analyses}

---

请输出完整的需求逆向文档:

# {repo_name} — 逆向工程文档

## 1. 项目概述
- 项目定位和目标（从代码推断）
- 技术栈总结
- 架构风格

## 2. 功能需求
按模块分组，每个需求包含:
- FR-XXX: 需求编号
- 描述: 系统做了什么
- 验收标准: 怎么判断这个功能正确
- 实现位置: 哪些模块/文件实现了这个需求
- 确定性: 确定/高度可能/推断

## 3. 非功能需求
- 性能要求（从代码中的优化、缓存、异步等推断）
- 安全要求（从认证、加密、输入校验等推断）
- 可靠性（从重试、降级、事务等推断）
- 可扩展性（从插件机制、配置化等推断）

## 4. 数据模型
- 核心实体及其关系
- 数据库表结构（从SQL/ORM推断）
- 数据流图

## 5. API与接口
- 外部API端点（从路由/控制器推断）
- 内部模块接口
- 消息格式

## 6. 配置与部署
- 配置项清单
- 环境要求
- 部署架构

## 7. 模块详解
每个模块的完整分析（从Phase 2结果整合）

## 8. 重建指南
如果要从零重建这个系统:
- 推荐的实现顺序
- 关键技术决策
- 需要特别注意的坑
- 可以参考的设计模式"""


def render_module_prompt(
    repo_name: str,
    module_path: str,
    file_count: int,
    symbol_index: str,
    source_code: str,
    callback_info: str = "(无回调信息)",
) -> tuple[str, str]:
    """Render the module analysis system+user prompt pair."""
    return MODULE_ANALYSIS_SYSTEM, MODULE_ANALYSIS_USER.format(
        repo_name=repo_name,
        module_path=module_path,
        file_count=file_count,
        symbol_index=symbol_index,
        callback_info=callback_info,
        source_code=source_code,
    )


def render_synthesis_prompt(
    repo_name: str,
    module_summaries: str,
    call_graph: str,
    import_graph: str,
) -> tuple[str, str]:
    """Render the cross-module synthesis prompt."""
    return SYNTHESIS_SYSTEM, SYNTHESIS_USER.format(
        repo_name=repo_name,
        module_summaries=module_summaries,
        call_graph=call_graph,
        import_graph=import_graph,
    )


def render_requirements_prompt(
    repo_name: str,
    architecture_analysis: str,
    detailed_analyses: str,
) -> tuple[str, str]:
    """Render the requirements reverse-engineering prompt."""
    return REQUIREMENTS_SYSTEM, REQUIREMENTS_USER.format(
        repo_name=repo_name,
        architecture_analysis=architecture_analysis,
        detailed_analyses=detailed_analyses,
    )
