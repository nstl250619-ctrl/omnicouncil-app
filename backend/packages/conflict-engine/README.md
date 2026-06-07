# omnicounci1l-conflict

冲突分析引擎 — 分析 AI 回复之间的分歧原因和根因。

## 安装

```bash
pip install omnicounci1l-conflict
```

## 使用

```python
from omnicounci1l_conflict import ConflictEngine

engine = ConflictEngine()
result = engine.analyze(round_context, comparison_context, consensus_report)

print(result.conflicts)             # 冲突点列表
print(result.overall_conflict_level) # 整体冲突程度 0-1
print(result.summary)               # 冲突摘要
```

## 接口

```python
class ConflictEngine:
    def analyze(
        self,
        round_ctx: RoundContext,
        comparison_ctx: ComparisonContext,
        consensus_report: Any | None = None,
    ) -> ConflictResult
```

## 冲突根因分类

- 事实性分歧 — 不同数据来源
- 观点性分歧 — 不同价值判断
- 方法论分歧 — 不同解决路径
