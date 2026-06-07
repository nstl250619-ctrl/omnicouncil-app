# omnicounci1l-judge

AI 裁判引擎 — 可选的外部 AI 裁决，用于验证共识结论。

## 安装

```bash
pip install omnicounci1l-judge
```

## 使用

```python
from omnicounci1l_judge import JudgeEngine

engine = JudgeEngine(api_keys={"openai": "sk-..."})
verdict = await engine.judge(
    round_ctx, comparison_ctx, consensus_report, conflict_result
)

print(verdict.verdict)     # 裁决结果
print(verdict.reasoning)   # 推理过程
print(verdict.confidence)  # 置信度 0-1
```

## 说明

- 这是一个**可选**引擎，系统无需它即可运行
- 需要外部 AI API Key 才能工作
- 未配置 API Key 时返回降级结果
