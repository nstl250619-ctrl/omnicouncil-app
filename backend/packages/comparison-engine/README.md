# omnicounci1l-comparison

对比分析引擎 — 6 阶段流水线分析多个 AI 回复的相似度、差异和独有观点。

## 安装

```bash
pip install omnicounci1l-comparison
```

## 使用

```python
from omnicounci1l_comparison import ComparisonEngine

engine = ComparisonEngine()
result = engine.analyze(round_context)

print(result.similarity_matrix)  # 相似度矩阵
print(result.differences)        # 差异列表
print(result.unique_insights)    # 独有观点
```

## 流水线

1. 文本预处理
2. 语义单元提取
3. 相似度分析 (TF-IDF + LCS + 余弦)
4. 差异检测
5. 独有观点提取
6. 结果组装

## 依赖

- `numpy` — 矩阵运算
- `scikit-learn` — TF-IDF 向量化
