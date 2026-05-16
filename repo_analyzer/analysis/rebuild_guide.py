"""Dynamic rebuild guide generation per build system.

Detects the build system from repository metadata and generates a
step-by-step rebuild guide in Chinese, complete with code blocks.
"""

from __future__ import annotations


import logging

logger = logging.getLogger("repo_analyzer.analysis.rebuild_guide")


def generate_rebuild_guide(repo_path: str, metadata: dict) -> str:
    """Generate a rebuild guide tailored to the detected build system.

    Parameters
    ----------
    repo_path : str
        Path to the repository root.
    metadata : dict
        Repository metadata (from Phase 0). Expected key: ``build_systems``
        (list[str]).

    Returns
    -------
    str
        Markdown rebuild guide in Chinese.
    """
    build_systems = metadata.get("build_systems", [])
    languages = metadata.get("language_distribution", {})

    logger.info("Generating rebuild guide for build systems: %s", build_systems)

    # Priority-ordered detection
    if any("CMake" in bs for bs in build_systems):
        return _guide_cmake(repo_path, metadata)
    if any("Gradle" in bs for bs in build_systems):
        return _guide_gradle(repo_path, metadata)
    if any("Maven" in bs or "pom" in bs.lower() for bs in build_systems):
        return _guide_maven(repo_path, metadata)
    if any("Cargo" in bs for bs in build_systems):
        return _guide_cargo(repo_path, metadata)
    if any("npm" in bs for bs in build_systems):
        return _guide_npm(repo_path, metadata)
    if any("Go" in bs for bs in build_systems):
        return _guide_go(repo_path, metadata)
    if any(bs in ("setuptools", "pyproject", "pip") for bs in build_systems):
        return _guide_python(repo_path, metadata)
    if any("Make" in bs for bs in build_systems):
        return _guide_make(repo_path, metadata)

    # Fallback based on dominant language
    dominant = ""
    if languages:
        dominant = max(languages, key=languages.get)  # type: ignore[arg-type]

    if dominant == "Python":
        return _guide_python(repo_path, metadata)
    if dominant in ("Java", "Scala"):
        return _guide_gradle(repo_path, metadata)
    if dominant in ("C", "C++"):
        return _guide_cmake(repo_path, metadata)
    if dominant == "Go":
        return _guide_go(repo_path, metadata)
    if dominant == "Rust":
        return _guide_cargo(repo_path, metadata)

    return _guide_generic(repo_path, metadata)


# ---------------------------------------------------------------------------
# Build system guides (all in Chinese)
# ---------------------------------------------------------------------------

def _guide_cmake(repo_path: str, metadata: dict) -> str:
    return """\
# 重新构建指南 (CMake)

## 前置条件

确保系统已安装以下工具：

```bash
# macOS
brew install cmake make gcc

# Ubuntu / Debian
sudo apt-get install cmake build-essential

# CentOS / RHEL
sudo yum install cmake gcc gcc-c++ make
```

## 构建步骤

```bash
# 1. 进入项目根目录
cd {repo_path}

# 2. 创建构建目录（推荐 out-of-source 构建）
mkdir -p build && cd build

# 3. 运行 CMake 配置
cmake .. -DCMAKE_BUILD_TYPE=Release

# 4. 编译（使用所有可用核心）
cmake --build . --parallel $(nproc)

# 5. 安装（可选）
cmake --install . --prefix /usr/local
```

## 常见选项

```bash
# 指定编译器
cmake .. -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++

# 启用调试构建
cmake .. -DCMAKE_BUILD_TYPE=Debug

# 指定安装前缀
cmake .. -DCMAKE_INSTALL_PREFIX=/opt/myproject

# 传递自定义选项
cmake .. -DENABLE_TESTS=ON -DENABLE_DOCS=OFF
```

## 故障排除

- **找不到依赖库**: 检查 `CMakeLists.txt` 中的 `find_package()` 调用，确保依赖已安装。
- **编译器版本不兼容**: 查看 `CMakeLists.txt` 中的 `CMAKE_CXX_STANDARD` 要求。
- **子模块缺失**: 运行 `git submodule update --init --recursive`。
""".format(repo_path=repo_path)


def _guide_make(repo_path: str, metadata: dict) -> str:
    return """\
# 重新构建指南 (Make)

## 前置条件

```bash
# macOS
brew install make gcc

# Ubuntu / Debian
sudo apt-get install build-essential

# CentOS / RHEL
sudo yum install gcc make
```

## 构建步骤

```bash
# 1. 进入项目根目录
cd {repo_path}

# 2. 查看可用目标
make help 2>/dev/null || head -50 Makefile

# 3. 执行默认构建
make

# 4. 并行编译
make -j$(nproc)

# 5. 安装（如支持）
make install PREFIX=/usr/local
```

## 常见目标

```bash
make clean      # 清理构建产物
make test       # 运行测试
make install    # 安装
make uninstall  # 卸载
make dist       # 生成发布包
```

## 故障排除

- **缺少头文件**: 安装对应的 `-dev` 或 `-devel` 包。
- **权限不足**: 使用 `sudo make install` 或修改 `PREFIX` 到用户目录。
""".format(repo_path=repo_path)


def _guide_gradle(repo_path: str, metadata: dict) -> str:
    return """\
# 重新构建指南 (Gradle)

## 前置条件

```bash
# 确保安装 JDK 11 或更高版本
java -version

# macOS
brew install openjdk@17

# Ubuntu / Debian
sudo apt-get install openjdk-17-jdk
```

## 构建步骤

```bash
# 1. 进入项目根目录
cd {repo_path}

# 2. 使用 Gradle Wrapper（推荐）
./gradlew build

# 3. 跳过测试构建
./gradlew build -x test

# 4. 清理后重新构建
./gradlew clean build

# 5. 查看所有可用任务
./gradlew tasks
```

## 常见任务

```bash
./gradlew compileJava     # 编译 Java 源码
./gradlew compileScala    # 编译 Scala 源码
./gradlew test            # 运行测试
./gradlew jar             # 打包 JAR
./gradlew shadowJar       # 打包 Fat JAR（需 Shadow 插件）
./gradlew publishToMavenLocal  # 发布到本地 Maven 仓库
./gradlew dependencies    # 查看依赖树
```

## 故障排除

- **Gradle Wrapper 权限**: 运行 `chmod +x gradlew`。
- **下载依赖超时**: 检查网络连接，或在 `~/.gradle/gradle.properties` 中配置镜像。
- **JDK 版本不匹配**: 在 `build.gradle` 或 `gradle.properties` 中确认 `sourceCompatibility`。
""".format(repo_path=repo_path)


def _guide_maven(repo_path: str, metadata: dict) -> str:
    return """\
# 重新构建指南 (Maven)

## 前置条件

```bash
# 确保安装 JDK 11 或更高版本
java -version

# macOS
brew install maven openjdk@17

# Ubuntu / Debian
sudo apt-get install maven openjdk-17-jdk
```

## 构建步骤

```bash
# 1. 进入项目根目录
cd {repo_path}

# 2. 完整构建（编译 + 测试 + 打包）
mvn clean package

# 3. 跳过测试
mvn clean package -DskipTests

# 4. 仅编译
mvn compile

# 5. 安装到本地仓库
mvn clean install
```

## 常见命令

```bash
mvn test                  # 运行测试
mvn dependency:tree       # 查看依赖树
mvn dependency:resolve    # 下载所有依赖
mvn versions:display-dependency-updates  # 检查依赖更新
mvn site                  # 生成项目站点
```

## 故障排除

- **下载依赖失败**: 检查 `~/.m2/settings.xml` 中的镜像配置。
- **内存不足**: 设置 `export MAVEN_OPTS="-Xmx2g"`。
- **插件版本冲突**: 运行 `mvn dependency:tree -Dverbose` 查看冲突。
""".format(repo_path=repo_path)


def _guide_cargo(repo_path: str, metadata: dict) -> str:
    return """\
# 重新构建指南 (Cargo / Rust)

## 前置条件

```bash
# 安装 Rust 工具链
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
```

## 构建步骤

```bash
# 1. 进入项目根目录
cd {repo_path}

# 2. 构建项目
cargo build

# 3. Release 构建（优化）
cargo build --release

# 4. 运行测试
cargo test

# 5. 运行项目
cargo run
```

## 常见命令

```bash
cargo check           # 快速语法检查（不生成二进制）
cargo clippy          # 代码质量检查
cargo fmt             # 格式化代码
cargo doc --open      # 生成并打开文档
cargo update          # 更新依赖
cargo tree            # 查看依赖树
```

## 故障排除

- **编译缓慢**: 使用 `cargo build --release` 时首次编译较慢属正常现象。
- **依赖下载失败**: 检查网络，或在 `~/.cargo/config.toml` 中配置镜像源。
- **版本不兼容**: 查看 `Cargo.toml` 中的 `edition` 和依赖版本要求。
""".format(repo_path=repo_path)


def _guide_npm(repo_path: str, metadata: dict) -> str:
    return """\
# 重新构建指南 (npm / Node.js)

## 前置条件

```bash
# 确保安装 Node.js 18+ 和 npm
node --version
npm --version

# macOS
brew install node

# Ubuntu / Debian
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install nodejs
```

## 构建步骤

```bash
# 1. 进入项目根目录
cd {repo_path}

# 2. 安装依赖
npm install

# 3. 构建项目
npm run build

# 4. 运行测试
npm test

# 5. 启动开发服务器（如适用）
npm run dev
```

## 常见命令

```bash
npm ci                  # 清洁安装（使用 lock 文件）
npm run lint            # 代码检查
npm audit               # 安全审计
npm outdated            # 检查过时依赖
npm run start           # 启动生产服务
```

## 故障排除

- **node_modules 损坏**: 删除 `node_modules` 和 `package-lock.json`，重新 `npm install`。
- **Node 版本不匹配**: 使用 `nvm` 管理 Node.js 版本。
- **构建脚本缺失**: 查看 `package.json` 中的 `scripts` 字段确认可用命令。
""".format(repo_path=repo_path)


def _guide_go(repo_path: str, metadata: dict) -> str:
    return """\
# 重新构建指南 (Go)

## 前置条件

```bash
# 确保安装 Go 1.21 或更高版本
go version

# macOS
brew install go

# Ubuntu / Debian
sudo apt-get install golang-go
```

## 构建步骤

```bash
# 1. 进入项目根目录
cd {repo_path}

# 2. 下载依赖
go mod download

# 3. 构建项目
go build ./...

# 4. 运行测试
go test ./...

# 5. 安装可执行文件
go install ./cmd/...
```

## 常见命令

```bash
go vet ./...            # 静态分析
go mod tidy             # 清理无用依赖
go mod graph            # 查看依赖图
go generate ./...       # 运行代码生成
go build -o myapp .     # 指定输出文件名
```

## 故障排除

- **模块下载失败**: 设置 `GOPROXY=https://goproxy.cn,direct`（国内镜像）。
- **版本不兼容**: 检查 `go.mod` 中的 `go` 指令版本。
- **CGO 依赖**: 确保安装了 C 编译器（`gcc` 或 `clang`）。
""".format(repo_path=repo_path)


def _guide_python(repo_path: str, metadata: dict) -> str:
    return """\
# 重新构建指南 (Python)

## 前置条件

```bash
# 确保安装 Python 3.10+
python3 --version

# 推荐使用虚拟环境
python3 -m venv .venv
source .venv/bin/activate  # Linux / macOS
# .venv\\Scripts\\activate   # Windows
```

## 构建步骤

```bash
# 1. 进入项目根目录
cd {repo_path}

# 2. 安装依赖（选择适用的方式）
pip install -r requirements.txt
# 或者
pip install -e ".[dev]"
# 或者
pip install -e .

# 3. 运行测试
pytest

# 4. 代码检查
flake8 .  # 或 ruff check .
mypy .    # 类型检查（如适用）
```

## 常见操作

```bash
pip install -e .          # 以开发模式安装
pip freeze > requirements.txt  # 导出当前依赖
python -m build           # 构建发布包（需 build 包）
twine upload dist/*       # 上传到 PyPI（需 twine 包）
```

## 故障排除

- **依赖冲突**: 使用 `pip check` 检查兼容性，或尝试 `pip-compile`。
- **C 扩展编译失败**: 确保安装了 Python 开发头文件（`python3-dev`）。
- **虚拟环境问题**: 删除 `.venv` 重新创建。
""".format(repo_path=repo_path)


def _guide_generic(repo_path: str, metadata: dict) -> str:
    build_systems = metadata.get("build_systems", [])
    languages = metadata.get("language_distribution", {})
    lang_str = ", ".join(f"{k}: {v} 文件" for k, v in list(languages.items())[:5])

    return f"""\
# 重新构建指南

## 项目信息

- **路径**: `{repo_path}`
- **构建系统**: {', '.join(build_systems) if build_systems else '未检测到'}
- **语言分布**: {lang_str if lang_str else '未知'}

## 通用构建步骤

### 1. 检查项目文档

首先查看项目中的构建说明：

```bash
# 检查是否存在以下文件
cat README.md
cat INSTALL.md
cat BUILD.md
cat CONTRIBUTING.md
```

### 2. 检查依赖管理

```bash
# 查看项目根目录的配置文件
ls -la

# 常见依赖文件:
# - requirements.txt / pyproject.toml (Python)
# - package.json (Node.js)
# - pom.xml / build.gradle (Java)
# - Cargo.toml (Rust)
# - go.mod (Go)
# - CMakeLists.txt / Makefile (C/C++)
```

### 3. 安装依赖并构建

根据检测到的构建系统或语言选择对应命令。请参考上述具体指南。

## 故障排除

- 仔细阅读项目 README 中的构建说明。
- 检查 CI/CD 配置文件（`.github/workflows/`、`.gitlab-ci.yml`、`Jenkinsfile`）
  了解自动化构建流程。
- 查看 `Dockerfile` 或 `docker-compose.yml` 了解容器化构建方式。
"""
