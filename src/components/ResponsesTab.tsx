import { useAppStore, AIResponseState } from '../stores/appStore';
import ReactMarkdown from 'react-markdown';

const STATUS_ICONS: Record<string, string> = {
  idle: '⚪',
  waiting: '🔄',
  streaming: '⏳',
  completed: '✅',
  error: '❌',
};

const STATUS_LABELS: Record<string, string> = {
  idle: '空闲',
  waiting: '等待中',
  streaming: '生成中...',
  completed: '已完成',
  error: '失败',
};

const AI_COLORS: Record<string, string> = {
  deepseek: '#4f8fff',
  gemini: '#8b5cf6',
  qianwen: '#f59e0b',
};

function ResponseCard({ aiId, response }: { aiId: string; response: AIResponseState }) {
  const color = AI_COLORS[aiId] || '#6366f1';

  return (
    <div className="response-card" style={{ borderTopColor: color }}>
      <div className="card-header">
        <span className="card-ai-name" style={{ color }}>
          🤖 {aiId.toUpperCase()}
        </span>
        <span className={`card-status status-${response.status}`}>
          {STATUS_ICONS[response.status]} {STATUS_LABELS[response.status]}
          {response.wordCount && ` · ${response.wordCount}字`}
          {response.elapsedMs && ` · ${(response.elapsedMs / 1000).toFixed(1)}秒`}
        </span>
      </div>
      <div className="card-content">
        {response.status === 'waiting' && (
          <div className="card-placeholder">
            <div className="spinner" />
            <span>等待AI回复...</span>
          </div>
        )}
        {response.status === 'streaming' && (
          <div className="card-streaming">
            <ReactMarkdown>{response.content || '思考中...'}</ReactMarkdown>
            <span className="cursor">|</span>
          </div>
        )}
        {response.status === 'completed' && (
          <div className="card-completed">
            <ReactMarkdown>{response.content}</ReactMarkdown>
          </div>
        )}
        {response.status === 'error' && (
          <div className="card-error">
            <span>❌ {response.error}</span>
            <button className="retry-btn">重试</button>
          </div>
        )}
      </div>
    </div>
  );
}

export function ResponsesTab() {
  const responses = useAppStore((s) => s.responses);
  const aiIds = Object.keys(responses);

  if (aiIds.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🤖</div>
        <div className="empty-title">等待提问</div>
        <div className="empty-desc">输入问题并选择AI模型，开始分析</div>
      </div>
    );
  }

  return (
    <div className="responses-grid">
      {aiIds.map((aiId) => (
        <ResponseCard key={aiId} aiId={aiId} response={responses[aiId]} />
      ))}
    </div>
  );
}
