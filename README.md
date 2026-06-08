# OmniCouncil — 多AI共识决策桌面应用

> 让多个AI共同思考，而不是让用户重复劳动。

OmniCouncil 是一个能够让多个AI并行思考、交叉验证、自动提炼共识、分析冲突、形成决策结果的**桌面应用**。

## 架构

### V2 架构（Runtime Engine + Query Engine 分离）

```
┌─────────────────────────────────────────────────────────────┐
│                        OmniCouncil.exe                       │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              Python 后端 (FastAPI + WebSocket)          │  │
│  │                                                        │  │
│  │  ┌─────────────────────────────────────────────────┐   │  │
│  │  │              Runtime Engine (左手)               │   │  │
│  │  │  确保页面就绪、登录有效、健康在线、自动恢复       │   │  │
│  │  │                                                 │   │  │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐       │   │  │
│  │  │  │ 状态机   │ │ Profile  │ │ Session  │       │   │  │
│  │  │  │ 10状态   │ │ Manager  │ │ Validator│       │   │  │
│  │  │  └──────────┘ └──────────┘ └──────────┘       │   │  │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐       │   │  │
│  │  │  │ Health   │ │ Recovery │ │ Registry │       │   │  │
│  │  │  │ Monitor  │ │ Engine   │ │          │       │   │  │
│  │  │  └──────────┘ └──────────┘ └──────────┘       │   │  │
│  │  └─────────────────────────────────────────────────┘   │  │
│  │                          │ ensure_ready() → Page        │  │
│  │                          ▼                              │  │
│  │  ┌─────────────────────────────────────────────────┐   │  │
│  │  │              Query Engine (右手)                 │   │  │
│  │  │  在就绪的 Page 上发送问题、等待回复、提取结果     │   │  │
│  │  │                                                 │   │  │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐       │   │  │
│  │  │  │ Base     │ │ DeepSeek │ │ ChatGPT  │ ...   │   │  │
│  │  │  │ Adapter  │ │ Adapter  │ │ Adapter  │       │   │  │
│  │  │  └──────────┘ └──────────┘ └──────────┘       │   │  │
│  │  └─────────────────────────────────────────────────┘   │  │
│  │                                                        │  │
│  │  ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐   │  │
│  │  │ 调度  │→│ AI    │→│ 收集  │→│ 对比  │→│ 共识  │   │  │
│  │  │ 中心  │ │ 接入  │ │ 中心  │ │ 分析  │ │ 引擎  │   │  │
│  │  └───────┘ └───────┘ └───────┘ └───────┘ └───────┘   │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │           前端 (React + TypeScript + Zustand)           │  │
│  │           WebSocket 实时通信                            │  │
│  └────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 核心设计原则

- **Runtime Engine（左手）**：负责"把 AI 网页变成稳定、可调用的运行时资源"
  - 10 状态生命周期状态机
  - Profile 备份/恢复
  - Session 离线+在线验证
  - 后台心跳健康监控
  - 4 级自动恢复链（reload → renavigate → new_tab → restart_browser）

- **Query Engine（右手）**：负责"向就绪的页面发送请求并拿回结果"
  - 纯发送/等待/提取逻辑
  - 不持有浏览器引用，Page 由外部传入
  - 每个平台独立适配器
  - 停止按钮检测 + 内容稳定性判断

- **唯一契约**：一个已登录、可交互的 `Page` 对象

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

```powershell
# Windows PowerShell
.\scripts\build-windows.ps1
```

## 测试

```bash
# 后端测试 (345 新测试 + 既有测试)
cd backend && python -m pytest tests/test_state_machine.py tests/test_profile_manager.py tests/test_session_validator.py tests/test_health_monitor.py tests/test_recovery_engine.py tests/test_runtime_engine.py tests/test_query_adapter.py tests/test_query_adapter_coverage.py tests/test_integration_v2.py tests/test_contracts.py tests/test_stress.py -v

# 带覆盖率
cd backend && python -m pytest tests/ --cov=runtime --cov=engine.contracts --cov-report=html

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
├── src/                    # 前端 (React + TypeScript + Vite)
│   ├── pages/
│   │   ├── ConsolePage.tsx         # 控制台主页
│   │   └── PlatformSetupPage.tsx   # AI 平台管理页
│   ├── components/
│   │   ├── AIIconSelector.tsx      # AI 图标选择器
│   │   ├── AIPlatformManager.tsx   # 首次启动向导 (旧)
│   │   ├── ComparisonTab.tsx       # 对比分析标签
│   │   ├── ConflictTab.tsx         # 冲突分析标签
│   │   ├── ConsensusTab.tsx        # 共识分析标签
│   │   ├── ErrorBoundary.tsx       # 错误边界
│   │   ├── ErrorToast.tsx          # 错误/健康 Toast
│   │   ├── HistoryView.tsx         # 历史记录
│   │   ├── JudgeView.tsx           # 评判建议标签
│   │   ├── QueryInput.tsx          # 查询输入框
│   │   ├── ResponsesTab.tsx        # AI 回复标签
│   │   ├── Settings.tsx            # 设置页面
│   │   ├── StatusBar.tsx           # 状态栏
│   │   ├── TabBar.tsx              # 标签栏
│   │   └── Titlebar.tsx            # 标题栏
│   ├── stores/
│   │   ├── appStore.ts             # Zustand 主状态 (AI 回复/runtimeHealth)
│   │   └── configStore.ts          # 配置持久化
│   ├── hooks/
│   │   └── useWebSocket.ts         # WebSocket + 健康事件
│   ├── styles/
│   │   └── globals.css             # CSS 变量 + 全局样式
│   ├── App.tsx                     # 路由 + Toast
│   └── main.tsx                    # React 入口
├── backend/                # Python 后端 (FastAPI + WebSocket)
│   ├── main.py             # 入口 (FastAPI + lifespan)
│   ├── main_v2.py          # 旧入口 (向后兼容)
│   ├── build.spec          # PyInstaller 打包配置
│   ├── api/
│   │   ├── routes.py       # HTTP 路由
│   │   └── events.py       # EventBus → WebSocket 事件桥接
│   ├── ws/
│   │   └── connection.py   # WebSocket 连接管理器
│   ├── engine/
│   │   ├── contracts.py    # 接口契约 (RuntimeHealth/状态枚举)
│   │   └── layers/
│   │       ├── layer1_ai_access/   # AI 接入层
│   │       ├── layer2_scheduler/   # 调度中心
│   │       └── layer3_collector/   # 结果收集
│   ├── runtime/            # Runtime Engine
│   │   ├── engine.py       # AIRuntimeEngine 主类
│   │   ├── state_machine.py # 10 状态生命周期
│   │   ├── health_monitor.py # 后台心跳
│   │   ├── profile_manager.py # Profile 备份/恢复
│   │   ├── session_validator.py # Session 验证
│   │   ├── recovery_engine.py # 自动恢复编排
│   │   ├── recovery_strategies.py # 4 级恢复策略
│   │   └── registry.py     # RuntimeRegistry
│   ├── providers/          # Query Engine
│   │   ├── base/
│   │   │   ├── provider.py # 旧 BaseProvider
│   │   │   └── query_adapter.py # 新 BaseQueryAdapter
│   │   ├── deepseek/chatgpt/gemini/qianwen/mimo/claude/ # 适配器
│   │   ├── vision_fallback.py # 截图+OCR 兜底
│   │   ├── runtime.py      # ProviderRuntime
│   │   ├── registry/registry_v2.py # 提供商注册表
│   │   ├── event_bus.py    # 事件总线
│   │   └── health_monitor.py / session_manager.py # (已弃用)
│   ├── packages/           # 独立引擎包 (pip install -e)
│   │   ├── omnicounci1l-core/       # 共享类型 (v2.0.0)
│   │   ├── comparison-engine/       # 对比分析 (v2.0.0)
│   │   ├── consensus-engine/        # 共识分析 (v2.0.0)
│   │   ├── conflict-engine/         # 冲突分析 (v2.0.0)
│   │   └── judge-engine/            # 评判建议 (v2.0.0)
│   ├── browser/            # 浏览器引擎 (Playwright)
│   ├── shared/             # 共享类型/配置/日志
│   ├── storage/            # 本地存储
│   ├── config/             # 配置文件
│   ├── tests/              # 659 项 pytest 测试
│   └── requirements.txt
├── scripts/
│   ├── build-backend.py    # PyInstaller 打包
│   └── test-e2e.py
├── tests/                  # Playwright E2E
├── dist/                   # Vite 构建输出
├── .github/workflows/
│   ├── ci.yml              # OmniCouncil CI
│   └── release.yml         # Windows EXE 构建
├── CHANGELOG.md
├── BUILD.md
└── README.md
```

## 功能状态

| 功能 | 状态 |
|------|------|
| **Runtime Engine** |
| 10 状态生命周期状态机 | ✅ |
| Profile 备份/恢复/健康检查 | ✅ |
| Session 离线+在线验证 | ✅ |
| 后台心跳健康监控 | ✅ |
| 4 级自动恢复链 | ✅ |
| RuntimeRegistry 平台注册 | ✅ |
| **Query Engine** |
| BaseQueryAdapter 统一接口 | ✅ |
| DeepSeek / ChatGPT / Gemini / 千问 / MiMo 适配器 | ✅ |
| 停止按钮检测 + 内容稳定性判断 | ✅ |
| VisionFallback 截图+OCR 兜底 | ✅ |
| **业务引擎** |
| AI 接入层 | ✅ DeepSeek + 千问 + Gemini + ChatGPT + MiMo |
| 调度中心 | ✅ 并行/序贯分发 |
| 结果收集 | ✅ 自动收集 + 标准化 |
| 对比分析 | ✅ 相似度/差异/独观点 |
| 共识分析 | ⏳ P1 |
| 冲突分析 | ⏳ P1 |
| **前端/桌面** |
| 首次启动向导 | ✅ CDP/内嵌模式选择 |
| 设置页面 | ✅ AI管理/引擎配置 |
| EXE 打包 | ✅ Tauri + Python sidecar |
| **测试** |
| 单元测试 | ✅ 345 用例全部通过 |
| 核心模块覆盖率 | ✅ 88% |
| 压力测试 | ✅ 心跳/恢复/并发 |

## 前端独立开发/构建/部署

前端（`src/` 目录）可独立于 Tauri 壳开发和部署，仅需后端 API 服务。

### 独立开发（热更新）
```bash
cd omnicouncil-app
npm install
npm run dev
# 浏览器打开 http://localhost:5173
# 后端需在 http://127.0.0.1:8765 运行
```

### 独立构建
```bash
npm run build
# 输出到 dist/
# dist/index.html + dist/assets/*.js + dist/assets/*.css
```

### 独立部署（静态服务器）
```bash
# 使用 serve
npx serve dist

# 或使用任何静态服务器
python3 -m http.server 8080 -d dist
```

### 前端-后端 API 接口

前端通过以下 HTTP + WebSocket 接口与后端通信：

| 接口 | 方法 | 说明 |
|------|------|------|
| `ws://127.0.0.1:8765/ws` | WebSocket | 任务提交、状态推送、流式回复 |
| `/api/runtime/health` | GET | 所有 AI 的 RuntimeHealth（含状态灯） |
| `/api/providers/{name}/reauth` | POST | 手动触发重认证/恢复 |
| `/api/providers/{name}` | DELETE | 删除平台 |
| `/api/providers` | POST | 添加新平台（stub） |
| `/health` | GET | 后端基础健康检查 |

**WebSocket 事件**（前端自动监听）：

| 事件 | 触发时机 | UI 效果 |
|------|----------|---------|
| `session_expired` | AI 登录过期 | 黄色 toast + 状态灯变红 |
| `recovery_success` | 自动恢复成功 | 绿色 toast + 状态灯变绿 |
| `ai_unavailable` | AI 不可用 | 红色 toast + 状态灯变红 |

### 状态灯颜色说明

| 状态 | 颜色 | 含义 |
|------|------|------|
| `healthy` | 🟢 绿色 | 正常运行 |
| `degraded` | 🟡 黄色 | 部分异常（可恢复） |
| `login_required` | 🔴 红色 | 需要重新登录 |
| `unavailable` | 🔴 红色 | 不可用 |

## 设计文档

详见项目设计文档目录：
- 01_Council OS项目蓝图
- 02_AI接入层设计
- 03_调度中心 + 结果收集中心
- 04_对比分析中心
- 05_共识引擎
- 06_冲突分析引擎
- 07_AI互审引擎
