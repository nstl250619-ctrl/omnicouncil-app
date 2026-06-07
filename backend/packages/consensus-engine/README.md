# omnicounci1l-consensus

共识分析引擎 — 从多个 AI 的回复中发现共识点和分歧点。

## 安装

```bash
pip install omnicounci1l-consensus
```

## 使用

```python
from omnicounci1l_consensus import ConsensusEngine

engine = ConsensusEngine()
report = engine.analyze(round_context, comparison_context)

print(report.conclusion)        # 共识结论
print(report.confidence)        # 置信度 0-1
print(report.consensus_points)  # 共识点列表
print(report.disagreements)     # 分歧点列表
```

## 接口

```python
class ConsensusEngine:
    def analyze(
        self,
        round_ctx: RoundContext,
        comparison_ctx: ComparisonContext,
    ) -> ConsensusReport
```

## 输出类型

- `ConsensusReport` — 最终报告
- `ConsensusPoint` — 共识点
- `DisagreementPoint` — 分歧点
- `ConsensusRecommendation` — 建议
- `ConsensusSummaryStats` — 统计摘要
