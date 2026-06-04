import { useAppStore } from '../stores/appStore';

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

  return (
    <div className="comparison-view">
      <div className="comparison-header">
        <span>📊 整体分析</span>
      </div>
      <div className="comparison-metrics">
        <div className="metric">
          <span className="metric-label">语义单元数</span>
          <span className="metric-value">{String(comparison.semantic_units_count || 0)}</span>
        </div>
        <div className="metric">
          <span className="metric-label">整体分歧度</span>
          <span className="metric-value">{((comparison.metrics as Record<string, number>)?.overall_divergence * 100 || 0).toFixed(1)}%</span>
        </div>
      </div>
    </div>
  );
}
