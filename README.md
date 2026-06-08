# OmniCouncil — 多AI共识决策桌面应用

> 让多个AI共同思考，而不是让用户重复劳动。

OmniCouncil 是一个能够让多个AI并行思考、交叉验证、自动提炼共识、分析冲突、形成决策结果的**桌面应用**。它通过浏览器自动化操作 AI 网页版，无需 API Key。

## 架构

### V2 架构（Runtime Engine + Query Engine 分离）

```
┌──────────────────────────────────────────────────────────────┐
│                       OmniCouncil.exe                         │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │             Python 后端 (FastAPI + WebSocket)             │ │
│  │                                                         │ │
│  │  ┌──────────────────────────────────────────────────┐   │ │
│  │  │              Runtime Engine (左手)                │   │ │
│  │  │  确保页面就绪、登录有效、健康在线、自动恢复        │   │ │
│  │  │                                                    │   │ │
│  │  │  状态机 · Profile · Session · 心跳 · 恢复 · 注册   │   │ │
│  │  └──────────────────────────────────────────────────┘   │ │
│  │                     │ ensure_ready() → Page              │ │
│  │                     ▼                                    │ │
│  │  ┌──────────────────────────────────────────────────┐   │ │
│  │  │              Query Engine (右手)                  │   │ │
│  │  │  在就绪的 Page 上发送问题、等待回复、提取结果      │   │ │
│  │  │                                                    │   │ │
│  │  │  BaseAdapter · DeepSeek · ChatGPT · Gemini         │   │ │
│  │  │  千问 · MiMo · VisionFallback                     │   │ │
│  │  └──────────────────────────────────────────────────┘   │ │
│  │                                                         │ │
│  │  调度中心 → AI 接入 → 结果收集 → 对比分析 → 共识/冲突  │ │
│  │                                                         │ │
│  │  引擎包 (独立 pip 安装):                                │ │
│  │  omnicounci1l-core · comparison · consensus             │ │
│  │  conflict · judge                                       │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │      前端 (React + TypeScript + Zustand + Vite)          │ │
│  │  控制台 / 平台管理 / AI选择器 / 状态灯 / Toast           │ │
│  │  WebSocket 实时通信 + /api/runtime/health 轮询            │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### 核心设计原则

- **Runtime Engine（左手）**：负责"把 AI 网页变成稳定、可调用的运行时资源"
  - 10 状态生命周期状态机
  - Profile 备份/恢复
  - Session 离线+在线验证
  - 后台心跳健康监控 (60s 间隔)
  - 4 级自动恢复链（reload → renavigate → new_tab → restart_browser）

- **Query Engine（右手）**：负责"向就绪的页面发送请求并拿回结果"
  - 纯发送/等待/提取逻辑
  - 不持有浏览器引用，Page 由外部传入
  - 每个平台独立适配器 (DeepSeek, ChatGPT, Gemini, 千问, MiMo)
  - 停止按钮检测 + 内容稳定性判断

- **唯一契约**：一个已登录、可交互的 `Page` 对象

- **5 个独立引擎包**：对比、共识、冲突、评判引擎拆为独立 pip 包，可单独使用

## 技术栈

| 层 | 技术 |
|---|---|
| 桌面壳 | Tauri (Rust) |
| 后端 | Python 3.12 + FastAPI + WebSocket |
| 浏览器引擎 | Playwright (CDP / 内嵌 Chromium) |
| 前端 | React + TypeScript + Zustand + Vite |
| 引擎包 | 5 个独立 pip 包 (comparison/consensus/conflict/judge/core) |
| 测试 | pytest (666 项) + Playwright E2E |

## 快速开始（开发模式）

### 前置条件
- Node.js 18+
- Python 3.11+
- Rust（仅构建 Tauri 时需要）

### 启动后端
```bash
cd backend
pip install -r requirements.txt
# 安装引擎包
pip install -e packages/omnicounci1l-core
for d in packages/*/; do
  [ "$(basename $d)" = "omnicounci1l-core" ] && continue
  pip install -e "$d"
done
# 启动
python main.py --port 8765
```

### 启动前端（开发模式，热更新）
```bash
npm install
npm run dev
# 浏览器打开 http://localhost:5173
```

### 启动前端（独立部署，生产构建）
```bash
npm run build
npx serve dist
# 浏览器打开 http://localhost:3000
```

### 启动 Tauri（需要 Rust）
```bash
npm run tauri dev
```

## 构建 EXE

详见 [BUILD.md](BUILD.md)

## 测试

```bash
# 后端全部测试 (666 项)
cd backend && source .venv/bin/activate && python -m pytest tests/ -v

# 带覆盖率
cd backend && python -m pytest tests/ --cov=. --cov-report=html

# E2E 测试（需后端运行）
python scripts/test-e2e.py --port 8765
```

## 项目结构

```
omnicouncil-app/
├── src-tauri/              # Tauri 壳 (Rust)
│   └── src/
│       ├── main.rs         # 窗口管理、进程管理
│       └── python_manager.rs # Python 子进程管理
├── src/                    # 前端 (React + TypeScript + Vite)
│   ├── pages/
│   │   ├── ConsolePage.tsx         # 控制台主页
│   │   └── PlatformSetupPage.tsx   # AI 平台管理页
│   ├── components/         # 14 个 UI 组件
│   │   ├── AIIconSelector.tsx      # AI 图标选择器
│   │   ├── AIPlatformManager.tsx   # 首次启动向导
│   │   ├── ComparisonTab.tsx       # 对比分析标签
│   │   ├── ConflictTab.tsx         # 冲突分析标签
│   │   ├── ConsensusTab.tsx        # 共识分析标签
│   │   ├── ErrorBoundary.tsx       # 错误边界
│   │   ├── ErrorToast.tsx          # 健康/错误 Toast (支持 severity)
│   │   ├── HistoryView.tsx         # 历史记录
│   │   ├── JudgeView.tsx           # 评判建议标签
│   │   ├── QueryInput.tsx          # 查询输入框
│   │   ├── ResponsesTab.tsx        # AI 回复标签
│   │   ├── Settings.tsx            # 设置页面
│   │   ├── StatusBar.tsx           # 状态栏
│   │   ├── TabBar.tsx              # 标签栏
│   │   └── Titlebar.tsx            # 标题栏
│   ├── stores/
│   │   ├── appStore.ts     # Zustand 主状态 (AI回复/runtimeHealth/WebSocket事件)
│   │   └── configStore.ts  # 配置持久化
│   ├── hooks/
│   │   └── useWebSocket.ts # WebSocket + 健康事件回调
│   ├── styles/
│   │   └── globals.css     # CSS 变量 + 全局样式 (Google Fonts)
│   ├── App.tsx             # 路由 + Toast 管理
│   └── main.tsx            # React 入口
├── backend/                # Python 后端 (FastAPI + WebSocket)
│   ├── main.py             # 入口 (FastAPI + lifespan)
│   ├── build.spec          # PyInstaller 打包配置 (含引擎包)
│   ├── api/
│   │   ├── routes.py       # HTTP 路由 (/health, /api/runtime/health, /api/providers/*)
│   │   └── events.py       # EventBus → WebSocket 事件桥接
│   ├── ws/
│   │   └── connection.py   # WebSocket 连接管理器
│   ├── engine/
│   │   ├── contracts.py    # 接口契约 (RuntimeHealth/QueryRequest/状态枚举)
│   │   └── layers/
│   │       ├── layer1_ai_access/   # AI 接入层 (适配器管理/熔断/限流)
│   │       ├── layer2_scheduler/   # 调度中心 (并发控制/超时/重试)
│   │       └── layer3_collector/   # 结果收集/标准化
│   ├── runtime/            # Runtime Engine
│   │   ├── engine.py       # AIRuntimeEngine 主类
│   │   ├── state_machine.py # 10 状态生命周期状态机
│   │   ├── health_monitor.py # 后台心跳监控
│   │   ├── profile_manager.py # Profile 备份/恢复
│   │   ├── session_validator.py # Session 离线+在线验证
│   │   ├── recovery_engine.py # 4 级自动恢复编排
│   │   ├── recovery_strategies.py # 各级恢复策略
│   │   └── registry.py     # RuntimeRegistry
│   ├── providers/          # Query Engine
│   │   ├── base/
│   │   │   ├── provider.py       # 旧 BaseProvider (向后兼容)
│   │   │   └── query_adapter.py  # 新 BaseQueryAdapter
│   │   ├── deepseek/       # DeepSeek 适配器
│   │   ├── chatgpt/        # ChatGPT 适配器
│   │   ├── gemini/         # Gemini 适配器
│   │   ├── qianwen/        # 千问适配器
│   │   ├── mimo/           # MiMo 适配器
│   │   ├── claude/         # Claude 适配器 (v1 排除)
│   │   ├── vision_fallback.py # 截图+OCR 兜底
│   │   ├── runtime.py      # ProviderRuntime 统一生命周期
│   │   ├── registry/       # ProviderRegistry
│   │   ├── registry_v2.py  # ProviderRegistryV2
│   │   ├── event_bus.py    # 提供商事件总线
│   │   ├── health_monitor.py / session_manager.py # (已弃用)
│   │   └── errors.py       # 提供商异常定义
│   ├── packages/           # 独立引擎包 (pip install -e)
│   │   ├── omnicounci1l-core/       # 共享类型和配置 (v2.0.0)
│   │   ├── comparison-engine/       # 对比分析引擎 (v2.0.0)
│   │   ├── consensus-engine/        # 共识分析引擎 (v2.0.0)
│   │   ├── conflict-engine/         # 冲突分析引擎 (v2.0.0)
│   │   └── judge-engine/            # 评判建议引擎 (v2.0.0)
│   ├── browser/            # 浏览器引擎 (Playwright 内嵌 Chromium)
│   ├── shared/             # 共享类型/配置/日志/EventBus
│   ├── storage/            # 本地存储 (JSON/SQLite)
│   ├── config/             # YAML 配置文件
│   ├── tests/              # 666 项 pytest 测试
│   └── requirements.txt
├── scripts/
│   ├── build-backend.py    # PyInstaller 后端打包 (含引擎包)
│   ├── build-windows.ps1   # Windows 一键构建脚本
│   ├── test-e2e.py         # E2E 测试脚本
│   └── generate_report.py  # 报告生成
├── tests/e2e/              # Playwright E2E 测试
├── dist/                   # Vite 构建输出 (gitignore)
├── .github/workflows/
│   ├── ci.yml              # OmniCouncil CI (每次 push/PR)
│   └── release.yml         # Release (手动触发 Windows EXE 构建)
├── CHANGELOG.md
├── BUILD.md
├── playwright.config.ts
├── tsconfig.json
├── vite.config.ts
├── package.json
└── README.md
```

## 前端独立开发/构建/部署

前端（`src/` 目录）可独立于 Tauri 壳开发和部署，仅需后端 API 服务。

### 独立开发（热更新）
```bash
npm install
npm run dev            # → http://localhost:5173
# 后端需在 http://127.0.0.1:8765 运行
```

### 独立构建
```bash
npm run build
# 输出到 dist/: index.html + assets/*.js + assets/*.css
# 产出: ~378KB JS (gzip: ~117KB), ~29KB CSS (gzip: ~5.5KB)
```

### 独立部署（静态服务器）
```bash
npx serve dist         # → http://localhost:3000
# 或使用任何静态服务器
python3 -m http.server 8080 -d dist
```

### 前端-后端 API 接口

前端通过以下 HTTP + WebSocket 接口与后端通信：

| 接口 | 方法 | 说明 |
|------|------|------|
| `ws://127.0.0.1:8765/ws` | WebSocket | 任务提交、状态推送、流式回复、健康事件 |
| `/api/runtime/health` | GET | 所有 AI 的 RuntimeHealth（含状态灯） |
| `/api/providers/{name}/reauth` | POST | 手动触发重认证/恢复 |
| `/api/providers/{name}` | DELETE | 删除平台 |
| `/api/providers` | POST | 添加新平台 (stub) |
| `/health` | GET | 后端基础健康检查 |
| `/health/detailed` | GET | 单 AI 详细健康状态 |
| `/api/sessions/status` | GET | 所有 AI 登录会话状态 |

**WebSocket 事件**（前端自动监听）：

| 事件 | 触发时机 | UI 效果 |
|------|----------|---------|
| `session_expired` | AI 登录过期 | 🟡 黄色 toast + 状态灯变红 |
| `recovery_success` | 自动恢复成功 | 🟢 绿色 toast + 状态灯变绿 |
| `ai_unavailable` | AI 不可用 | 🔴 红色 toast + 状态灯变红 |

### 状态灯颜色说明

| 状态 | 颜色 | 含义 |
|------|------|------|
| `healthy` | 🟢 绿色 | 正常运行 |
| `degraded` | 🟡 黄色 | 部分异常（可点击恢复） |
| `login_required` | 🔴 红色 | 需要重新登录（可点击恢复） |
| `unavailable` | 🔴 红色 | 不可用 |

## 功能状态

| 功能 | 状态 |
|------|------|
| **Runtime Engine** | |
| 10 状态生命周期状态机 | ✅ |
| Profile 备份/恢复/健康检查 | ✅ |
| Session 离线+在线验证 | ✅ |
| 后台心跳健康监控 (60s) | ✅ |
| 4 级自动恢复链 | ✅ |
| RuntimeRegistry 平台注册 | ✅ |
| **Query Engine** | |
| BaseQueryAdapter 统一接口 | ✅ |
| DeepSeek / ChatGPT / Gemini / 千问 / MiMo 适配器 | ✅ |
| 停止按钮检测 + 内容稳定性判断 | ✅ |
| VisionFallback 截图+OCR 兜底 | ✅ |
| **业务引擎** | |
| AI 接入层 (AIAccessManager) | ✅ 含熔断器 + 限流器 |
| 调度中心 | ✅ 并行分发 + 超时 + 重试 |
| 结果收集 | ✅ 自动收集 + 标准化 |
| 对比分析 | ✅ 6 阶段语义分析流水线 |
| 共识分析 | ✅ 共识点挖掘 + 分歧分析 + 置信度评分 |
| 冲突分析 | ✅ 冲突检测 + 根因分析 |
| 评判建议 | ✅ 独立评判引擎 (可接入外部 AI) |
| **前端** | |
| 状态路由 (platform-setup / console) | ✅ |
| AI 平台管理页 (CRUD + 搜索 + 状态灯) | ✅ |
| 控制台 (AI 选择 + 多标签 + 实时回复) | ✅ |
| 健康状态灯 (30s 轮询) | ✅ |
| 错误 Toast (error/warning/success) | ✅ |
| WebSocket 健康事件 | ✅ |
| **桌面/部署** | |
| Tauri 壳 (Rust) | ✅ |
| PyInstaller 后端打包 | ✅ (含引擎包) |
| GitHub Actions CI | ✅ (OmniCouncil CI: success) |
| GitHub Actions Release | ✅ (手动触发 EXE 构建) |
| **测试** | |
| pytest 单元测试 | ✅ 666 项全部通过 |
| 测试覆盖率 | ⏳ CI 中配置 |
| E2E 测试 | ⏳ Playwright 配置齐全 |

## CI/CD

项目使用 GitHub Actions 自动化：

| 工作流 | 触发 | 内容 |
|--------|------|------|
| **OmniCouncil CI** | `push`/`PR` → `main` | 后端测试 + 前端构建 + 引擎包验证 + 心跳浸泡测试 |
| **Release (Windows Build)** | 手动 (`workflow_dispatch`) | Windows EXE 构建 (测试 + Tauri + PyInstaller) |

当前 CI 状态: ✅ `OmniCouncil CI` — 通过

## 设计文档

详见项目设计文档目录：
- 01_Council OS 项目蓝图
- 02_AI 接入层设计
- 03_调度中心 + 结果收集中心
- 04_对比分析中心
- 05_共识引擎
- 06_冲突分析引擎
- 07_AI 互审引擎
