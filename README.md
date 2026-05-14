# repo-analyzer — 代码仓库逆向工程工具

从代码仓库生成"可重建"级别的逆向工程文档。

## 核心原则

> 逆向生成的文档，能让开发者在无误的情况下重建一个功能等价的项目（误差 < 5%）。

## 支持语言

| 语言 | tree-sitter | 符号提取 | 调用图 |
|------|:-----------:|:--------:|:------:|
| Python | ✅ | ✅ | ✅ |
| Java | ✅ | ✅ | ✅ |
| C | ✅ | ✅ | ✅ |
| C++ | ✅ | ✅ | ✅ |
| Scala | ✅ | ✅ | ✅ |
| SQL | ✅ | ✅ | — |

## 快速开始

```bash
cd ~/code/repo-analyzer
source .venv/bin/activate

# 分析整个仓库 (需要 LM Studio 运行)
python main.py /path/to/your/repo

# 只运行结构提取 (不需要 LLM)
python main.py /path/to/your/repo --phase 0-1

# 运行 LLM 分析阶段 (需要先完成 Phase 0-1)
python main.py /path/to/your/repo --phase 2-4

# 自定义输出路径
python main.py /path/to/your/repo -o ~/analysis-output.md

# 使用不同的 LLM 端点
python main.py /path/to/your/repo --lm-studio-url http://192.168.1.100:1234/v1 --model my-model
```

## 流水线

```
Phase 0: 侦察        → 语言统计、目录结构、入口点      (10秒)
Phase 1: 结构提取    → tree-sitter符号/调用图/依赖       (30秒)
Phase 2: 模块分析    → LLM逐模块深度分析               (~30分钟)
Phase 3: 跨模块综合  → 架构、数据流、接口契约           (~5分钟)
Phase 4: 需求逆向    → 功能/非功能需求 + 最终文档       (~3分钟)
```

## 输出结构

```
/repo-root/
├── .code-analysis/
│   ├── metadata.json          # Phase 0: 仓库统计
│   ├── structure.json         # Phase 1: 符号/调用图
│   ├── modules/               # Phase 1: 按目录分组的模块数据
│   │   ├── src_core.json
│   │   └── ...
│   ├── module_analyses/       # Phase 2: 每个模块的LLM分析
│   │   ├── src_core.md
│   │   └── ...
│   └── synthesis.md           # Phase 3: 架构综合
└── repo-name-analysis.md      # Phase 4: 最终文档
```

## LM Studio 配置

- 默认端点: `http://127.0.0.1:1234/v1`
- 默认模型: `qwen3.5-35b-a3b`
- 建议 context: 32K+ tokens
- 温度: 0.1 (低温度保证分析一致性)

## 特性

- **断点续传**: Phase 2 会跳过已分析的模块
- **智能截断**: 大文件只提取关键部分
- **嵌入式SQL**: 从非SQL文件中提取SQL字符串
- **并行就绪**: 各模块分析独立，可手动并行

## 文件清单

```
main.py              # 主编排器
phase0_recon.py      # Phase 0: 仓库侦察
phase1_structure.py  # Phase 1: tree-sitter 结构提取
prompts.py           # "可重建"级 prompt 模板
llm_client.py        # LM Studio API 客户端
```
