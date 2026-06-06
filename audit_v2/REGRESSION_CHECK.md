验证以下内容：

Layer1
PASS

Layer2
PASS

Layer3
PASS

Layer4
PASS

Provider
PASS

Browser
PASS

WebSocket
PASS

说明：

验证依据
本次修改仅在 SchedulerCenter._execute_task_safe() 的 finally 块中新增一行 self.cleanup_old_tasks() 调用。cleanup_old_tasks() 是已有方法，逻辑未变。修改不涉及 Layer1/3/4、Provider、Browser、WebSocket 的任何代码。回归验证的核心目标是确认：1) 修改后的文件可正常导入；2) 现有测试全部通过；3) cleanup 逻辑在模拟场景下行为正确。

验证过程
1. 运行完整 smoke 测试套件 (tests/test_smoke.py)，覆盖所有 Layer 的导入验证：
   - TestSharedImports: config, errors, event_bus, types
   - TestBrowserImports: engine_abc, factory
   - TestProviderImports: base_provider, registry, all_providers_importable
   - TestEngineLayerImports: layer1_ai_access, layer2_scheduler, layer3_collector, layer4_comparison
   - TestSessionImports: session_storage, session_manager
   - TestMainImport: main_module_importable

2. 逐层独立导入验证：Layer1 (AIAccessManager, CircuitBreaker, RateLimiter, ProviderManager, ResponseNormalizer), Layer2 (SchedulerCenter, ConcurrencyController, RetryManager, TimeoutManager), Layer3 (ResultCollector), Layer4 (ComparisonEngine, TextPreprocessor, SemanticUnitExtractor, SimilarityAnalyzer, DifferenceAnalyzer, UniqueInsightExtractor, ComparisonAssembler), Provider (Registry, BaseProvider, 5个具体Provider), Browser (BrowserEngine, Factory, EmbeddedEngine, CDPEngine), WebSocket (ConnectionManager, websocket_endpoint, GlobalExceptionHandler), Shared (AppState, EventBus, Config, Types, Errors, Logger)

3. cleanup_old_tasks() 功能验证：创建 1050 个已完成任务（状态 COMPLETED，时间戳 2 小时前），调用 cleanup_old_tasks()，确认清理至 0 条（所有任务超过 3600 秒阈值），cancel_events 同步清理。

验证结果
- smoke 测试: 16/16 passed in 0.22s
- 逐层导入: 8/8 PASS
- cleanup 功能: PASS (1050 → 0)
- 总计: 全部 PASS
