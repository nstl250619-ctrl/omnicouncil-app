# OmniCouncil — 多AI共识决策桌面应用

> 让多个AI共同思考，而不是让用户重复劳动。

OmniCouncil 是一个能够让多个AI并行思考、交叉验证、自动提炼共识、分析冲突、形成决策结果的**桌面应用**。

## 架构

```
┌─────────────────────────────────────────────┐
│                OmniCouncil.exe               │
│                                              │
│  ┌──────────────────────┐                    │
│  │    Tauri 壳 (Rust)    │  窗口管理          │
│  └──────────┬───────────┘                    │
│             │                                │
│  ┌──────────▼───────────────────────────┐    │
│  │   Python 后端 (FastAPI + WebSocket)   │    │
│  │   ┌───────┐ ┌───────┐ ┌───────┐     │    │
│  │   │ 第1层 │→│ 第2层 │→│ 第3层 │     │    │
│  │   │AI接入 │ │ 调度  │ │ 收集  │     │    │
│  │   └───────┘ └───────┘ └───┬───┘     │    │
│  │                     ┌───────┐        │    │
│  │                     │ 第4层 │        │    │
│  │                     │ 对比  │        │    │
│  │                     └───────┘        │    │
│  │   ┌───────────────────────────┐      │    │
│  │   │  BrowserEngine            │      │    │
│  │   │  CDP / 内嵌 Chromium      │      │    │
│  │   └───────────────────────────┘      │    │
│  └──────────────────────────────────────┘    │
│                                              │
│  ┌──────────────────────────────────────┐    │
│  │  前端 (React + TypeScript + Zustand)  │    │
│  │  WebSocket 实时通信                   │    │
│  └──────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

## 技术栈

| 层 | 技术 |
|---|---|
| 桌面壳 | Tauri (Rust) |
| 后端 | Python 3.12 + FastAPI + WebSocket |
| 浏览器引擎 | Playwright (CDP / 内嵌 Chromium) |
| 前端 | React + TypeScript + Zustand |
| 测试 | pytest + Vitest |

## 快速开始（开发模式）

### 前置条件
- Node.js 18+
- Python 3.11+
- Rust（仅构建 Tauri 时需要）

### 启动后端
```bash
cd backend
pip install -r requirements.txt
python main.py --port 8765
```

### 启动前端
```bash
npm install
npm run dev
```

### 启动 Tauri（需要 Rust）
```bash
npm run tauri dev
```

## 构建 EXE

详见 [BUILD.md](BUILD.md)

```powershell
# Windows PowerShell
.\scripts\build-windows.ps1
```

## 测试

```bash
# 后端测试
cd backend && python -m pytest tests/ -v

# E2E 测试（需要后端运行）
python scripts/test-e2e.py --port 8765
```

## 项目结构

```
omnicouncil-app/
├── src-tauri/              # Tauri 壳 (Rust)
│   └── src/
│       ├── main.rs         # 窗口管理、进程管理
│       └── python_manager.rs
├── src/                    # 前端 (React)
│   ├── components/         # UI 组件
│   ├── stores/             # Zustand 状态管理
│   ├── hooks/              # WebSocket hook
│   └── styles/             # CSS 样式
├── backend/                # Python 后端
│   ├── main.py             # FastAPI + WebSocket
│   ├── engine/             # 核心引擎 (第1-4层)
│   ├── browser/            # 浏览器引擎抽象
│   ├── shared/             # 共享类型/配置
│   └── tests/              # 测试
├── scripts/                # 构建/测试脚本
└── BUILD.md                # 构建说明
```

## 功能状态

| 功能 | 状态 |
|------|------|
| AI 接入层 | ✅ DeepSeek + 千问 |
| 调度中心 | ✅ 并行/序贯分发 |
| 结果收集 | ✅ 自动收集 + 标准化 |
| 对比分析 | ✅ 相似度/差异/独观点 |
| 共识分析 | ⏳ P1 |
| 冲突分析 | ⏳ P1 |
| 首次启动向导 | ✅ CDP/内嵌模式选择 |
| 设置页面 | ✅ AI管理/引擎配置 |
| EXE 打包 | ✅ Tauri + Python sidecar |

## 设计文档

详见项目设计文档目录：
- 01_Council OS项目蓝图
- 02_AI接入层设计
- 03_调度中心 + 结果收集中心
- 04_对比分析中心
- 05_共识引擎
- 06_冲突分析引擎
- 07_AI互审引擎
