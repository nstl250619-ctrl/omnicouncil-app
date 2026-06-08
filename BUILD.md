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

## 引擎包安装

v2.0.0 起，后端依赖 5 个独立引擎包，必须先安装：

```bash
cd backend
pip install -r requirements.txt
# 安装引擎包 (core 必须先装)
pip install -e packages/omnicounci1l-core
for d in packages/*/; do
  [ "$(basename $d)" = "omnicounci1l-core" ] && continue
  pip install -e "$d"
done
```

验证安装：
```bash
python -c "
from omnicounci1l_core.types import QueryRequest
from omnicounci1l_comparison import ComparisonEngine
from omnicounci1l_consensus import ConsensusEngine
from omnicounci1l_conflict import ConflictEngine
print('All engine packages: OK')
"
```

## 开发模式

### WSL2（Linux）— 前后端开发
在 WSL2 中运行后端 + 前端开发服务器，浏览器访问：

```bash
# 终端 1：后端
cd backend
pip install -r requirements.txt
pip install -e packages/omnicounci1l-core
for d in packages/*/; do
  [ "$(basename $d)" = "omnicounci1l-core" ] && continue
  pip install -e "$d"
done
python main.py --port 8765

# 终端 2：前端 (热更新)
npm install
npm run dev          # → http://localhost:5173

# 终端 3 (可选)：前端生产构建预览
npm run build
npx serve dist       # → http://localhost:3000
```

### Windows — Tauri 桌面开发/构建
Tauri 构建（EXE）**必须**在 Windows 原生环境执行，WSL2 无法构建 Windows 桌面应用。

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

# 6. 安装 Python 后端依赖 + 引擎包
cd backend
pip install -r requirements.txt
pip install -e packages/omnicounci1l-core
for %d in (packages/*/) do (
  if not "%d"=="omnicounci1l-core\" pip install -e packages/%d
)
cd ..

# 7. 构建 Tauri 应用（编译 Rust + 打包前端 + PyInstaller 打包后端）
npm run tauri build
```

> **注意**：第一次运行 `npm run tauri build` 会下载 Rust crate 依赖，可能需要 5-15 分钟。
> PyInstaller 打包时会自动安装引擎包（参见 `scripts/build-backend.py`）。

#### 第 3 步：找到构建产物

```
src-tauri/target/release/bundle/
├── msi/OmniCouncil_2.0.0_x64.msi     # MSI 安装程序
└── nsis/OmniCouncil_2.0.0_x64.exe    # NSIS 安装程序（推荐，~17MB）
```

### 方法 B：GitHub Actions 自动构建

在 GitHub 仓库页面：

1. 点击 **Actions** 标签
2. 选择 **Release (Windows Build)** workflow
3. 点击 **Run workflow**
4. 输入版本号（如 `2.0.0`）
5. 等待 10-20 分钟
6. 构建完成后在 Workflow 页面下载 Artifact：
   - `OmniCouncil-2.0.0-x64-installer.zip` (~17MB, NSIS 安装程序)
   - `OmniCouncil-2.0.0-portable.zip` (~4MB, 免安装便携版)

> 这是最简单的方法，无需在本地安装任何工具。

## PyInstaller 独立打包（仅后端）

如果需要单独打包后端（不通过 Tauri）：

```bash
cd backend
pip install -r requirements.txt pyinstaller
pip install -e packages/omnicounci1l-core
for d in packages/*/; do
  [ "$(basename $d)" = "omnicounci1l-core" ] && continue
  pip install -e "$d"
done
python ../scripts/build-backend.py
```

产物在 `src-tauri/resources/backend/` 下。

## CI/CD 自动构建

项目配置了两个 GitHub Actions 工作流：

| 工作流 | 触发 | 内容 |
|--------|------|------|
| `ci.yml` | push/PR → main | 后端 pytest (666 项) + 前端 Vite 构建 + 引擎包验证 + 10min 浸泡测试 |
| `release.yml` | 手动 | Windows EXE 构建 (Tauri + PyInstaller) + Pre-release 测试 |

### 手动触发 Release 构建

```bash
gh workflow run "Release (Windows Build)" --repo nstl250619-ctrl/omnicouncil-app --ref main -f version=2.0.0
```

## 配置文件位置

```
~/.omnicouncil/
├── config.json          # 全局配置
├── auth/                # AI 登录 Profile + Cookies
│   ├── deepseek_profile/
│   ├── chatgpt_profile/
│   ├── gemini_profile/
│   ├── qianwen_profile/
│   └── mimo_profile/
├── sessions/            # 历史会话
└── logs/                # 日志（自动轮转，最多 5×10MB）
```

## 常见问题

### Q: 双击 EXE 没反应？
A: 打开命令行运行 `OmniCouncil.exe` 查看错误输出。常见原因：
- 引擎包未正确打包（确认使用 v2.0.0 以上版本）
- Playwright Chromium 未安装（首次启动会自动下载）

### Q: 后端启动报 `ModuleNotFoundError: No module named 'omnicounci1l_*'`
A: 引擎包未安装。执行：
```bash
cd backend
pip install -e packages/omnicounci1l-core
for d in packages/*/; do
  [ "$(basename $d)" = "omnicounci1l-core" ] && continue
  pip install -e "$d"
done
```

### Q: 前端构建后后端 API 连不上？
A: 确认后端在 `http://127.0.0.1:8765` 运行。前端 WebSocket 和 HTTP 请求均写死此地址（开发模式）。Tauri 中通过 Python sidecar 管理。
