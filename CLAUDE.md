## 架构约束（每次修改代码前强制执行）

本项目已建立 Provider Runtime OS v2 统一架构。在修复任何 Bug 或实现功能前，必须先检索已有框架能力：

### 1. 框架能力清单（修改代码前必须逐一检查）

| 问题领域 | 已有框架能力 | 位置 |
|----------|-------------|------|
| 认证/会话 | AuthManager + AuthStrategy + SessionLifecycle | auth/ |
| 页面交互 | PageInteractionManager（配置驱动，选择器来自 YAML） | providers/interaction_manager.py |
| 选择器失效 | SelectorHealthChecker（自动降级 + 备选选择器） | providers/selector_health.py |
| 登录恢复 | LoginRecoveryHandler + SessionStateBus | auth/login_recovery.py, runtime/session_bus.py |
| 健康监控 | PlatformHealthMonitor + Dashboard API | runtime/health_monitor.py, api/dashboard.py |

### 2. 禁止事项

- 禁止在单个 Provider adapter 中覆写以下方法（已由 BaseQueryAdapter + PageInteractionManager 提供）：
  _find_input, _extract_response, _try_selector_extraction, _try_body_extraction, _is_ui_element, pre_flight_check
- 禁止在 Provider adapter 中硬编码 CSS 选择器、Cookie 域名、Cookie 名称——这些必须来自 YAML 配置
- 禁止新建与现有框架能力重复的模块

### 3. 修复流程（必须按顺序执行）

1. 定位报错的具体位置和直接原因
2. 检查：这个原因是否已有框架能力可以覆盖？
   - 如果已有能力被绕过/未正确使用 → 修复调用链路，让框架能力生效
   - 如果框架能力不足 → 扩展框架层（BaseQueryAdapter/AuthManager/SessionLifecycle），确保所有 Provider 同时受益
3. 修复后，确认：
   - 没有新增与框架重复的代码
   - 所有 Provider 行为一致
   - 配置驱动而非硬编码

### 4. 不允许的修复方式（示例）

❌ Grok 找不到输入框 → 在 GrokQueryAdapter 中写 _find_input 方法
✅ Grok 找不到输入框 → 检查 provider.yaml 中的 input_selectors 是否正确，修正 YAML 配置
