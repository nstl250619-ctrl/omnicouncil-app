import { useState, useEffect, useCallback } from 'react';

const API_BASE = 'http://localhost:8765';

interface HistoryEntry {
  task_id: string;
  query: string;
  ai_ids: string[];
  completed_at: number;
  saved_at: number;
  summary: {
    total_ais: number;
    success_count: number;
    consensus_count: number;
    conflict_count: number;
  };
}

interface FullSession {
  task_id: string;
  query: string;
  ai_ids: string[];
  responses: Record<string, { content: string; status: string; elapsed_ms: number }>;
  comparison?: Record<string, unknown>;
  consensus?: Record<string, unknown>;
  conflict?: Record<string, unknown>;
  completed_at: number;
  saved_at: number;
}

const AI_NAMES: Record<string, string> = {
  deepseek: 'DeepSeek',
  gemini: 'Gemini',
  qianwen: '千问',
  chatgpt: 'ChatGPT',
  mimo: 'MiMo',
};

function formatDate(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  });
}

export function HistoryView() {
  const [sessions, setSessions] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [fullSession, setFullSession] = useState<FullSession | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const fetchSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/sessions?limit=50`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSessions(data.sessions || []);
    } catch (e) {
      console.error('Failed to fetch sessions:', e);
      setError('无法加载历史记录');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  const loadSessionDetail = async (taskId: string) => {
    setSelectedSessionId(taskId);
    setLoadingDetail(true);
    setFullSession(null);
    try {
      const res = await fetch(`${API_BASE}/api/sessions/${taskId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setFullSession(data as FullSession);
    } catch (e) {
      console.error('Failed to load session detail:', e);
      setError('无法加载会话详情');
    } finally {
      setLoadingDetail(false);
    }
  };

  const deleteSession = async (taskId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/sessions/${taskId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSessions((prev) => prev.filter((s) => s.task_id !== taskId));
      if (selectedSessionId === taskId) {
        setSelectedSessionId(null);
        setFullSession(null);
      }
    } catch (e) {
      console.error('Failed to delete session:', e);
    }
  };

  const clearAllSessions = async () => {
    if (!confirm('确定要清除所有历史记录吗？')) return;
    try {
      const res = await fetch(`${API_BASE}/api/sessions`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSessions([]);
      setSelectedSessionId(null);
      setFullSession(null);
    } catch (e) {
      console.error('Failed to clear sessions:', e);
    }
  };

  const filtered = sessions.filter((s) =>
    s.query.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Detail view
  if (selectedSessionId !== null) {
    return (
      <div className="history-view">
        <div className="history-header">
          <button className="history-back-btn" onClick={() => { setSelectedSessionId(null); setFullSession(null); }}>
            ← 返回列表
          </button>
          <h3>会话详情</h3>
        </div>
        {loadingDetail && (
          <div className="empty-state">
            <div className="empty-icon">⏳</div>
            <div className="empty-title">加载中...</div>
          </div>
        )}
        {fullSession && (
          <div className="session-detail">
            <div className="session-detail-card">
              <div className="session-detail-query">💬 {fullSession.query}</div>
              <div className="session-detail-meta">
                <span>📅 {formatDate(fullSession.completed_at || fullSession.saved_at)}</span>
                <span>🤖 {fullSession.ai_ids.map((id) => AI_NAMES[id] || id).join(' + ')}</span>
              </div>
            </div>
            {fullSession.responses && Object.entries(fullSession.responses).map(([aiId, resp]) => (
              <div key={aiId} className="session-response-card">
                <div className="session-response-header">
                  <strong>{AI_NAMES[aiId] || aiId}</strong>
                  <span className="session-response-meta">
                    {resp.status === 'completed' ? '✅ ' : '❌ '}
                    {resp.elapsed_ms ? `${(resp.elapsed_ms / 1000).toFixed(1)}秒` : ''}
                  </span>
                </div>
                <div className="session-response-content markdown-body">
                  {resp.content?.substring(0, 1000)}
                  {(resp.content?.length || 0) > 1000 ? '...' : ''}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  // List view
  return (
    <div className="history-view">
      <div className="history-header">
        <div className="history-search">
          <input
            type="text"
            placeholder="搜索历史记录..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="history-search-input"
          />
        </div>
        {sessions.length > 0 && (
          <button className="history-clear-btn" onClick={clearAllSessions}>
            清除全部
          </button>
        )}
      </div>

      {loading && (
        <div className="empty-state">
          <div className="empty-icon">⏳</div>
          <div className="empty-title">加载历史记录...</div>
        </div>
      )}

      {error && (
        <div className="empty-state">
          <div className="empty-icon">❌</div>
          <div className="empty-title">{error}</div>
          <div className="empty-desc">请确保后端服务正在运行</div>
          <button className="history-btn" onClick={fetchSessions} style={{ marginTop: '12px' }}>
            重试
          </button>
        </div>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className="empty-state">
          <div className="empty-icon">📚</div>
          <div className="empty-title">暂无历史记录</div>
          <div className="empty-desc">完成一次分析后，历史记录会自动保存</div>
        </div>
      )}

      <div className="history-list">
        {filtered.map((entry) => (
          <div key={entry.task_id} className="history-card" onClick={() => loadSessionDetail(entry.task_id)}>
            <div className="history-date">📅 {formatDate(entry.completed_at || entry.saved_at)}</div>
            <div className="history-query">💬 {entry.query}</div>
            <div className="history-ais">
              🤖 {entry.ai_ids.map((id) => AI_NAMES[id] || id).join(' + ')}
            </div>
            <div className="history-stats">
              📊 共识: {entry.summary?.consensus_count ?? 0} · 冲突: {entry.summary?.conflict_count ?? 0} · 成功率: {entry.summary?.total_ais ? Math.round((entry.summary.success_count / entry.summary.total_ais) * 100) : 0}%
            </div>
            <div className="history-actions">
              <button className="history-btn" onClick={(e) => { e.stopPropagation(); loadSessionDetail(entry.task_id); }}>
                查看
              </button>
              <button
                className="history-btn-delete"
                onClick={(e) => { e.stopPropagation(); deleteSession(entry.task_id); }}
              >
                删除
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
