import { useState } from 'react';
import { useAppStore } from '../stores/appStore';
import { useWebSocket } from '../hooks/useWebSocket';

const AVAILABLE_AIS = [
  { id: 'deepseek', name: 'DeepSeek', color: '#4f8fff' },
  { id: 'gemini', name: 'Gemini', color: '#8b5cf6' },
  { id: 'qianwen', name: '千问', color: '#f59e0b' },
];

export function QueryInput() {
  const [query, setQuery] = useState('');
  const [selectedAIs, setSelectedAIs] = useState<string[]>(['deepseek', 'qianwen']);
  const { send } = useWebSocket();
  const submitQuery = useAppStore((s) => s.submitQuery);
  const responses = useAppStore((s) => s.responses);
  const isRunning = Object.values(responses).some((r) => r.status === 'waiting' || r.status === 'streaming');

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
          {AVAILABLE_AIS.map((ai) => (
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
