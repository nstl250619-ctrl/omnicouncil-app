import { useState } from 'react';

interface HistoryEntry {
  id: string;
  date: string;
  query: string;
  aiNames: string[];
  consensusCount: number;
  conflictCount: number;
  divergence: number;
}

const MOCK_HISTORY: HistoryEntry[] = [];

export function HistoryView() {
  const [searchQuery, setSearchQuery] = useState('');
  const history = MOCK_HISTORY; // Will be replaced with real data from backend

  const filteredHistory = history.filter(
    (entry) => entry.query.toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (history.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon">📚</div>
        <div className="empty-title">暂无历史记录</div>
        <div className="empty-desc">完成一次分析后，历史记录会自动保存</div>
      </div>
    );
  }

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
        <button className="history-clear-btn">清除全部</button>
      </div>

      <div className="history-list">
        {filteredHistory.map((entry) => (
          <div key={entry.id} className="history-card">
            <div className="history-date">📅 {entry.date}</div>
            <div className="history-query">💬 {entry.query}</div>
            <div className="history-ais">
              🤖 {entry.aiNames.join(' + ')}
            </div>
            <div className="history-stats">
              📊 共识: {entry.consensusCount} · 冲突: {entry.conflictCount} · 分歧: {entry.divergence}%
            </div>
            <div className="history-actions">
              <button className="history-btn">查看</button>
              <button className="history-btn">重新分析</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
