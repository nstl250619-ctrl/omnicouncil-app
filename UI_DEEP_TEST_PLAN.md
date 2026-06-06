# OmniCouncil V1 — UI 深度调试测试计划

## 测试环境

```
前端: React + Zustand + Vite (localhost:5173)
后端: FastAPI + WebSocket (localhost:8765)
桌面: Tauri (src-tauri)
```

---

## 一、连接测试

### 1.1 WebSocket 连接

```
测试步骤:
  1. 启动后端 (uvicorn)
  2. 启动前端 (npm run dev)
  3. 观察浏览器控制台

预期:
  - [WS] Connected 出现
  - 收到 engine_status 消息
  - connectionStatus = "connected"

异常场景:
  - 后端未启动 → connectionStatus = "disconnected" → 自动重连
  - 后端重启 → 自动恢复连接
  - 网络断开 → reconnecting 状态 → 恢复后自动连接
```

### 1.2 心跳

```
测试步骤:
  1. 连接后等待 15 秒
  2. 检查 Network 面板

预期:
  - 每 15 秒发送 ping
  - 收到 pong 响应
  - 连接保持活跃
```

---

## 二、Provider 管理测试

### 2.1 AI Platform Manager (首次启动)

```
测试步骤:
  1. 清除 localStorage
  2. 重启前端
  3. 观察页面

预期:
  - 显示 AIPlatformManager (setup mode)
  - 列出所有 Provider (DeepSeek, Qianwen, Gemini, ChatGPT, MiMo)
  - 每个 Provider 显示连接状态
  - "完成" 按钮可点击

验证点:
  - [ ] Provider 列表正确显示
  - [ ] 颜色/图标正确
  - [ ] 初始状态为 disconnected
  - [ ] 完成后进入主界面
```

### 2.2 Provider 登录

```
测试步骤:
  1. 点击 DeepSeek 的 "连接" 按钮
  2. 观察浏览器弹窗
  3. 手动完成登录
  4. 关闭弹窗

预期:
  - 弹出 Chromium 浏览器窗口
  - 导航到 DeepSeek 登录页
  - 登录成功后状态变为 "authenticated"
  - auth_status WebSocket 消息广播

验证点:
  - [ ] 浏览器弹窗正常
  - [ ] 登录页正确加载
  - [ ] 登录成功检测
  - [ ] UI 状态更新 (connected=true)
  - [ ] authStatus store 更新
```

### 2.3 Session 恢复

```
测试步骤:
  1. 完成 DeepSeek 登录
  2. 关闭前端
  3. 重新启动前端
  4. 检查 DeepSeek 状态

预期:
  - DeepSeek 状态为 connected (无需重新登录)
  - 通过 /api/sessions/status 检测到 cookie
  - 通过 engine_status WebSocket 消息同步

验证点:
  - [ ] 重启后自动恢复
  - [ ] 无需用户干预
  - [ ] 状态正确显示
```

---

## 三、查询执行测试

### 3.1 提交查询

```
测试步骤:
  1. 确保 DeepSeek 已登录
  2. 在 QueryInput 输入 "hello"
  3. 选择 DeepSeek
  4. 点击发送

预期:
  - QueryInput 显示发送状态
  - TabBar 切换到 responses
  - ResponsesTab 显示 DeepSeek 的等待状态
  - StatusBar 显示 "分析中..."

验证点:
  - [ ] 输入框正常工作
  - [ ] AI 选择器正常
  - [ ] 发送触发 WebSocket submit_query
  - [ ] 进度条显示
  - [ ] 状态栏更新
```

### 3.2 响应接收

```
测试步骤:
  1. 提交查询后等待
  2. 观察 ResponsesTab

预期:
  - 收到 ai_completed 消息
  - DeepSeek 状态从 waiting → completed
  - 显示 AI 响应内容
  - 显示字数和耗时

验证点:
  - [ ] 响应内容正确显示
  - [ ] 无 UI 噪音
  - [ ] 字数统计正确
  - [ ] 耗时显示正确
  - [ ] 状态图标正确 (✅)
```

### 3.3 多 AI 并发

```
测试步骤:
  1. 选择 DeepSeek + Qianwen (如已登录)
  2. 提交查询
  3. 观察两个 AI 的响应

预期:
  - 两个 AI 同时开始
  - 独立显示各自状态
  - 先完成的先显示结果
  - 全部完成后触发 Comparison

验证点:
  - [ ] 并发执行正常
  - [ ] 状态独立更新
  - [ ] 无交叉污染
  - [ ] all_completed 触发
```

---

## 四、分析结果测试

### 4.1 Comparison Tab

```
测试步骤:
  1. 完成一个多 AI 查询
  2. 切换到 Comparison Tab
  3. 检查显示内容

预期:
  - comparison_ready 消息到达
  - 显示语义单元数量
  - 显示差异项列表
  - 显示独特洞察
  - 显示指标 (divergence, similarity)

验证点:
  - [ ] 数据正确渲染
  - [ ] 差异项可展开
  - [ ] 独特洞察可展开
  - [ ] 指标数值正确
  - [ ] 无空数据异常
```

### 4.2 Consensus Tab

```
测试步骤:
  1. 完成一个多 AI 查询
  2. 切换到 Consensus Tab
  3. 检查显示内容

预期:
  - consensus_ready 消息到达
  - 显示共识结论
  - 显示置信度
  - 显示共识点列表
  - 显示分歧点列表
  - 显示建议列表

验证点:
  - [ ] 结论文本正确
  - [ ] 置信度显示正确
  - [ ] 共识点可展开
  - [ ] 分歧点可展开
  - [ ] 建议列表显示
  - [ ] degraded 状态处理
```

### 4.3 Conflict Tab

```
测试步骤:
  1. 完成一个多 AI 查询
  2. 切换到 Conflict Tab
  3. 检查显示内容

预期:
  - conflict_ready 消息到达
  - 显示冲突摘要
  - 显示冲突点列表
  - 每个冲突点显示各方立场
  - 显示根因分析

验证点:
  - [ ] 冲突列表正确
  - [ ] 立场对比清晰
  - [ ] 根因分析显示
  - [ ] 严重度标识正确
  - [ ] 无冲突时显示 "无显著冲突"
```

---

## 五、错误处理测试

### 5.1 Provider 错误

```
测试步骤:
  1. 断开网络
  2. 提交查询
  3. 观察错误处理

预期:
  - 收到 error WebSocket 消息
  - ErrorToast 显示错误信息
  - Provider 状态变为 error
  - 其他 Provider 不受影响

验证点:
  - [ ] 错误消息显示
  - [ ] recoverable 标识正确
  - [ ] 重试按钮可用
  - [ ] 不影响其他 AI
```

### 5.2 登录过期

```
测试步骤:
  1. 手动清除 DeepSeek cookies
  2. 提交查询
  3. 观察处理

预期:
  - 检测到 login_required
  - 触发重新登录流程
  - 或显示 "需要重新登录" 错误

验证点:
  - [ ] 过期检测正确
  - [ ] 错误消息清晰
  - [ ] 可触发重新登录
```

### 5.3 WebSocket 断连

```
测试步骤:
  1. 停止后端
  2. 观察前端状态
  3. 重启后端
  4. 观察恢复

预期:
  - connectionStatus → "disconnected"
  - 2 秒后尝试重连
  - connectionStatus → "reconnecting"
  - 后端恢复后 → "connected"

验证点:
  - [ ] 断连检测及时
  - [ ] 自动重连工作
  - [ ] 状态显示正确
  - [ ] 恢复后功能正常
```

---

## 六、UI 状态同步测试

### 6.1 StatusBar

```
测试场景:
  - 空闲状态: 显示 "就绪"
  - 查询执行中: 显示 "分析中..."
  - 连接断开: 显示 "未连接"
  - 错误状态: 显示错误信息

验证点:
  - [ ] 状态文本正确
  - [ ] 颜色标识正确
  - [ ] 实时更新
```

### 6.2 TabBar

```
测试场景:
  - 默认显示 responses tab
  - 点击切换 tab
  - 分析完成后 tab 可用

验证点:
  - [ ] Tab 切换正常
  - [ ] 未完成的 tab 禁用
  - [ ] 数据到达后 tab 启用
  - [ ] 当前 tab 高亮
```

### 6.3 HistoryView

```
测试场景:
  - 完成查询后查看历史
  - 历史列表正确显示
  - 点击历史项查看详情

验证点:
  - [ ] 历史记录保存
  - [ ] 列表排序正确
  - [ ] 详情显示完整
  - [ ] 删除功能正常
```

---

## 七、Tauri 桌面测试

### 7.1 窗口行为

```
测试场景:
  - 窗口标题栏显示
  - 最小化/最大化正常
  - 关闭窗口行为

验证点:
  - [ ] 自定义标题栏工作
  - [ ] 窗口拖拽正常
  - [ ] 关闭时后端进程清理
```

### 7.2 Python 进程管理

```
测试场景:
  - Tauri 启动 Python 后端
  - Tauri 关闭时清理 Python 进程

验证点:
  - [ ] Python 进程正确启动
  - [ ] 端口 8765 被监听
  - [ ] 关闭时进程清理
  - [ ] 无僵尸进程
```

---

## 八、性能测试

### 8.1 响应时间

```
测试场景:
  - DeepSeek 单次查询: < 15s
  - UI 渲染延迟: < 100ms
  - WebSocket 消息延迟: < 50ms

验证点:
  - [ ] 响应时间在预期范围
  - [ ] UI 无卡顿
  - [ ] 消息传递及时
```

### 8.2 内存使用

```
测试场景:
  - 连续 10 次查询
  - 监控浏览器内存

验证点:
  - [ ] 内存无持续增长
  - [ ] 无内存泄漏警告
  - [ ] GC 正常工作
```

---

## 九、兼容性测试

### 9.1 浏览器兼容性

```
测试环境:
  - Chrome 120+
  - Firefox 120+
  - Safari 17+
  - Edge 120+

验证点:
  - [ ] 页面正常渲染
  - [ ] WebSocket 连接正常
  - [ ] 样式一致
  - [ ] 功能正常
```

### 9.2 分辨率测试

```
测试分辨率:
  - 1920x1080 (Full HD)
  - 1440x900 (笔记本)
  - 1280x720 (小屏幕)
  - 2560x1440 (2K)

验证点:
  - [ ] 布局自适应
  - [ ] 文字可读
  - [ ] 按钮可点击
  - [ ] 无溢出
```

---

## 十、测试执行清单

```
优先级 P0 (必须通过):
  [ ] WebSocket 连接正常
  [ ] Provider 登录成功
  [ ] 查询提交 + 响应接收
  [ ] Session 恢复
  [ ] 错误处理

优先级 P1 (应该通过):
  [ ] 多 AI 并发
  [ ] Comparison 显示
  [ ] Consensus 显示
  [ ] Conflict 显示
  [ ] 状态同步

优先级 P2 (最好通过):
  [ ] 历史记录
  [ ] 性能测试
  [ ] 兼容性测试
  [ ] Tauri 桌面测试
```

---

## 测试结果模板

```
测试日期: ____
测试环境: ____
测试人员: ____

连接测试:     PASS / FAIL
Provider 测试: PASS / FAIL
查询测试:     PASS / FAIL
分析测试:     PASS / FAIL
错误处理:     PASS / FAIL
UI 状态:      PASS / FAIL
Tauri:        PASS / FAIL
性能:         PASS / FAIL
兼容性:       PASS / FAIL

总体结果: PASS / FAIL

备注:
____
```
