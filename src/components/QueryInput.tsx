import { useState, useMemo } from 'react';
import { useAppStore } from '../stores/appStore';
import { useWebSocket } from '../hooks/useWebSocket';

const AI_COLORS: Record<string, string> = {
  deepseek: '#4f8fff',
  gemini: '#8b5cf6',
  qianwen: '#f59e0b',
  chatgpt: '#10a37f',
  mimo: '#ff6b6b',
};

export function QueryInput() {
  const [query, setQuery] = useState('');
  const [selectedAIs, setSelectedAIs] = useState<string[]>(['deepseek', 'qianwen']);
  const { send } = useWebSocket();
  const aiList = useAppStore((s) => s.aiList);
  const submitQuery = useAppStore((s) => s.submitQuery);
  const responses = useAppStore((s) => s.responses);
  const isRunning = Object.values(responses).some((r) => r.status === 'waiting' || r.status === 'streaming');

  // Use backend's aiList (filtered to enabled AIs) with fallback
  const availableAIs = useMemo(() => {
    if (aiList.length > 0) {
      return aiList
        .filter((ai) => ai.enabled)
        .map((ai) => ({
          id: ai.provider_id,
          name: ai.display_name,
          color: ai.icon_color || AI_COLORS[ai.provider_id] || '#6366f1',
        }));
    }
    // Fallback if backend hasn't sent ai_list yet
    return [
      { id: 'deepseek', name: 'DeepSeek', color: '#4f8fff' },
      { id: 'qianwen', name: '千问', color: '#f59e0b' },
      { id: 'gemini', name: 'Gemini', color: '#8b5cf6' },
      { id: 'chatgpt', name: 'ChatGPT', color: '#10a37f' },
      { id: 'mimo', name: 'MiMo', color: '#ff6b6b' },
    ];
  }, [aiList]);

  const toggleAI = (aiId: string) => {
    setSelectedAIs((prev) =>
      prev.includes(aiId) ? prev.filter((id) => id !== aiId) : [...prev, aiId]
    );
  };

  const handleSubmit = () => {
    if (!query.trim() || selectedAIs.length === 0 || isRunning) return;
    submitQuery(query, selectedAIs);
    send('submit_query', { query, ai_ids: selectedAIs, mode: 'parallel' });
  };

  return (
    <div className="query-input">
      <textarea
        className="query-textarea"
        placeholder="输入你的问题，让多个AI共同思考..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit();
        }}
      />
      <div className="query-controls">
        <div className="ai-selector">
          {availableAIs.map((ai) => (
            <button
              key={ai.id}
              className={`ai-chip ${selectedAIs.includes(ai.id) ? 'selected' : ''}`}
              style={selectedAIs.includes(ai.id) ? { borderColor: ai.color, background: ai.color + '20' } : {}}
              onClick={() => toggleAI(ai.id)}
            >
              {ai.name}
            </button>
          ))}
        </div>
        <button
          className="submit-btn"
          onClick={handleSubmit}
          disabled={!query.trim() || selectedAIs.length === 0 || isRunning}
        >
          {isRunning ? '⏳ 分析中...' : '🚀 开始分析'}
        </button>
      </div>
    </div>
  );
}
