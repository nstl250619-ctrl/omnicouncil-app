# 架构审计报告 V2

## 总评

| 维度 | 评分 | 等级 |
|------|------|------|
| 架构质量 | 5.5/10 | C |
| 代码质量 | 6.0/10 | C+ |
| 测试覆盖 | 3.0/10 | F |
| 可维护性 | 5.0/10 | C- |
| 扩展性 | 4.5/10 | D+ |
| 技术债 | 3.5/10 | D |

**综合评分: 4.6/10 (D+)**

---

## 1. 架构质量: 5.5/10

### 优点 (+)

- **清晰的分层设计**: Layer1(Access) → Layer2(Scheduler) → Layer3(Collector) → Layer4(Comparison) 职责分明
- **事件驱动通信**: EventBus 实现了层间解耦
- **不可变数据类型**: 所有核心类型使用 `frozen=True` dataclass
- **单一职责**: 每个文件 200-400 行，模块划分合理
- **工厂模式**: BrowserEngine 通过工厂创建，支持模式切换
- **自动发现**: ProviderRegistry 自动扫描 providers/ 目录

### 问题 (-)

- **双重架构**: Provider 系统和 Adapter 系统并行存在，同一功能实现两次
- **废弃模块未清理**: ConflictEngine/ConsensusEngine/JudgeEngine/SessionManager 完全未使用
- **AppState 服务定位器**: 全局单例隐式耦合，无法独立测试
- **层间边界不一致**: Layer2→1 直接调用，Layer2→3 事件驱动，Layer3→4 混合
- **Browser 层包含业务逻辑**: EmbeddedEngine 硬编码了 AI 特定的登录检测和 cookie 检查
- **缺少配置层**: `default.yaml` 不存在，全部使用默认值

### 评分依据

分层架构是好的起点，但双重 Provider/Adapter 架构和大量废弃模块严重拉低了评分。架构意图清晰，但执行不够彻底。

---

## 2. 代码质量: 6.0/10

### 优点 (+)

- **类型注解完整**: 所有函数都有类型注解
- **文档字符串**: 关键类和方法有 docstring
- **错误处理**: 统一的错误类型层次结构
- **日志规范**: 统一的 `get_logger()` 接口
- **代码行数控制**: 大部分文件 < 300 行
- **import 规范**: 使用 `from __future__ import annotations`

### 问题 (-)

- **Provider 代码重复**: 5 个 Provider 的 `send_message()` 有 80%+ 重复代码
- **响应提取逻辑**: 6 处独立实现相同的 body 文本解析模式
- **硬编码**: AI ID 列表、UI 元素列表、URL 检查散布在多个文件中
- **空方法**: 多个 `pass`/`return True`/`return False` 的空实现
- **未使用的参数**: 一些函数有未使用的参数（如 `round_number`）
- **字符串魔法**: 错误码、事件名、消息类型都是硬编码字符串

### 评分依据

代码风格整体规范，类型注解和文档做得不错。但大量重复代码和硬编码是明显的质量问题。

---

## 3. 测试覆盖: 3.0/10

### 现有测试

| 文件 | 行数 | 类型 |
|------|------|------|
| test_smoke.py | 126 | 冒烟测试 |
| test_browser_engine.py | 104 | 浏览器引擎测试 |
| test_integration.py | 234 | 集成测试 |
| test_login_flow.py | 169 | 登录流程测试 |
| test_profile_sharing.py | 166 | Profile 共享测试 |
| test_websocket.py | 85 | WebSocket 测试 |
| **总计** | **884** | |

### 问题 (-)

- **无单元测试**: 没有针对 Layer1-4 各组件的独立单元测试
- **无 Comparison 测试**: 6 阶段管道完全没有测试
- **无 Scheduler 测试**: 调度逻辑完全没有测试
- **无 Collector 测试**: 结果收集逻辑完全没有测试
- **无 Provider 测试**: 5 个 Provider 完全没有测试
- **无前端测试**: 0 个前端测试文件
- **覆盖率未知**: 没有配置覆盖率工具
- **测试文件不足**: 884 行测试 vs 6,946 行后端代码 = ~12.7% 行数比

### 评分依据

测试严重不足。核心业务逻辑（Layer1-4）完全没有单元测试。只有冒烟测试和集成测试，无法保证各模块的正确性。

---

## 4. 可维护性: 5.0/10

### 优点 (+)

- **模块化结构**: 按功能划分目录
- **共享类型**: `shared/types.py` 统一定义所有数据类型
- **事件解耦**: EventBus 使得添加新的事件处理器不需要修改现有代码
- **配置驱动**: ComparisonConfig 等使用 dataclass 配置

### 问题 (-)

- **修改一个 AI 需要改 3 个地方**: Provider + Adapter + Config
- **添加新 AI 流程不清晰**: 需要创建 Provider 目录 + Adapter 文件 + 注册
- **废弃代码干扰**: 3 个未使用的 engine 子包让新开发者困惑
- **隐式依赖**: 通过 AppState 全局访问，依赖关系不透明
- **无 API 文档**: WebSocket 协议没有文档
- **无错误码文档**: 错误码体系没有文档

### 评分依据

基本结构合理，但双重架构和废弃代码显著增加了维护成本。修改一个 AI 的行为需要理解并修改多个位置的代码。

---

## 5. 扩展性: 4.5/10

### 优点 (+)

- **Provider 自动发现**: 添加新 Provider 只需创建目录
- **BrowserEngine 抽象**: 可以切换 CDP/Embedded 模式
- **EventBus**: 添加新的事件处理器很容易
- **Comparison 管道**: 6 阶段设计理论上可扩展

### 问题 (-)

- **Gemini/ChatGPT/Claude 无法使用**: 缺少对应 Adapter，Provider 只是空壳
- **添加新 AI 需要**: 创建 Provider + 创建 Adapter + 修改 main.py 注册 + 修改 EmbeddedEngine 硬编码
- **Browser 层不可扩展**: 硬编码了 AI 特定逻辑
- **Comparison 管道不可插拔**: 6 个 Stage 是硬编码的，无法动态添加/替换
- **无插件系统**: 所有组件在 main.py 中硬编码组装
- **无中间件**: 无法在请求链路中插入自定义逻辑

### 评分依据

理论上设计了扩展点（Provider 自动发现、BrowserEngine 抽象），但实际上扩展一个新 AI 需要修改多个文件。Gemini/ChatGPT/Claude 的空壳 Provider 说明扩展性承诺未兑现。

---

## 6. 技术债: 3.5/10

### 高风险债项

| 债项 | 风险 | 影响 |
|------|------|------|
| Provider/Adapter 双重架构 | P0 | 每次修改 AI 逻辑需要改两处 |
| 内存泄漏（_tasks/_contexts 无限增长） | P0 | 长时间运行后 OOM |
| 3 个废弃 Engine 未清理 | P1 | 新开发者困惑，维护成本 |
| 无单元测试 | P1 | 重构无安全网 |
| 响应提取 6 处重复 | P1 | Bug 修复需要改 6 处 |
| Browser 硬编码 AI 逻辑 | P2 | 添加新 AI 需要改 Browser 层 |
| SessionManager/Storage 未使用 | P2 | 代码噪音 |
| EventBus 无错误传播 | P2 | 处理器失败被静默吞掉 |

### 评分依据

存在多个 P0/P1 级别的技术债。内存泄漏和双重架构是最紧迫的问题。缺乏测试使得任何重构都有高风险。

---

## 总结

### 架构意图 vs 实际执行

| 维度 | 意图 | 实际 |
|------|------|------|
| 分层架构 | Layer1-4 清晰分离 | ✅ 基本实现 |
| Provider 自动发现 | 添加新 AI 很简单 | ❌ 只发现了一半（Provider），Adapter 需要手动 |
| 事件驱动 | 层间通过事件解耦 | ⚠️ 混合使用（部分直接调用，部分事件） |
| 不可变数据 | frozen=True | ✅ 完全实现 |
| 浏览器抽象 | 支持多种引擎 | ⚠️ 只有 Embedded 可用 |
| 对比分析 | 6 阶段管道 | ✅ 实现完整 |
| 冲突/共识/裁判 | 高级分析 | ❌ 完全未接入 |
| 测试覆盖 | 80%+ | ❌ ~13% 行数比，0% 有意义的覆盖 |

### 最需要改进的 3 件事

1. **统一 Provider/Adapter**: 合并为一套系统，消除重复
2. **添加单元测试**: 至少覆盖 Layer1-4 的核心逻辑
3. **清理废弃代码**: 删除 ConflictEngine/ConsensusEngine/JudgeEngine/SessionManager
