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

### 1. 启动 Python 后端
```bash
cd backend
pip install -r requirements.txt
python main.py --port 8765
```

### 2. 启动前端开发服务器
```bash
npm install
npm run dev
```

### 3. 启动 Tauri 开发模式
```bash
npm run tauri dev
```

## 构建 EXE

### 1. 安装 Python 依赖到本地目录
```bash
cd backend
pip install -r requirements.txt -t ../src-tauri/python-runtime/Lib/site-packages
```

### 2. 下载嵌入式 Python
从 https://github.com/astral-sh/python-build-standalone 下载 Windows 版本，
解压到 `src-tauri/python-runtime/`

### 3. 构建 Tauri 应用
```bash
npm run tauri build
```

### 4. 输出位置
```
src-tauri/target/release/bundle/
├── msi/OmniCouncil_0.1.0_x64.msi    # MSI 安装包
└── exe/OmniCouncil.exe                # 可执行文件
```

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
│   └── engine/          # 核心引擎（待迁移）
└── dist/                # 前端构建输出
```

## 配置文件位置
```
~/.omnicouncil/
├── config.yaml          # 全局配置
├── auth/                # 登录态
│   ├── deepseek.json
│   └── qianwen.json
├── sessions/            # 历史会话
└── logs/                # 日志
```
