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

  return (
    <div className="tab-bar">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          className={`tab-btn ${activeTab === tab.id ? 'active' : ''}`}
          onClick={() => setActiveTab(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
