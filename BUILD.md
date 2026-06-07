# OmniCouncil 构建说明

## 前置条件

### Windows 环境
1. **Node.js** 18+ (https://nodejs.org)
2. **Rust** (https://rustup.rs)
3. **Python** 3.11+ (https://python.org)
4. **Visual Studio Build Tools** (C++ 桌面开发工作负载)

### 安装 Rust
```powershell
winget install Rustlang.Rustup
```

### 安装 Tauri CLI
```bash
npm install -g @tauri-apps/cli
```

## 开发模式

### WSL2（Linux）— 前后端开发
在 WSL2 中运行后端 + 前端开发服务器，浏览器访问：

```bash
# 终端 1：后端
cd backend
pip install -r requirements.txt
python main.py --port 8765

# 终端 2：前端
npm install
npm run dev          # → http://localhost:5173
```

浏览器打开 `http://localhost:5173` 即可开发调试。

### Windows — Tauri 桌面开发/构建
Tauri 构建（EXE/MSI）**必须**在 Windows 原生环境执行，WSL2 无法构建 Windows 桌面应用。

## Windows 构建 EXE（`npm run tauri build`）

### 方法 A：在 Windows 上手动构建（推荐）

#### 第 1 步：准备 Windows 环境

以 **管理员 PowerShell** 运行：

```powershell
# 1. 安装 Node.js（如果还没有）
winget install OpenJS.NodeJS.LTS

# 2. 安装 Rust
winget install Rustlang.Rustup
# 重启终端后运行：
rustup default stable

# 3. 安装 Visual Studio Build Tools
# 下载 https://visualstudio.microsoft.com/visual-cpp-build-tools/
# 安装时勾选 "使用 C++ 的桌面开发"（Desktop development with C++）
# 确保包含：MSVC v143、Windows 10/11 SDK、C++ CMake 工具
```

#### 第 2 步：获取代码并构建

```powershell
# 4. 克隆仓库
git clone https://github.com/nstl250619-ctrl/omnicouncil-app.git
cd omnicouncil-app

# 5. 安装前端依赖
npm install

# 6. 安装 Python 后端依赖
cd backend
pip install -r requirements.txt
cd ..

# 7. 构建 Tauri 应用（编译 Rust + 打包前端 + 打包安装包）
npm run tauri build
```

> **注意**：第一次运行 `npm run tauri build` 会下载 Rust crate 依赖，可能需要 5-15 分钟。

#### 第 3 步：找到构建产物

```
src-tauri/target/release/bundle/
├── msi/OmniCouncil_0.1.0_x64.msi    # MSI 安装程序
└── nsis/OmniCouncil_0.1.0_x64.exe   # NSIS 安装程序（推荐）
```

### 方法 B：GitHub Actions 自动构建

在 GitHub 仓库页面：

1. 点击 **Actions** 标签
2. 选择 **Release (Windows Build)** workflow
3. 点击 **Run workflow**
4. 输入版本号（如 `0.1.0`）
5. 等待 10-20 分钟
6. 构建完成后在 Workflow 页面下载 artifact（`OmniCouncil-0.1.0-x64`）

> 这是最简单的方法，无需在本地安装任何工具。

## 目录结构
```
omnicouncil-app/
├── src-tauri/           # Tauri Rust 代码
│   ├── src/
│   │   ├── main.rs      # 窗口管理、进程管理
│   │   └── python_manager.rs  # Python 子进程管理
│   └── Cargo.toml
├── src/                 # React 前端
│   ├── components/
│   ├── stores/
│   └── hooks/
├── backend/             # Python 后端
│   ├── main.py          # FastAPI + WebSocket
│   └── engine/          # 核心引擎
├── .github/workflows/   # GitHub Actions CI/CD
│   ├── ci.yml           # 每次推送自动测试
│   └── release.yml      # 手动触发 Windows 构建
└── dist/                # 前端构建输出
```

## 配置文件位置
```
~/.omnicouncil/
├── config.json          # 全局配置
├── sessions/            # 历史会话
└── logs/                # 日志（自动轮转，最多 5×10MB）
```
