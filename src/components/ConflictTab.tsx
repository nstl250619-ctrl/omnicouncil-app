import { useAppStore } from '../stores/appStore';

export function ConflictTab() {
  const conflict = useAppStore((s) => s.conflict);

  if (!conflict) {
    return (
      <div className="empty-state">
        <div className="empty-icon">⚔️</div>
        <div className="empty-title">等待冲突分析</div>
        <div className="empty-desc">对比分析完成后自动识别冲突</div>
      </div>
    );
  }

  return (
    <div className="conflict-view">
      <div className="conflict-header">
        <span>⚔️ 冲突分析</span>
      </div>
      <div className="conflict-content">
        <p>冲突分析结果将在此显示</p>
      </div>
    </div>
  );
}
