import { useAppStore } from '../stores/appStore';

export function ConsensusTab() {
  const consensus = useAppStore((s) => s.consensus);

  if (!consensus) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🤝</div>
        <div className="empty-title">等待共识分析</div>
        <div className="empty-desc">对比分析完成后自动提取共识</div>
      </div>
    );
  }

  return (
    <div className="consensus-view">
      <div className="consensus-header">
        <span>🤝 共识分析</span>
      </div>
      <div className="consensus-content">
        <p>共识分析结果将在此显示</p>
      </div>
    </div>
  );
}
