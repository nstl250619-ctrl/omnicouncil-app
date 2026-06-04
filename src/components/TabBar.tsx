import { useAppStore, TabId } from '../stores/appStore';

const TABS: { id: TabId; label: string }[] = [
  { id: 'responses', label: 'AI回复' },
  { id: 'comparison', label: '对比分析' },
  { id: 'consensus', label: '共识分析' },
  { id: 'conflict', label: '冲突分析' },
  { id: 'history', label: '历史记录' },
];

export function TabBar() {
  const activeTab = useAppStore((s) => s.activeTab);
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const responses = useAppStore((s) => s.responses);
  const comparison = useAppStore((s) => s.comparison);
  const consensus = useAppStore((s) => s.consensus);
  const conflict = useAppStore((s) => s.conflict);

  const total = Object.keys(responses).length;
  const completed = Object.values(responses).filter((r) => r.status === 'completed').length;
  const isRunning = Object.values(responses).some((r) => r.status === 'waiting' || r.status === 'streaming');

  const getBadge = (tabId: TabId): string | null => {
    switch (tabId) {
      case 'responses':
        if (isRunning) return `${completed}/${total}`;
        if (completed > 0) return '✅';
        return null;
      case 'comparison':
        return comparison ? '✅' : null;
      case 'consensus':
        return consensus ? '✅' : null;
      case 'conflict':
        return conflict ? '⚠️' : null;
      default:
        return null;
    }
  };

  return (
    <div className="tab-bar">
      {TABS.map((tab) => {
        const badge = getBadge(tab.id);
        return (
          <button
            key={tab.id}
            className={`tab-btn ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
            {badge && <span className="tab-badge">{badge}</span>}
          </button>
        );
      })}
    </div>
  );
}
