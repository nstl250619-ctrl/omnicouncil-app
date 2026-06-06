当前剩余P0列表

按风险排序

P0-1
问题：SchedulerCenter._tasks 内存泄漏 — dict 永不清理
文件：backend/engine/layers/layer2_scheduler/scheduler_center.py
状态：已修复

P0-2
问题：ResultCollector._contexts 内存泄漏 — dict 存储所有 RoundContext，永不清理
文件：backend/engine/layers/layer3_collector/result_collector.py
状态：未修复

P0-3
问题：ComparisonEngine._contexts 内存泄漏 — dict 存储所有 ComparisonContext（含完整语义单元和相似度矩阵），永不清理
文件：backend/engine/layers/layer4_comparison/comparison_engine.py
状态：未修复

P0-4
问题：Provider/Adapter 双重架构 — 同一 DeepSeek/千问有两套独立实现（providers/ + adapters/），修改 AI 逻辑需要改 3 处
文件：backend/providers/ + backend/engine/layers/layer1_ai_access/
状态：未修复

P0-5
问题：响应提取逻辑 6 处重复 — 所有 Provider 的 send_message() 和 BrowserAIAdapter 的 _extract_response() 独立实现相同的 body 文本解析轮询模式
文件：providers/deepseek/provider.py, providers/qianwen/provider.py, providers/gemini/provider.py, providers/chatgpt/provider.py, providers/claude/provider.py, browser_adapter.py
状态：未修复

推荐下一步处理的唯一P0问题：

P0-2: ResultCollector._contexts 内存泄漏

原因：
1. 与 P0-1 同属内存泄漏类别，修复模式完全一致（在任务完成时添加清理调用）
2. 风险最低 — 不涉及架构变更，只添加清理逻辑
3. RoundContext 包含完整 AI 响应文本（可能数 KB），比 _tasks 的 ~300 字节/条泄漏更快
4. 修复方法：在 _assemble_context() 完成后清理旧的 contexts，或添加与 SchedulerCenter.cleanup_old_tasks() 类似的清理方法
