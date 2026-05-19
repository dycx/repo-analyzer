# repo-analyzer — 代码仓库逆向工程工具

从代码仓库生成"可重建"级别的逆向工程文档。

> 逆向生成的文档，能让开发者在无误的情况下重建一个功能等价的项目（误差 < 5%）。

## 支持语言

| 语言 | tree-sitter | 符号提取 | 调用图 | 回调检测 |
|------|:-----------:|:--------:|:------:|:--------:|
| C | ✅ | ✅ | ✅ | ✅ |
| C++ | ✅ | ✅ | ✅ | — |
| Java | ✅ | ✅ | ✅ | — |
| Scala | ✅ | ✅ | ✅ | — |
| Python | ✅ | ✅ | ✅ | — |
| SQL | ✅ | ✅ | — | — |

## 安装

```bash
# 1. 克隆仓库
git clone https://github.com/dycx/repo-analyzer.git
cd repo-analyzer

# 2. 创建虚拟环境并安装依赖
uv venv --python 3.11 .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

uv pip install tree-sitter tree-sitter-c tree-sitter-cpp \
    tree-sitter-java tree-sitter-python tree-sitter-scala \
    tree-sitter-sql pygount httpx pyyaml
```

## 快速开始

### 本地 LM Studio（默认）

```bash
source .venv/bin/activate

# 全流程分析
python main.py /path/to/your/repo

# 只运行结构提取（不需要 LLM）
python main.py /path/to/your/repo --phase 0-1

# 只运行 LLM 分析（需要先完成 Phase 0-1）
python main.py /path/to/your/repo --phase 2-4

# 自定义输出路径
python main.py /path/to/your/repo -o ~/analysis-output.md
```

### 输出数据流 / 算法说明模式（新）

如果目标是说明“输入数据如何经过计算得到输出文件/表”，使用 `trace` 模式：

```bash
# 生成按输出组织的数据流与算法说明
python main.py trace /path/to/your/repo

# 或使用包入口
python -m repo_analyzer trace /path/to/your/repo

# 自定义输出路径
python main.py trace /path/to/your/repo -o ~/output-trace.md
```

`trace` 模式当前聚焦：

- Java / Scala Spark 数据处理代码
- Python Pandas / Spark 数据处理代码
- SQL 文件与嵌入式 SQL
- XML 配置中的 Spark SQL step
- 文件输出、表输出、API 返回、消息发布等输出点

输出报告按“输出物”组织，每个输出包含：

- 输入来源
- 输入到输出的处理流程
- 过滤、字段选择、字段派生、Join、Group By、聚合等计算细节
- 字段级计算规则（best effort）
- 伪代码
- 无法静态确认的上游引用

### 远程 LLM（Qwen / OpenAI 兼容）

```bash
# 方式 1: 命令行参数
python main.py /path/to/your/repo \
  --base-url https://your-qwen-server/v1 \
  --api-key sk-xxx \
  --model qwen3.5-35b-a3b

# 方式 2: 环境变量（更安全，避免 key 出现在 shell history）
export LLM_API_KEY=sk-xxx
python main.py /path/to/your/repo --base-url https://your-qwen-server/v1
```

## 流水线

```
Phase 0:   侦察          → 语言统计、目录结构、入口点        (~10秒)
Phase 1:   结构提取      → tree-sitter 符号/调用图/依赖      (~30秒)
Phase 1.5: 回调检测      → C函数指针/间接调用补全            (~2秒)
Phase 2:   模块分析      → LLM 逐模块深度分析 + 流程图       (~30分钟)
Phase 2.5: 跨模块流程    → 端到端业务流程 + 时序图           (~3分钟)
Phase 3:   架构综合      → 架构全景、数据流、接口契约        (~2分钟)
Phase 4:   文档拼装      → 最终 Markdown 文档生成            (~瞬时)
```

Phase 0-1 不需要 LLM，可以单独运行验证结构提取效果。

## 输出结构

```
/repo-root/
├── .code-analysis/
│   ├── metadata.json          # Phase 0: 仓库统计
│   ├── structure.json         # Phase 1: 符号/调用图/回调数据
│   ├── modules/               # Phase 1: 按目录分组的模块数据
│   │   ├── src_core.json
│   │   └── ...
│   ├── module_analyses/       # Phase 2: 每个模块的 LLM 分析（含 Mermaid 流程图）
│   │   ├── src_core.md
│   │   └── ...
│   ├── cross_flows.md         # Phase 2.5: 跨模块端到端流程（时序图）
│   └── synthesis.md           # Phase 3: 架构综合
└── repo-name-analysis.md      # Phase 4: 最终文档（含所有流程图）
```

## LLM 配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--base-url` | `http://127.0.0.1:1234/v1` | LLM API 端点 |
| `--api-key` | 无（或 `LLM_API_KEY` 环境变量） | API 认证密钥 |
| `--model` | `qwen3.5-35b-a3b` | 模型名称 |
| `--max-files` | 5000 | Phase 1 最大扫描文件数 |

建议 LLM context: 32K+ tokens。温度默认 0.1（低温度保证分析一致性）。

## 特性

- **断点续传**: Phase 2 会跳过已分析的模块，中断后重跑自动续接
- **智能截断**: 大文件只提取关键部分（函数签名 + 核心逻辑）
- **回调检测**: 自动识别 C 函数指针/回调模式，补全间接调用关系
- **Mermaid 流程图**: 每个模块自动生成核心业务流程图
- **跨模块时序图**: 自动提取端到端业务流程（如 HTTP 请求生命周期）
- **Mermaid 语法修复**: 自动修正 LLM 生成的 Mermaid 语法问题
- **多语言**: C/C++/Java/Scala/Python/SQL 原生支持

## 文件清单

```
main.py                  # 主编排器（含 Mermaid 修复 + 文档拼装）
phase0_recon.py          # Phase 0: 仓库侦察
phase1_structure.py      # Phase 1: tree-sitter 结构提取
callback_detection.py    # Phase 1.5: C 回调/函数指针检测
prompts.py               # "可重建"级 prompt 模板
llm_client.py            # LLM API 客户端（支持本地 + 远程）
phase25_cross_flows.py   # Phase 2.5: 跨模块流程提取
```
