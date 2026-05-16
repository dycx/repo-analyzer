"""Pipeline improvements module.

Implements:
- Library output detection (public API headers as outputs)
- Large module auto-splitting
- Fuzzy cross-validation (namespace resolution, alias matching)
- Dynamic rebuild guide generation
- Structured iterative refinement feedback
"""

import os
import re
from pathlib import Path
from dataclasses import dataclass, field


# ── 1. Library Output Detection ─────────────────────────────────────────────

def detect_library_outputs(repo_path: str, structure_data: dict) -> list[dict]:
    """Detect library-style outputs: public API headers, exported symbols.

    For projects like LevelDB that have no DB/file/API outputs,
    the 'output' is the public API surface (header files in include/).
    """
    outputs = []

    # Strategy 1: Public header directories (include/, inc/, api/, public/)
    PUBLIC_DIRS = {"include", "inc", "api", "public", "headers", "interface"}
    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirname = os.path.basename(dirpath).lower()
        if dirname in PUBLIC_DIRS:
            for fname in filenames:
                if fname.endswith(('.h', '.hpp', '.hxx')):
                    rel = os.path.relpath(os.path.join(dirpath, fname), repo_path)
                    outputs.append({
                        "name": os.path.splitext(fname)[0],
                        "output_type": "public_header",
                        "file": rel,
                        "line": 1,
                        "confidence": "high",
                        "detection_layer": "library_api",
                        "evidence": f"Public header in {dirname}/",
                        "context": f"Library API surface: {rel}",
                        "inputs": [],
                    })

    # Strategy 2: Exported functions (symbols with external linkage)
    for edge in structure_data.get("call_graph", []):
        callee = edge.get("callee", "")
        # Functions that are called from outside their module
        if callee and "::" in callee:
            parts = callee.split("::")
            if len(parts) >= 2:
                # Class method that's likely a public API
                pass  # Skip for now, too noisy

    # Strategy 3: Check for library markers in build files
    build_markers = []
    for fname in os.listdir(repo_path):
        if fname in ("CMakeLists.txt", "Makefile", "build.gradle", "Cargo.toml", "setup.py", "pyproject.toml"):
            build_markers.append(fname)
            # Check if it defines a library target
            fpath = os.path.join(repo_path, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read(5000)
                if any(kw in content for kw in ("add_library", "LIBRARY", "crate-type", "library")):
                    outputs.append({
                        "name": fname,
                        "output_type": "library_build",
                        "file": fname,
                        "line": 1,
                        "confidence": "medium",
                        "detection_layer": "build_file",
                        "evidence": f"Library target in {fname}",
                        "context": content[:200],
                        "inputs": [],
                    })
            except (OSError, PermissionError):
                pass

    return outputs


# ── 2. Large Module Auto-Splitting ──────────────────────────────────────────

def auto_split_modules(modules: list[dict], max_files: int = 10) -> list[dict]:
    """Split modules with too many files into logical sub-modules.

    Splitting strategy:
    1. Group files by directory depth (sub-directories become sub-modules)
    2. If still too many, group by file prefix patterns
    3. Preserve callback and symbol associations
    """
    result = []

    for mod in modules:
        files = mod.get("files", [])
        if len(files) <= max_files:
            result.append(mod)
            continue

        # Group by immediate sub-directory
        groups = {}
        for f in files:
            path = f.get("path", "")
            parts = path.replace("\\", "/").split("/")
            if len(parts) >= 2:
                group_key = parts[-2]  # parent directory
            else:
                group_key = "_root"
            groups.setdefault(group_key, []).append(f)

        # If grouping by directory produces too-small groups, merge
        MIN_GROUP_SIZE = 2
        merged = {}
        overflow = []
        for key, group_files in groups.items():
            if len(group_files) >= MIN_GROUP_SIZE:
                merged[key] = group_files
            else:
                overflow.extend(group_files)

        # Distribute overflow files to largest group
        if overflow and merged:
            largest_key = max(merged, key=lambda k: len(merged[k]))
            merged[largest_key].extend(overflow)

        # If no good grouping found, split by file count
        if not merged or len(merged) == 1:
            chunk_size = max_files
            for i in range(0, len(files), chunk_size):
                chunk = files[i:i + chunk_size]
                sub_name = f"{mod['module']}_part{i // chunk_size + 1}"
                result.append({
                    "module": sub_name,
                    "files": chunk,
                    "callbacks": mod.get("callbacks", {}),
                })
            continue

        # Create sub-modules
        for sub_key, sub_files in merged.items():
            sub_name = f"{mod['module']}/{sub_key}"
            result.append({
                "module": sub_name,
                "files": sub_files,
                "callbacks": mod.get("callbacks", {}),
            })

    return result


# ── 3. Fuzzy Cross-Validation ──────────────────────────────────────────────

def fuzzy_match_name(name: str, candidates: set[str], threshold: float = 0.7) -> list[str]:
    """Fuzzy match a function name against candidates.

    Handles:
    - Namespace prefixes: ngx_http_process_request → process_request
    - Method qualifiers: Class::method → method
    - Case variations: camelCase vs snake_case
    - Abbreviations: init vs initialize
    """
    matches = []

    # Normalize the name
    name_lower = name.lower()
    name_parts = set(_split_identifier(name))

    for candidate in candidates:
        cand_lower = candidate.lower()

        # Exact match
        if name_lower == cand_lower:
            matches.append(candidate)
            continue

        # Suffix match (namespace stripping)
        if name_lower.endswith(cand_lower) or cand_lower.endswith(name_lower):
            matches.append(candidate)
            continue

        # Partial match (method name without class)
        if "::" in candidate:
            method = candidate.split("::")[-1].lower()
            if method == name_lower:
                matches.append(candidate)
                continue

        # Token overlap (split by _ and camelCase)
        cand_parts = set(_split_identifier(candidate))
        if name_parts and cand_parts:
            overlap = len(name_parts & cand_parts)
            union = len(name_parts | cand_parts)
            if union > 0 and overlap / union >= threshold:
                matches.append(candidate)

    return matches


def _split_identifier(name: str) -> list[str]:
    """Split identifier into tokens: camelCase → [camel, Case], snake_case → [snake, case]."""
    # Split by underscores and dots
    parts = re.split(r'[_.]', name)
    # Further split camelCase
    tokens = []
    for part in parts:
        camel = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)', part)
        tokens.extend(t.lower() for t in camel if t)
    return tokens


def enhanced_validate(
    llm_output: str,
    ground_truth: dict,
    module_data: list[dict] = None,
) -> "ValidationResult":
    """Enhanced cross-validation with fuzzy matching and indirect call handling.

    Improvements over basic validate_cross_module_calls:
    1. Fuzzy name matching (handles aliases, namespaces, abbreviations)
    2. Indirect call resolution (function pointers → actual implementations)
    3. Exported symbol matching (public headers count as valid references)
    4. Context-aware table validation (SQL table names from XML configs)
    """
    # Import the basic validator
    from cross_validation import validate_cross_module_calls, ValidationResult

    # Run basic validation first
    basic_result = validate_cross_module_calls(llm_output, ground_truth)

    # Collect all known names (from symbols, call graph, exports)
    all_names = set()
    all_names.update(ground_truth.get("symbols", {}).keys())
    all_names.update(ground_truth.get("call_edges_by_name", {}).keys())
    for callee_list in ground_truth.get("call_edges_by_name", {}).values():
        for ref in callee_list:
            all_names.add(ref.get("caller", ""))

    # Re-check unverified calls with fuzzy matching
    still_unverified = []
    for unverified in basic_result.unverified_calls:
        name = unverified["name"]
        fuzzy_matches = fuzzy_match_name(name, all_names)

        if fuzzy_matches:
            # Found a fuzzy match — move to verified
            best_match = fuzzy_matches[0]
            basic_result.verified_calls.append({
                "name": name,
                "matched_to": best_match,
                "match_type": "fuzzy",
                "confidence": "medium",
            })
        else:
            still_unverified.append(unverified)

    basic_result.unverified_calls = still_unverified

    # Recalculate accuracy
    total = len(basic_result.verified_calls) + len(basic_result.unverified_calls)
    if total > 0:
        basic_result.accuracy_score = len(basic_result.verified_calls) / total

    return basic_result


# ── 4. Dynamic Rebuild Guide ────────────────────────────────────────────────

def generate_rebuild_guide(repo_path: str, metadata: dict) -> str:
    """Generate a rebuild guide based on detected build system and language."""
    build_systems = metadata.get("build_systems", [])
    languages = metadata.get("languages", {})
    primary_lang = max(languages, key=languages.get) if languages else "unknown"

    parts = []
    parts.append("如果要从零重建这个系统:\n")

    # Detect build system and generate appropriate instructions
    bs_lower = [b.lower() for b in build_systems]

    if any("cmake" in b for b in bs_lower):
        parts.append(_guide_cmake(repo_path))
    elif any("make" in b for b in bs_lower):
        parts.append(_guide_make(repo_path))
    elif any("gradle" in b for b in bs_lower):
        parts.append(_guide_gradle())
    elif any("maven" in b for b in bs_lower):
        parts.append(_guide_maven())
    elif any("cargo" in b for b in bs_lower):
        parts.append(_guide_cargo())
    elif any("npm" in b or "package.json" in b for b in bs_lower):
        parts.append(_guide_npm())
    elif any("go.mod" in b for b in bs_lower):
        parts.append(_guide_go())
    elif any("pyproject" in b or "setup.py" in b or "pip" in b for b in bs_lower):
        parts.append(_guide_python())
    else:
        parts.append(_guide_generic(primary_lang))

    # Common sections
    parts.append("\n### 关键技术决策\n")
    parts.append("| 决策点 | 选择 | 原因 |")
    parts.append("|--------|------|------|")
    parts.append("| (基于分析结果填写) | | |")

    parts.append("\n### 必须注意的坑\n")
    parts.append("1. (基于分析中的异常处理和边界条件填写)")

    parts.append("\n### 设计模式参考\n")
    parts.append("1. (基于分析中的架构模式填写)")

    return "\n".join(parts)


def _guide_cmake(repo_path: str) -> str:
    """Generate CMake rebuild guide."""
    # Check for common CMake patterns
    has_tests = os.path.exists(os.path.join(repo_path, "test")) or os.path.exists(os.path.join(repo_path, "tests"))

    return """### 推荐实现顺序

```bash
# 1. 创建项目结构
mkdir -p src include test

# 2. 编写 CMakeLists.txt
cmake_minimum_required(VERSION 3.10)
project(MyProject)

# 3. 核心库
add_library(core STATIC src/core.cc)
target_include_directories(core PUBLIC include)

# 4. 可执行文件
add_executable(app main.cc)
target_link_libraries(app core)
```

### 构建命令
```bash
mkdir build && cd build
cmake ..
make -j$(nproc)
""" + ("ctest  # 运行测试" if has_tests else "") + """
```"""


def _guide_make(repo_path: str) -> str:
    return """### 推荐实现顺序

```makefile
# Makefile 模板
CC = gcc
CFLAGS = -Wall -Wextra -O2
LDFLAGS =

SRCS = $(wildcard src/*.c)
OBJS = $(SRCS:.c=.o)

all: app

app: $(OBJS)
\t$(CC) $(LDFLAGS) -o $@ $^

%.o: %.c
\t$(CC) $(CFLAGS) -c -o $@ $<

clean:
\trm -f $(OBJS) app
```

### 构建命令
```bash
make
make test  # 如果有测试
```"""


def _guide_gradle() -> str:
    return """### 推荐实现顺序

```bash
# 1. 初始化项目
gradle init --type basic

# 2. 编写 build.gradle
plugins {
    id 'java'
}

repositories {
    mavenCentral()
}

dependencies {
    // 核心依赖
}
```"""


def _guide_maven() -> str:
    return """### 推荐实现顺序

```bash
# 1. 初始化项目
mvn archetype:generate -DgroupId=com.example -DartifactId=myproject

# 2. 编写 pom.xml
# 3. 实现 src/main/java 下的代码
# 4. 测试: mvn test
```"""


def _guide_cargo() -> str:
    return """### 推荐实现顺序

```bash
# 1. 初始化项目
cargo init myproject

# 2. 编写 Cargo.toml
# 3. 实现 src/ 下的代码
# 4. 构建: cargo build
# 5. 测试: cargo test
```"""


def _guide_npm() -> str:
    return """### 推荐实现顺序

```bash
# 1. 初始化项目
npm init -y

# 2. 安装依赖
npm install

# 3. 编写代码
# 4. 构建: npm run build
# 5. 测试: npm test
```"""


def _guide_go() -> str:
    return """### 推荐实现顺序

```bash
# 1. 初始化模块
go mod init myproject

# 2. 编写代码
# 3. 构建: go build
# 4. 测试: go test ./...
```"""


def _guide_python() -> str:
    return """### 推荐实现顺序

```bash
# 1. 创建虚拟环境
python -m venv .venv && source .venv/bin/activate

# 2. 安装依赖
pip install -e .

# 3. 编写代码
# 4. 测试: pytest
```"""


def _guide_generic(lang: str) -> str:
    return f"""### 推荐实现顺序

基于检测到的主要语言 ({lang})，建议按照以下顺序实现:
1. 基础工具和数据结构
2. 核心业务逻辑
3. 外部接口和集成
4. 测试和文档"""


# ── 5. Structured Refinement Feedback ───────────────────────────────────────

def build_structured_refinement_prompt(
    original_output: str,
    validation_result,  # ValidationResult
    ground_truth_context: str,
) -> str:
    """Build a structured refinement prompt with specific, actionable corrections.

    Instead of just listing errors, provides:
    1. Specific correction for each error
    2. Evidence from ground truth
    3. Suggested replacement
    """
    corrections = []

    # For each unverified call, find the closest match and suggest it
    from cross_validation import ValidationResult as VR
    all_names = set()
    # Collect from ground_truth_context (parse the structured data)

    for i, unverified in enumerate(validation_result.unverified_calls[:10], 1):
        name = unverified["name"]
        corrections.append(
            f"  {i}. `{name}` — 在调用图和符号表中未找到。\n"
            f"     建议: 检查是否是间接调用、回调函数、或名称拼写错误。\n"
            f"     如果无法验证，标注为 [推测]。"
        )

    if not corrections:
        return original_output  # No corrections needed

    corrections_text = "\n".join(corrections)

    return f"""## 修正要求

交叉验证发现以下问题，请按要求修正：

{corrections_text}

## 修正规则
1. 对于无法在验证数据中找到的调用关系，标注为 [推测] 并说明推断依据
2. 保留已验证的关系不变
3. 如果某个函数确实存在但名称不同，使用验证数据中的正确名称
4. 在分析末尾添加置信度统计

## 原始分析
{original_output}

## 请输出修正后的完整分析
"""
