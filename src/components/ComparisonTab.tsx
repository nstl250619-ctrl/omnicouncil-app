import { useAppStore } from '../stores/appStore';

const AI_NAMES: Record<string, string> = {
  deepseek: 'DeepSeek',
  gemini: 'Gemini',
  qianwen: '千问',
};

function SimilarityBar({ aiA, aiB, similarity }: { aiA: string; aiB: string; similarity: number }) {
  const nameA = AI_NAMES[aiA] || aiA;
  const nameB = AI_NAMES[aiB] || aiB;
  const percent = Math.round(similarity * 100);
  const color = similarity > 0.7 ? '#22c55e' : similarity > 0.4 ? '#f59e0b' : '#ef4444';

  return (
    <div className="similarity-bar-item">
      <div className="similarity-label">
        <span>{nameA}</span>
        <span className="similarity-arrow">↔</span>
        <span>{nameB}</span>
      </div>
      <div className="similarity-bar-track">
        <div className="similarity-bar-fill" style={{ width: `${percent}%`, background: color }} />
      </div>
      <span className="similarity-value" style={{ color }}>{percent}%</span>
    </div>
  );
}

export function ComparisonTab() {
  const comparison = useAppStore((s) => s.comparison);

  if (!comparison) {
    return (
      <div className="empty-state">
        <div className="empty-icon">📊</div>
        <div className="empty-title">等待对比分析</div>
        <div className="empty-desc">所有AI完成后自动进行对比分析</div>
      </div>
    );
  }

  const metrics = (comparison.metrics as Record<string, unknown>) || {};
  const differences = (comparison.differences as Array<Record<string, unknown>>) || [];
  const uniqueInsights = (comparison.unique_insights as Array<Record<string, unknown>>) || [];
  const pairwiseSimilarities = (metrics.pairwise_similarities as Array<{ ai_a: string; ai_b: string; similarity: number }>) || [];

  return (
    <div className="comparison-view">
      {/* Summary */}
      <div className="comparison-summary">
        <div className="summary-card">
          <span className="summary-icon">📊</span>
          <span className="summary-text">
            语义单元: <strong>{String(metrics.total_units || 0)}</strong>
          </span>
        </div>
        <div className="summary-card">
          <span className="summary-icon">🔀</span>
          <span className="summary-text">
            分歧度: <strong>{((metrics.overall_divergence as number || 0) * 100).toFixed(1)}%</strong>
          </span>
        </div>
        <div className="summary-card">
          <span className="summary-icon">⚠️</span>
          <span className="summary-text">
            差异点: <strong>{differences.length}</strong>
          </span>
        </div>
        <div className="summary-card">
          <span className="summary-icon">💡</span>
          <span className="summary-text">
            独观点: <strong>{uniqueInsights.length}</strong>
          </span>
        </div>
      </div>

      {/* Similarity Matrix */}
      {pairwiseSimilarities.length > 0 && (
        <div className="comparison-section">
          <h3 className="section-title">🔗 相似度</h3>
          <div className="similarity-bars">
            {pairwiseSimilarities.map((sim, i) => (
              <SimilarityBar key={i} aiA={sim.ai_a} aiB={sim.ai_b} similarity={sim.similarity} />
            ))}
          </div>
        </div>
      )}

      {/* Differences */}
      {differences.length > 0 && (
        <div className="comparison-section">
          <h3 className="section-title">🔍 差异点</h3>
          <div className="difference-list">
            {differences.map((diff, i) => (
              <div key={i} className="difference-card">
                <div className="diff-header">
                  <span className="diff-dimension">{String(diff.dimension || '未知')}</span>
                  <span className="diff-strength">
                    强度: {((diff.strength as number || 0) * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="diff-positions">
                  {(diff.involved_ais as Array<{ ai_id: string; stance: string }>)?.map((inv, j) => (
                    <div key={j} className="diff-position">
                      <span className="diff-ai" style={{ color: getAIColor(inv.ai_id) }}>
                        {AI_NAMES[inv.ai_id] || inv.ai_id}
                      </span>
                      <span className="diff-stance">{inv.stance}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Unique Insights */}
      {uniqueInsights.length > 0 && (
        <div className="comparison-section">
          <h3 className="section-title">💡 独特观点</h3>
          <div className="insight-list">
            {uniqueInsights.map((insight, i) => (
              <div key={i} className="insight-card">
                <div className="insight-header">
                  <span className="insight-ai" style={{ color: getAIColor(insight.ai_id as string) }}>
                    💎 {AI_NAMES[insight.ai_id as string] || insight.ai_id}
                  </span>
                  <span className="insight-novelty">
                    新颖度: {((insight.novelty_score as number || 0) * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="insight-content">{String(insight.content || '')}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* No findings */}
      {differences.length === 0 && uniqueInsights.length === 0 && (
        <div className="comparison-section">
          <div className="no-findings">
            🎉 所有AI的回答高度一致，没有发现显著差异或独特观点。
          </div>
        </div>
      )}
    </div>
  );
}

function getAIColor(aiId: string): string {
  const colors: Record<string, string> = {
    deepseek: '#4f8fff',
    gemini: '#8b5cf6',
    qianwen: '#f59e0b',
  };
  return colors[aiId] || '#6366f1';
}
