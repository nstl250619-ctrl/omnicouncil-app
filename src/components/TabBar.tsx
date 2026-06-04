import { useAppStore, TabId } from '../stores/appStore';

interface TabDef {
  id: TabId;
  label: string;
  requires: TabId | null; // null = always available
}

const TABS: TabDef[] = [
  { id: 'responses', label: 'AI回复', requires: null },
  { id: 'comparison', label: '对比分析', requires: 'responses' },
  { id: 'consensus', label: '共识分析', requires: 'comparison' },
  { id: 'conflict', label: '冲突分析', requires: 'comparison' },
  { id: 'history', label: '历史记录', requires: null },
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

  const isTabEnabled = (tab: TabDef): boolean => {
    if (!tab.requires) return true;
    switch (tab.requires) {
      case 'responses':
        return completed > 0;
      case 'comparison':
        return comparison !== null;
      default:
        return true;
    }
  };

  const getBadge = (tab: TabDef): string | null => {
    switch (tab.id) {
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
        const enabled = isTabEnabled(tab);
        const badge = getBadge(tab);
        return (
          <button
            key={tab.id}
            className={`tab-btn ${activeTab === tab.id ? 'active' : ''} ${!enabled ? 'disabled' : ''}`}
            onClick={() => enabled && setActiveTab(tab.id)}
            disabled={!enabled}
            title={!enabled ? '请先完成前置步骤' : ''}
          >
            {tab.label}
            {badge && <span className="tab-badge">{badge}</span>}
          </button>
        );
      })}
    </div>
  );
}
