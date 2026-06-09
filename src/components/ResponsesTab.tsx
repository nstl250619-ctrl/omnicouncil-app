import { useState } from 'react';
import { useAppStore, AIResponseState } from '../stores/appStore';
import { useWebSocket } from '../hooks/useWebSocket';
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
  deepseek: '#4F8FFF',
  gemini: '#A78BFA',
  qianwen: '#F59E0B',
  chatgpt: '#10A37F',
  mimo: '#FF6B6B',
};

const AI_NAMES: Record<string, string> = {
  deepseek: 'DeepSeek',
  gemini: 'Gemini',
  qianwen: '千问',
  chatgpt: 'ChatGPT',
  mimo: 'MiMo',
};

function ResponseCard({ aiId, response, onRetry }: { aiId: string; response: AIResponseState; onRetry?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const color = AI_COLORS[aiId] || '#6366f1';
  const name = AI_NAMES[aiId] || aiId.toUpperCase();
  const contentLength = (response.content || '').length;
  const shouldTruncate = contentLength > 500 && !expanded;

  return (
    <div className="response-card" style={{ borderTopColor: color }}>
      <div className="card-header">
        <div className="card-header-left">
          <span className="card-ai-name" style={{ color }}>
            🤖 {name}
          </span>
          <span className={`card-status status-${response.status}`}>
            {STATUS_ICONS[response.status]} {STATUS_LABELS[response.status]}
          </span>
        </div>
        <div className="card-header-right">
          {response.wordCount && <span className="card-meta">{response.wordCount}字</span>}
          {response.elapsedMs && <span className="card-meta">{(response.elapsedMs / 1000).toFixed(1)}秒</span>}
        </div>
      </div>

      <div className={`card-content ${shouldTruncate ? 'truncated' : ''}`}>
        {response.status === 'idle' && (
          <div className="card-placeholder">
            <span className="placeholder-text">等待发送...</span>
          </div>
        )}

        {response.status === 'waiting' && (
          <div className="card-placeholder">
            <div className="pulse-loader">
              <div className="pulse-dot" style={{ background: color }} />
              <div className="pulse-dot" style={{ background: color }} />
              <div className="pulse-dot" style={{ background: color }} />
            </div>
            <span className="placeholder-text">等待AI回复...</span>
          </div>
        )}

        {response.status === 'streaming' && (
          <div className="card-streaming">
            <div className="markdown-body" dangerouslySetInnerHTML={{ __html: response.content || '思考中...' }} />
            <span className="cursor" style={{ color }}>▊</span>
          </div>
        )}

        {response.status === 'completed' && (
          <div className="card-completed">
            <div className="markdown-body" dangerouslySetInnerHTML={{ __html: response.content }} />
          </div>
        )}

        {response.status === 'error' && (
          <div className="card-error">
            <div className="error-icon">❌</div>
            <div className="error-message">{response.error}</div>
            <button className="retry-btn" style={{ borderColor: color }} onClick={onRetry}>
              重试
            </button>
          </div>
        )}
      </div>

      {contentLength > 500 && (
        <button className="card-expand-btn" onClick={() => setExpanded(!expanded)}>
          {expanded ? '收起 ▲' : '展开全文 ▼'}
        </button>
      )}
    </div>
  );
}

export function ResponsesTab() {
  const responses = useAppStore((s) => s.responses);
  const aiIds = Object.keys(responses);
  const { send } = useWebSocket();

  if (aiIds.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🤖</div>
        <div className="empty-title">等待提问</div>
        <div className="empty-desc">输入问题并选择AI模型，点击"开始分析"</div>
      </div>
    );
  }

  return (
    <div className="responses-grid">
      {aiIds.map((aiId) => (
        <ResponseCard
          key={aiId}
          aiId={aiId}
          response={responses[aiId]}
          onRetry={() => send('reauth', { ai_id: aiId })}
        />
      ))}
    </div>
  );
}
