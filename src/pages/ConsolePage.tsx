import { useState, useMemo, useCallback } from 'react';
import { useAppStore, TabId, type RuntimeHealth } from '../stores/appStore';
import { useWebSocket } from '../hooks/useWebSocket';
import Titlebar from '../components/Titlebar';
import { AIIconSelector } from '../components/AIIconSelector';
import { ResponsesTab } from '../components/ResponsesTab';
import { ComparisonTab } from '../components/ComparisonTab';
import { ConsensusTab } from '../components/ConsensusTab';
import { ConflictTab } from '../components/ConflictTab';
import { JudgeView } from '../components/JudgeView';
import { HistoryView } from '../components/HistoryView';
import { ErrorBoundary } from '../components/ErrorBoundary';

const SIDEBAR_TABS = [
  { id: 'responses' as TabId, label: 'AI 回复', icon: '💬' },
  { id: 'comparison' as TabId, label: '对比分析', icon: '⚖' },
  { id: 'consensus' as TabId, label: '共识分析', icon: '🤝' },
  { id: 'conflict' as TabId, label: '冲突分析', icon: '⚡' },
  { id: 'judge' as TabId, label: '评判建议', icon: '🏛' },
  { id: 'history' as TabId, label: '历史记录', icon: '📋' },
];

interface ConsolePageProps {
  onNavigateToPlatforms: () => void;
}

export function ConsolePage({ onNavigateToPlatforms }: ConsolePageProps) {
  const { send } = useWebSocket();
  const activeTab = useAppStore((s) => s.activeTab);
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const aiList = useAppStore((s) => s.aiList);
  const responses = useAppStore((s) => s.responses);
  const submitQuery = useAppStore((s) => s.submitQuery);
  const connectionStatus = useAppStore((s) => s.connectionStatus);

  const [query, setQuery] = useState('');
  const [selectedAIs, setSelectedAIs] = useState<string[]>(['deepseek', 'qianwen']);

  const isRunning = Object.values(responses).some(
    (r) => r.status === 'waiting' || r.status === 'streaming'
  );

  // Build AI list for icon selector
  const availableAIs = useMemo(() => {
    if (aiList.length > 0) {
      return aiList
        .filter((ai) => ai.enabled)
        .map((ai) => ({
          id: ai.provider_id,
          name: ai.display_name,
          connected: true,
        }));
    }
    return [
      { id: 'deepseek', name: 'DeepSeek', connected: true },
      { id: 'gemini', name: 'Gemini', connected: true },
      { id: 'chatgpt', name: 'ChatGPT', connected: true },
      { id: 'qianwen', name: '千问', connected: true },
      { id: 'mimo', name: 'MiMo', connected: true },
      { id: 'claude', name: 'Claude', connected: false },
      { id: 'copilot', name: 'Copilot', connected: false },
      { id: 'perplexity', name: 'Perplexity', connected: false },
      { id: 'kimi', name: 'Kimi', connected: false },
    ];
  }, [aiList]);

  // Platform status for sidebar (from runtime health)
  const runtimeHealthMap = useAppStore((s) => s.runtimeHealthMap);
  const platformStatuses = useMemo(() => {
    return availableAIs.map((ai) => {
      const rh = runtimeHealthMap[ai.id];
      const state = rh?.state ?? 'unknown';
      return {
        id: ai.id,
        name: ai.name,
        status: state === 'healthy' ? 'connected' : state === 'degraded' ? 'idle' : 'disconnected',
      };
    });
  }, [availableAIs, runtimeHealthMap]);

  const toggleAI = useCallback((id: string) => {
    setSelectedAIs((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }, []);

  const handleSubmit = useCallback(() => {
    if (!query.trim() || selectedAIs.length === 0 || isRunning) return;
    submitQuery(query, selectedAIs);
    send('submit_query', { query, ai_ids: selectedAIs, mode: 'parallel' });
    setQuery('');
  }, [query, selectedAIs, isRunning, submitQuery, send]);

  const handleTabChange = useCallback(
    (tab: TabId) => {
      setActiveTab(tab);
    },
    [setActiveTab]
  );

  // Override activeTab for judge (not in original TabId)
  const currentTab = activeTab === 'review' || activeTab === 'debate' ? 'responses' : activeTab;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', position: 'relative', zIndex: 1 }}>
      <Titlebar statusText={isRunning ? '分析中...' : connectionStatus === 'connected' ? '就绪' : '未连接'} />

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', marginTop: 40 }}>
        {/* Sidebar */}
        <div
          style={{
            width: 190,
            background: 'var(--bg-surface)',
            borderRight: '1px solid var(--border-subtle)',
            display: 'flex',
            flexDirection: 'column',
            flexShrink: 0,
            padding: '12px 0',
          }}
        >
          <div style={sbLabelStyle}>分析</div>
          {SIDEBAR_TABS.filter((t) => t.id !== 'history').map((tab) => (
            <div
              key={tab.id}
              onClick={() => handleTabChange(tab.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 9,
                padding: '8px 16px',
                cursor: 'pointer',
                transition: 'all 0.25s',
                borderLeft: `2px solid ${currentTab === tab.id ? 'var(--accent)' : 'transparent'}`,
                fontFamily: "'Syne', sans-serif",
                fontSize: 13,
                color: currentTab === tab.id ? 'var(--accent)' : 'var(--text-secondary)',
                background: currentTab === tab.id ? 'var(--accent-glow)' : 'transparent',
              }}
            >
              <span style={{ width: 16, textAlign: 'center', fontSize: 13, flexShrink: 0 }}>{tab.icon}</span>
              {tab.label}
            </div>
          ))}
          <div style={sbLabelStyle}>记录</div>
          <div
            onClick={() => handleTabChange('history')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 9,
              padding: '8px 16px',
              cursor: 'pointer',
              transition: 'all 0.25s',
              borderLeft: `2px solid ${currentTab === 'history' ? 'var(--accent)' : 'transparent'}`,
              fontFamily: "'Syne', sans-serif",
              fontSize: 13,
              color: currentTab === 'history' ? 'var(--accent)' : 'var(--text-secondary)',
              background: currentTab === 'history' ? 'var(--accent-glow)' : 'transparent',
            }}
          >
            <span style={{ width: 16, textAlign: 'center', fontSize: 13, flexShrink: 0 }}>📋</span>
            历史记录
          </div>
          <div style={{ flex: 1 }} />

          {/* Platform navigation */}
          <div
            onClick={onNavigateToPlatforms}
            style={{
              padding: '12px 16px',
              borderTop: '1px solid var(--border-subtle)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              fontFamily: "'Syne', sans-serif",
              fontSize: 12,
              color: 'var(--text-muted)',
              transition: 'all 0.25s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = 'var(--accent)';
              e.currentTarget.style.background = 'var(--accent-glow)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'var(--text-muted)';
              e.currentTarget.style.background = 'transparent';
            }}
          >
            🖥 AI 平台管理 →
          </div>

          {/* Platform health status */}
          <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border-subtle)' }}>
            <div
              style={{
                fontFamily: "'DM Mono', monospace",
                fontSize: 10,
                color: 'var(--text-muted)',
                textTransform: 'uppercase',
                letterSpacing: 0.1,
                marginBottom: 8,
              }}
            >
              平台状态
            </div>
            {platformStatuses.map((p) => (
              <div
                key={p.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 7,
                  marginBottom: 5,
                  fontFamily: "'DM Mono', monospace",
                  fontSize: 11,
                  color: 'var(--text-secondary)',
                }}
              >
                <div
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    flexShrink: 0,
                    background:
                      p.status === 'connected'
                        ? 'var(--green)'
                        : p.status === 'idle'
                        ? 'var(--amber)'
                        : 'var(--red)',
                    boxShadow:
                      p.status === 'connected'
                        ? '0 0 6px rgba(62,207,142,0.4)'
                        : p.status === 'idle'
                        ? '0 0 6px rgba(245,158,11,0.4)'
                        : '0 0 6px rgba(239,68,68,0.4)',
                  }}
                />
                {p.name}
              </div>
            ))}
          </div>
        </div>

        {/* Main area */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Tab bar */}
          <div
            style={{
              height: 44,
              background: 'var(--bg-surface)',
              borderBottom: '1px solid var(--border-subtle)',
              display: 'flex',
              alignItems: 'stretch',
              padding: '0 16px',
              flexShrink: 0,
            }}
          >
            {SIDEBAR_TABS.map((tab) => (
              <div
                key={tab.id}
                onClick={() => handleTabChange(tab.id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '0 16px',
                  fontFamily: "'Syne', sans-serif",
                  fontSize: 13,
                  color: currentTab === tab.id ? 'var(--text-primary)' : 'var(--text-muted)',
                  cursor: 'pointer',
                  transition: 'all 0.25s',
                  borderBottom: `2px solid ${currentTab === tab.id ? 'var(--accent)' : 'transparent'}`,
                  whiteSpace: 'nowrap',
                }}
              >
                <span style={{ fontSize: 13, opacity: 0.7 }}>{tab.icon}</span>
                {tab.label}
              </div>
            ))}
          </div>

          {/* Content area */}
          <div style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
            <div
              style={{
                display: currentTab === 'responses' ? 'block' : 'none',
                height: '100%',
                overflowY: 'auto',
                padding: '20px 24px',
              }}
            >
              <ErrorBoundary>
                <ResponsesTab />
              </ErrorBoundary>
            </div>
            <div
              style={{
                display: currentTab === 'comparison' ? 'block' : 'none',
                height: '100%',
                overflowY: 'auto',
                padding: '20px 24px',
              }}
            >
              <ComparisonTab />
            </div>
            <div
              style={{
                display: currentTab === 'consensus' ? 'block' : 'none',
                height: '100%',
                overflowY: 'auto',
                padding: '20px 24px',
              }}
            >
              <ConsensusTab />
            </div>
            <div
              style={{
                display: currentTab === 'conflict' ? 'block' : 'none',
                height: '100%',
                overflowY: 'auto',
                padding: '20px 24px',
              }}
            >
              <ConflictTab />
            </div>
            <div
              style={{
                display: activeTab === 'judge' ? 'block' : 'none',
                height: '100%',
                overflowY: 'auto',
                padding: '20px 24px',
              }}
            >
              <JudgeView />
            </div>
            <div
              style={{
                display: currentTab === 'history' ? 'block' : 'none',
                height: '100%',
                overflowY: 'auto',
                padding: '20px 24px',
              }}
            >
              <HistoryView />
            </div>
          </div>

          {/* Query bar */}
          <div
            style={{
              flexShrink: 0,
              background: 'var(--bg-surface)',
              borderTop: '1px solid var(--border-subtle)',
              padding: '12px 20px 16px',
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
            }}
          >
            <AIIconSelector ais={availableAIs} selected={selectedAIs} onToggle={toggleAI} />
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end' }}>
              <div style={{ flex: 1 }}>
                <textarea
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleSubmit();
                    }
                  }}
                  placeholder="输入你的问题，让多个 AI 共同思考..."
                  rows={1}
                  style={{
                    width: '100%',
                    background: 'var(--bg-inset)',
                    border: '1px solid var(--border)',
                    borderRadius: 10,
                    padding: '11px 16px',
                    fontFamily: "'Source Serif 4', serif",
                    fontSize: 14,
                    color: 'var(--text-primary)',
                    resize: 'none',
                    outline: 'none',
                    minHeight: 44,
                    maxHeight: 110,
                    lineHeight: 1.5,
                  }}
                />
              </div>
              <button
                onClick={handleSubmit}
                disabled={!query.trim() || selectedAIs.length === 0 || isRunning}
                style={{
                  width: 44,
                  height: 44,
                  background: 'var(--accent)',
                  border: 'none',
                  borderRadius: 10,
                  color: 'var(--bg-deep)',
                  fontSize: 17,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                  opacity: !query.trim() || selectedAIs.length === 0 || isRunning ? 0.5 : 1,
                }}
              >
                ↑
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

const sbLabelStyle: React.CSSProperties = {
  fontFamily: "'DM Mono', monospace",
  fontSize: 10,
  color: 'var(--text-muted)',
  textTransform: 'uppercase',
  letterSpacing: 0.1,
  padding: '0 16px',
  margin: '12px 0 6px',
};
