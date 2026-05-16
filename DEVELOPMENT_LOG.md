# Repo-Analyzer 项目完整开发记录

> 本文档记录了 repo-analyzer 从零到完整的全部开发过程，包括每个决策的背景、实现细节、遇到的问题和解决方案。
> 目标读者：任何开发者或 AI agent，可以通过本文档完整复现项目。

---

## 目录

1. [项目概述](#1-项目概述)
2. [初始架构设计](#2-初始架构设计)
3. [Phase 0-1: 基础流水线](#3-phase-0-1-基础流水线)
4. [Windows 兼容性](#4-windows-兼容性)
5. [Mermaid 图表系统](#5-mermaid-图表系统)
6. [文档生成系统](#6-文档生成系统)
7. [XML/Spark 支持](#7-xmlspark-支持)
8. [LLM 准确性框架](#8-llm-准确性框架)
9. [输出驱动分析](#9-输出驱动分析)
10. [测试与修复](#10-测试与修复)
11. [最终架构](#11-最终架构)
12. [CLI 参数参考](#12-cli-参数参考)
13. [已知问题与改进方向](#13-已知问题与改进方向)

---

## 1. 项目概述

**目标**: 构建一个代码仓库逆向工程流水线，使用 tree-sitter 提取代码结构 + LLM 生成"可重建"级别的文档。

**核心原则**: 生成的文档必须足够详细，使得一个有经验的开发者仅凭文档就能重建功能等价的项目（误差 < 5%）。

**技术栈**:
- 语言: Python 3.11
- AST 解析: tree-sitter (C/C++/Java/Python/Scala/SQL/XML)
- LLM: 任何 OpenAI 兼容 API（LM Studio 本地 / 远程）
- 文档: Markdown + HTML（带 Mermaid 图表）

**仓库**: `github.com/dycx/repo-analyzer`
**分支策略**: `feat/windows-remote-llm` 开发，稳定后合并到 `main`

---

## 2. 初始架构设计

### 2.1 流水线阶段

```
Phase 0: 侦察 (Reconnaissance)
  → 扫描目录结构、语言统计、构建系统检测
  → 输出: metadata.json

Phase 1: 结构提取 (Structure Extraction)
  → tree-sitter 解析源码，提取符号、调用图、导入关系
  → 输出: structure.json, modules/*.json

Phase 1.5: 输出识别 (Output Identification) [后增]
  → 5 层策略识别系统对外输出
  → 输出: outputs.json

Phase 2: 模块分析 (Module Analysis)
  → LLM 分析每个模块的职责、流程、接口
  → 输出: module_analyses/*.md

Phase 2.5: 跨模块流程 (Cross-Module Flows)
  → LLM 识别端到端业务流程，生成时序图
  → 输出: cross_flows.md

Phase 3: 架构综合 (Architecture Synthesis)
  → LLM 综合所有模块分析，生成架构全景
  → 输出: synthesis.md

Phase 4: 文档组装 (Document Assembly)
  → 确定性拼接（无 LLM），生成最终文档
  → 输出: {repo}-analysis.md, {repo}-analysis.html, {repo}-io-flows.md
```

### 2.2 文件结构

```
repo-analyzer/
├── main.py                    # CLI + 流水线编排
├── llm_client.py              # OpenAI 兼容 API 客户端
├── phase0_recon.py            # Phase 0: 侦察
├── phase1_structure.py        # Phase 1: tree-sitter 结构提取
├── phase25_cross_flows.py     # Phase 2.5: 跨模块流程
├── prompts.py                 # 所有 LLM prompt 模板
├── callback_detection.py      # C 函数指针/回调检测
├── output_identification.py   # Phase 1.5: 5 层输出识别
├── cross_validation.py        # 交叉验证引擎
├── accuracy.py                # LLM 准确性框架 (7 项技术)
├── spark_analysis.py          # Spark SQL/UDF 分析
├── pipeline_improvements.py   # 流水线改进（模糊匹配、自动拆分等）
├── report_gen.py              # HTML 报告、TOC、标题规范化
├── mermaid_rules.md           # Mermaid 语法完整参考
├── requirements.txt           # 依赖: httpx, markdown
└── DEVELOPMENT_LOG.md         # 本文件
```

---

## 3. Phase 0-1: 基础流水线

### 3.1 Phase 0: 侦察

**实现**: `phase0_recon.py`

**功能**:
- 扫描目录结构，排除 .git/node_modules 等
- 统计文件类型和代码行数
- 检测构建系统（CMake/Make/Gradle/Maven/Cargo/npm 等）
- 识别入口文件

**关键技术决策**:
- 使用 `os.walk` 而非 `pathlib.rglob`（性能更好）
- 语言检测基于文件扩展名映射（30+ 种语言）
- 构建系统通过特定文件名检测（CMakeLists.txt, Makefile 等）

### 3.2 Phase 1: 结构提取

**实现**: `phase1_structure.py`

**功能**:
- tree-sitter 解析源码为 AST
- 提取符号（函数、类、方法、变量）及签名
- 提取调用图（直接调用 + 间接调用）
- 提取导入/包含关系
- 提取嵌入式 SQL 语句
- 回调/函数指针检测

**支持的语言**: C, C++, Java, Python, Scala, SQL, XML

**数据模型**:
```python
@dataclass
class Symbol:
    name: str           # 符号名
    kind: str           # function/class/method/variable/sql_statement/xml_element
    file: str           # 相对路径
    line: int           # 起始行
    end_line: int       # 结束行
    signature: str      # 签名
    return_type: str    # 返回类型
    params: list[dict]  # 参数列表
    parent: str         # 父级（类/命名空间）

@dataclass
class CallEdge:
    caller: str         # 调用者（限定名）
    callee: str         # 被调用者
    file: str           # 所在文件
    line: int           # 行号

@dataclass
class FileAnalysis:
    path: str
    language: str
    symbols: list[dict]
    imports: list[dict]
    calls: list[dict]
    sql_stmts: list[dict]
    spark_cross_ref: list[dict]
```

**回调检测** (`callback_detection.py`):
- 检测 C 函数指针结构体
- 检测回调注册模式
- 检测间接调用
- 检测分发表（dispatch tables）

---

## 4. Windows 兼容性

### 4.1 SSE 响应解析

**问题**: 远程 LLM 服务器（尤其 Windows 上的 OpenAI 兼容服务）返回 SSE 格式而非 JSON。

**SSE 格式**:
```
data: {"id":"...","choices":[{"delta":{"content":"Hello"}}]}
data: {"id":"...","choices":[{"delta":{"content":" world"}}]}
data: [DONE]
```

**解决方案**: `llm_client.py` 中的 `_parse_sse_response()`:
1. 检测响应是否以 `data:` 开头
2. 解析每个 `data:` 行为 JSON
3. 收集所有 `delta.content` 片段
4. 拼接为完整内容
5. 构造标准 OpenAI 响应格式

### 4.2 UTF-8 编码

**问题**: 中文 Windows 默认编码为 GBK，所有 `open()` 调用会产生乱码。

**解决方案**: 所有 5 个 Python 文件中的 17 处 `open()` 调用都显式添加 `encoding="utf-8"`。

### 4.3 超时和重试

**问题**: 远程 LLM 不稳定，需要容错。

**解决方案**:
- `--timeout` 参数（默认 300s）
- `--retry` 参数（默认 3 次）
- 指数退避（1s → 2s → 4s）
- health_check 超时从 5s 增加到 min(15, timeout)

---

## 5. Mermaid 图表系统

### 5.1 问题背景

LLM 生成的 Mermaid 图表经常有语法错误，导致渲染失败。需要：
1. 在 prompt 中明确语法规则
2. 在后处理中自动修复常见错误

### 5.2 Mermaid 语法规则研究

从 mermaid.js.org 官方文档获取完整规则，编写 `mermaid_rules.md`（10KB）。

**关键发现**:
- `end` 是保留字，小写 `end` 作为标签会导致整个图崩溃
- 节点 ID 以 `o` 或 `x` 开头在 `---` 后会被误解析为 circle/cross edge
- 实体编码：`#quot;` = `"`，`#59;` = `;`，`#amp;` = `&`
- 时序图中 7 种块类型（alt/opt/loop/break/par/critical/rect）都必须有匹配的 `end`
- 分号在时序图消息中是换行符，必须转义

### 5.3 Prompt 中的规则

**Flowchart 规则（7 条）**:
1. 特殊字符标签必须引号包裹
2. `=` 禁止出现在标签中
3. 菱形节点恰好 2 条出边
4. subgraph 必须有 ID 和 end
5. 边标签含特殊字符时引号包裹
6. 禁止嵌套引号
7. URL 禁止协议前缀

**Sequence Diagram 规则（8 条）**:
1. participants ≤ 6（模块级）
2. 消息 ≤ 15 条
3. 只展示跨模块调用
4. 消息标签禁止嵌套引号
5. break 必须有匹配 end
6. alt/else 必须有匹配 end
7. 回调链路简化为模块级调度
8. participant 用 as 别名

### 5.4 后处理函数 `fix_mermaid_syntax()`

**初版实现**: 逐行状态机，跟踪 `in_mermaid` 状态。
**问题**: 有 bug 导致非 Mermaid 内容被丢弃（29/33 Mermaid 块为空）。

**重写**: 提取/修复/重组策略：
1. 用 `string.find()` 将内容分割为文本和 Mermaid 块
2. 对每个 Mermaid 块独立修复（`_fix_single_mermaid_block()`）
3. 用 `_wrap_mermaid_in_details()` 包裹为可折叠标签

**自动修复的 13 种问题**:
1. 未引用的括号：`NODE[text (stuff)]` → `NODE["text stuff"]`
2. 菱形节点中的括号
3. 边标签中的括号
4. 边箭头中的括号
5. 菱形中的赋值：`{"x = true"}` → `{"x is true"}`
6. 方括号中的赋值：`["x = true"]` → `["set x to true"]`
7. 保留字 `end`：`A["end"]` → `A["End"]`
8. o/x 节点 ID 陷阱：`A---ops` → `A--- ops`
9. subgraph 无 ID
10. 时序图嵌套引号
11. 时序图分号转义
12. 未闭合的块（自动注入 end）
13. URL 协议前缀

### 5.5 图表大小控制

**问题**: 大图表不可读。

**解决方案**:
- 流程图 ≤ 12 节点，超出拆分
- 时序图 ≤ 10 消息，≤ 5 参与者
- 使用 `flowchart LR`（左右布局）节省纵向空间
- 标签 ≤ 15 字符
- 合并线性路径
- 所有图表用 `<details>` 折叠标签包裹

---

## 6. 文档生成系统

### 6.1 TOC 生成

**实现**: `report_gen.py` 中的 `generate_toc()`

**锚点规则**（GitHub 兼容）:
- 小写化
- 空格转连字符
- 移除反引号
- 移除特殊字符（保留 CJK、数字、字母、连字符）
- 折叠多个连字符
- 去除首尾连字符

### 6.2 标题层级规范化

**问题**: LLM 输出的标题嵌入到汇总文档时层级错位。

**实现**: `normalize_headings(content, base_level)`
- 找到最小标题级别
- 计算偏移量，统一移位
- 删除空标题（标题后无内容直接到下一个标题）
- 保护代码块内的标题

### 6.3 HTML 报告

**实现**: `report_gen.py` 中的 `generate_html_report()`

**遵循规范**:
- HTML5（WHATWG Living Standard）
- CSS3（CSS Snapshot 2025）
- GFM（GitHub Flavored Markdown）

**特性**:
- 深色侧边栏目录（IntersectionObserver 跟踪当前位置）
- 主内容区 960px 居中
- Mermaid.js CDN 延迟加载
- 代码块暗色主题
- 表格交替行色
- 折叠区块样式
- 打印友好样式
- CJK 排版支持
- `:focus-visible` 键盘导航
- `scroll-margin-top` 锚点偏移
- `color-scheme: light dark`
- `scrollbar-width`/`scrollbar-color` 标准属性

### 6.4 IO 流文档

**实现**: `output_identification.py` 中的 `generate_io_flow_document()`

**结构**:
1. 输出全景表（标识、类型、位置、置信度、输入数）
2. 每个输出的详解（输入来源、处理链路、代码上下文）
3. 统计摘要

---

## 7. XML/Spark 支持

### 7.1 tree-sitter-xml

**依赖**: `tree-sitter-xml` (已安装 v0.7.0)

**API**: `Language(tsxml.language_xml())`（注意不是 `language()`）

**AST 结构**:
```
document → element
  element → STag (Name + Attributes) + content (CharData/nested elements) + ETag
```

### 7.2 XML 提取器

**实现**: `phase1_structure.py` 中的 `_extract_xml()`

**提取内容**:
- XML 元素 → `xml_element` 符号
- 属性 → 元素签名
- 文本内容中的 SQL → `sql_in_xml` 符号
- SQL 中的函数调用 → 调用图边

### 7.3 Spark 分析模块

**实现**: `spark_analysis.py`

**功能**:
- 300+ Spark 内置函数分类（聚合、窗口、字符串、数学、日期、集合、条件等）
- SQL 函数调用提取和分类
- UDF 检测（9 种 Scala/Java 注册模式）
- XML 加载器检测（8 种模式）
- 表引用提取 + CTE 识别

**UDF 检测模式**:
```python
spark.udf.register("name", func)
spark.udf.registerJavaFunction("name", "class")
registerFunction("name", func)
@UDF annotation
```

### 7.4 交叉引用

在 Phase 1 中，对 Scala/Java 文件自动运行：
- `_extract_spark_cross_ref()`: 检测 UDF 定义和 XML 加载器引用
- 结果存储在 `FileAnalysis.spark_cross_ref` 中

---

## 8. LLM 准确性框架

### 8.1 核心原则

1. **Grounding > Generation** — 提供充分事实，让 LLM 基于证据推理
2. **Verify > Trust** — 交叉验证每个结论
3. **Iterate > Once** — 验证-修正循环
4. **Confidence > Assumption** — 区分事实和推测

### 8.2 七项技术

| 技术 | 实现位置 | Token 成本 | 精确性提升 |
|------|----------|-----------|-----------|
| Chain-of-Thought | system prompt | +20-30% | 中 |
| Evidence Grounding | system prompt | +10-15% | 高 |
| Self-Critique | Phase 3 prompt | +100% | 高 |
| Confidence Scoring | system prompt | +5-10% | 低 |
| Iterative Refinement | Phase 2.5/3 后处理 | +50-100% | 高 |
| Decomposition | Phase 2 prompt | +30-50% | 中 |
| Structured Output | 预留 | - | - |

### 8.3 交叉验证

**实现**: `cross_validation.py`

**Ground Truth 构建** (`build_ground_truth()`):
- 从 Phase 1 结构数据构建事实索引
- 包含：调用边、符号、导入、表、UDF、XML 加载器

**验证流程** (`validate_cross_module_calls()`):
1. 从 LLM 输出中提取函数调用、表引用、UDF 引用
2. 与 Ground Truth 对比
3. 分类为：已验证 / 未验证
4. 计算准确率

**模糊匹配** (`pipeline_improvements.py` 中的 `fuzzy_match_name()`):
- 命名空间剥离：`ngx_http_process_request` → `process_request`
- 方法限定符：`Class::method` → `method`
- 标识符分词：camelCase/snake_case → token 集合
- Token 重叠度 ≥ 0.7 视为匹配

### 8.4 迭代修正

**流程**:
```
LLM 生成 → 交叉验证 → 准确率 < 70%?
  ├─ 否 → 输出结果
  └─ 是 → 构造结构化修正 prompt
         → LLM 重新生成 → 再次验证 → 输出
```

**结构化反馈** (`build_structured_refinement_prompt()`):
- 每个错误给出具体修正建议
- 提供 Ground Truth 证据
- 建议替换方案

---

## 9. 输出驱动分析

### 9.1 设计理念

**传统方式**: 文件 → 模块 → 调用图 → 综合（自底向上，代码视角）
**输出驱动**: 输出 → 追溯 → 输入/处理链路 → 模块划分（自顶向下，业务视角）

### 9.2 五层输出识别

**实现**: `output_identification.py`

| 层 | 方法 | 精确度 | 召回率 |
|----|------|--------|--------|
| Layer 1 | Regex 模式匹配 | 95%+ | 60% |
| Layer 2 | AST 结构分析 | 90%+ | 75% |
| Layer 3 | SQL 输出分析 | 95%+ | 80% |
| Layer 4 | 数据流追踪 | 80%+ | 85% |
| Layer 5 | LLM 辅助识别 | 70%+ | 90% |

**Layer 1 模式（~25 种）**:
- SQL: INSERT INTO, CREATE TABLE, MERGE INTO
- Spark: .write.parquet, .saveAsTable, .insertInto
- File: open("w"), .to_csv, .to_json, .to_parquet
- API: @GetMapping, @PostMapping, Flask route
- Message: .send, .publish, .emit

**库项目检测** (`detect_library_outputs()`):
- 公共头文件目录（include/, inc/, api/）
- 构建文件中的库目标（add_library, crate-type）

### 9.3 大模块自动拆分

**实现**: `auto_split_modules()`

**策略**:
1. 按子目录分组
2. 过小组并入大组
3. 仍无合理分组则按文件数切分
4. 每个子模块 ≤ 10 个文件

### 9.4 动态重建指南

**实现**: `generate_rebuild_guide()`

**支持的构建系统**: CMake, Make, Gradle, Maven, Cargo, npm, Go modules, Python (pip/pyproject)

---

## 10. 测试与修复

### 10.1 LevelDB 测试

**仓库**: google/leveldb (C++ 键值存储库)
**规模**: 149 文件, 22K+ C++ 行, 6K C 行

**测试结果**:
```
Phase 0: 149 files, C++/C, CMake
Phase 1: 91 files (42 test skipped), 1201 symbols, 3291 call edges
Phase 1.5: 1 public API output (library project)
Phase 2: 13 modules (auto-split from 7), 7-21KB each
Phase 2.5: Cross-module flows (6.5KB, 43% accuracy, auto-refined)
Phase 3: Architecture synthesis (10.9KB)
Phase 4: Final doc 28KB + HTML 53KB
```

### 10.2 发现并修复的 Bug

| # | Bug | 根因 | 修复 |
|---|-----|------|------|
| 1 | SSE 响应解析失败 | 远程服务器返回 SSE 格式 | `_parse_sse_response()` |
| 2 | Windows 乱码 | 默认 GBK 编码 | 所有 `open()` 加 `encoding="utf-8"` |
| 3 | Mermaid `end` 崩溃 | 小写 `end` 是保留字 | 自动替换为 `End` |
| 4 | Mermaid `=` 解析错误 | 标签中不能有 `=` | 改写为自然语言 |
| 5 | TOC 锚点失效 | 硬编码锚点 | 动态生成 `generate_toc()` |
| 6 | 标题层级错位 | LLM 输出嵌入时层级不对 | `normalize_headings()` |
| 7 | **Mermaid 块为空（严重）** | 旧的 `fix_mermaid_syntax` 逐行状态机 bug | 重写为提取/修复/重组策略 |
| 8 | **qwen3 输出为空** | 推理模型输出在 `reasoning_content` | `_extract_content()` 支持 reasoning |
| 9 | **模块分析被缓存污染** | 自动拆分后旧文件未清理 | 拆分时清除旧文件 |
| 10 | **LM Studio 上下文太小** | 默认 n_ctx=4096 | 需在 UI 中调大 |

### 10.3 关键经验

1. **先测试再提交** — 每次改动后 `py_compile` 验证语法
2. **小步迭代** — 按功能拆分 commit，每个可独立回滚
3. **双分支同步** — feat 分支开发，稳定后合并到 main
4. **Mermaid 必须后处理** — 即使 prompt 写得再好，LLM 仍会出错
5. **交叉验证是核心** — LLM 会编造调用关系，必须验证
6. **模块摘要不能太短** — 500/800 字符丢失关键细节，用 2000 字符
7. **推理模型需要更多 token** — qwen3 推理消耗大量 token，max_tokens ≥ 16384
8. **缓存是双刃剑** — 旧的损坏结果会被缓存，需要 `--force` 覆盖

---

## 11. 最终架构

### 11.1 流水线图

```
输入: 代码仓库路径
  │
  ▼
Phase 0: 侦察 ──────────────────────────────────────── metadata.json
  │  文件扫描、语言统计、构建系统检测
  ▼
Phase 1: 结构提取 ──────────────────────────────────── structure.json, modules/*.json
  │  tree-sitter AST → 符号、调用图、导入、SQL、回调
  ▼
Phase 1.5: 输出识别 ────────────────────────────────── outputs.json
  │  5 层策略: regex → AST → SQL → 数据流 → LLM
  │  库项目: 公共头文件检测
  ▼
Phase 2: 模块分析 (LLM) ───────────────────────────── module_analyses/*.md
  │  自动拆分大模块 (≤10 文件)
  │  CoT + Grounding + Confidence + Decomposition
  │  输出驱动 prompt (输入→输出流程)
  ▼
Phase 2.5: 跨模块流程 (LLM) ───────────────────────── cross_flows.md
  │  结构化 Ground Truth 注入
  │  交叉验证 + 模糊匹配
  │  迭代修正 (准确率 < 70% 时)
  ▼
Phase 3: 架构综合 (LLM) ───────────────────────────── synthesis.md
  │  Self-Critique + 交叉验证
  │  迭代修正
  ▼
Phase 4: 文档组装 (无 LLM) ─────────────────────────── {repo}-analysis.md
  │  标题规范化 → 动态 TOC → Mermaid 后处理       {repo}-analysis.html
  │  动态重建指南                                  {repo}-io-flows.md
  │  HTML 报告生成                                 {repo}-io-flows.html
  ▼                                               {repo}-modules/*.md
输出: 完整分析文档
```

### 11.2 核心模块职责

| 模块 | 职责 | 行数 |
|------|------|------|
| `main.py` | CLI、流水线编排、文档组装 | ~1050 |
| `llm_client.py` | API 客户端、SSE 解析、重试 | ~160 |
| `phase1_structure.py` | tree-sitter 提取、XML 支持 | ~1150 |
| `output_identification.py` | 5 层输出识别、IO 流文档 | ~650 |
| `cross_validation.py` | Ground Truth 构建、验证 | ~340 |
| `accuracy.py` | 7 项准确性技术 | ~270 |
| `spark_analysis.py` | Spark 函数/UDF/SQL 分析 | ~450 |
| `pipeline_improvements.py` | 模糊匹配、自动拆分、动态指南 | ~530 |
| `report_gen.py` | HTML 报告、TOC、标题规范化 | ~860 |
| `prompts.py` | LLM prompt 模板 | ~420 |

---

## 12. CLI 参数参考

```bash
python main.py <repo_path> [options]

必需:
  repo_path                    代码仓库路径

可选:
  --output, -o PATH            输出文档路径 (默认: {repo}-analysis.md)
  --phase, -p RANGE            阶段范围: 0, 0-1, 2-4, all (默认: all)
  --base-url URL               LLM API 地址 (默认: http://127.0.0.1:1234/v1)
  --api-key KEY                API 密钥 (或 LLM_API_KEY 环境变量)
  --model, -m MODEL            模型名 (默认: qwen3.5-35b-a3b)
  --max-files N                最大文件数 (默认: 5000)
  --timeout, -t SECS           LLM 超时秒数 (默认: 300)
  --retry N                    失败重试次数 (默认: 3)
  --context-size N             源码预览 token 数 (默认: 4000)
  --skip-tests                 跳过测试文件
  --skip-synthesis             跳过 Phase 3 (使用已有结果)
  --force                      强制重新生成 (忽略缓存)
```

---

## 13. 已知问题与改进方向

### 13.1 已知问题

1. **超时**: 13 个模块总耗时 >10 分钟，最后几个超时
2. **交叉验证准确率**: LevelDB 测试中 43%→45%，大量间接调用未检测到
3. **推理模型 token 消耗**: qwen3 推理消耗大量 token
4. **大模块拆分**: 目录分组有时不够合理

### 13.2 改进方向

1. **并行分析**: 多模块并行 LLM 调用
2. **增量分析**: 只分析变更的文件
3. **更好的间接调用检测**: 虚函数表、模板实例化
4. **多语言支持**: Go, Rust, JavaScript/TypeScript
5. **交互式报告**: 可点击的架构图、可搜索的符号表
6. **CI/CD 集成**: GitHub Action 自动生成分析报告

---

## 附录 A: 开发时间线

| 日期 | 内容 | Commit |
|------|------|--------|
| 2026-05-14 | 初始流水线 + nginx 测试 | d326644 |
| 2026-05-14 | callback 检测 + Mermaid 修复 | b9c2c96 |
| 2026-05-14 | Windows 远程 LLM 支持 | 48b44df |
| 2026-05-15 | SSE 解析 + UTF-8 编码 | 24954da |
| 2026-05-15 | Mermaid 完整规则 + 后处理 | a73e9fb, 41cf63c |
| 2026-05-15 | 图表大小优化 + 折叠 | 25576bf |
| 2026-05-15 | HTML 报告 + TOC + 标题规范化 | f69dc99 |
| 2026-05-15 | HTML5/CSS3/GFM 规范更新 | e810d17 |
| 2026-05-15 | XML/Spark 支持 | 23a40f5 |
| 2026-05-15 | 交叉验证 + 准确性框架 | ac3db8f, 4d4ea2f |
| 2026-05-15 | --timeout/--retry | 74a2e1e |
| 2026-05-15 | 输出驱动分析 + IO 流文档 | 2f90b68 |
| 2026-05-15 | --skip-tests | 248f552 |
| 2026-05-16 | Mermaid 重写 + 推理模型支持 | d2d8330 |
| 2026-05-16 | 7 项流水线改进 | ccf1bed |
| 2026-05-16 | 旧文件清理 + 空 Mermaid 修复 | 606c428 |

## 附录 B: 环境兼容性

| 配置 | macOS (本地) | Windows (远程) |
|------|-------------|---------------|
| --base-url | http://127.0.0.1:1234/v1 (默认) | https://server/v1 |
| --api-key | 不需要 | --api-key sk-xxx |
| 响应格式 | JSON | SSE (自动检测解析) |
| 编码 | UTF-8 (原生) | UTF-8 (显式指定) |
| 模型 | qwen3.5-35b-a3b | 任意 OpenAI 兼容 |

## 附录 C: 关键依赖

```
httpx           # HTTP 客户端
markdown        # Markdown → HTML (可选，有 fallback)
tree-sitter     # AST 解析
tree-sitter-c   # C 语言语法
tree-sitter-cpp # C++ 语法
tree-sitter-java # Java 语法
tree-sitter-python # Python 语法
tree-sitter-scala # Scala 语法
tree-sitter-sql # SQL 语法
tree-sitter-xml # XML 语法
```
