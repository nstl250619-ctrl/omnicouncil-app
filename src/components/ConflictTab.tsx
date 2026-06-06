import { useState } from 'react';
import { useAppStore } from '../stores/appStore';

const AI_NAMES: Record<string, string> = {
  deepseek: 'DeepSeek',
  gemini: 'Gemini',
  qianwen: '千问',
  chatgpt: 'ChatGPT',
  mimo: 'MiMo',
};

const SEVERITY_COLORS: Record<string, string> = {
  critical: '#ef4444',
  significant: '#f59e0b',
  minor: '#3b82f6',
  negligible: '#888',
};

const SEVERITY_ICONS: Record<string, string> = {
  critical: '🔴',
  significant: '🟡',
  minor: '🔵',
  negligible: '⚪',
};

function ConflictFocusCard({ focus }: { focus: Record<string, unknown> }) {
  const [expanded, setExpanded] = useState(false);
  const severity = String(focus.severity || 'minor');
  const severityColor = SEVERITY_COLORS[severity] || '#888';
  const severityIcon = SEVERITY_ICONS[severity] || '⚪';
  const positions = (focus.positions as Array<Record<string, unknown>>) || [];
  const involvedAIs = (focus.involved_ais as string[]) || [];
  const intensity = (focus.conflict_intensity as number || 0) * 100;
  const suggestDebate = focus.suggest_debate as boolean;

  return (
    <div className="conflict-card" style={{ borderLeftColor: severityColor }}>
      <div className="conflict-card-header" onClick={() => setExpanded(!expanded)}>
        <div className="conflict-title">
          <span>{severityIcon}</span>
          <span>{String(focus.topic || '未命名冲突')}</span>
        </div>
        <div className="conflict-meta">
          <span className="conflict-severity" style={{ color: severityColor }}>
            {severity.toUpperCase()}
          </span>
          <span className="conflict-expand">{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      <div className="conflict-intensity">
        <span className="intensity-label">冲突强度</span>
        <div className="intensity-track">
          <div className="intensity-fill" style={{ width: `${intensity}%`, background: severityColor }} />
        </div>
        <span className="intensity-value">{intensity.toFixed(0)}%</span>
      </div>

      <div className="conflict-involved">
        <span className="involved-label">涉及AI:</span>
        {involvedAIs.map((ai, i) => (
          <span key={i} className="involved-ai">
            {AI_NAMES[ai] || ai}
          </span>
        ))}
      </div>

      {suggestDebate && (
        <div className="conflict-suggestion">
          🎯 建议进入辩论
        </div>
      )}

      {expanded && (
        <div className="conflict-positions">
          <h4>立场对比</h4>
          {positions.map((pos, i) => (
            <div key={i} className="position-card">
              <div className="position-header">
                <span className="position-ai" style={{ color: getAIColor(pos.ai_id as string) }}>
                  👤 {AI_NAMES[pos.ai_id as string] || pos.ai_id}
                </span>
              </div>
              <div className="position-summary">
                {String(pos.summary || '')}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function ConflictTab() {
  const conflict = useAppStore((s) => s.conflict);

  if (!conflict) {
    return (
      <div className="empty-state">
        <div className="empty-icon">⚔️</div>
        <div className="empty-title">等待冲突分析</div>
        <div className="empty-desc">对比分析完成后自动识别冲突</div>
      </div>
    );
  }

  const metrics = (conflict.metrics as Record<string, unknown>) || {};
  const conflictFocuses = (conflict.conflict_focuses as Array<Record<string, unknown>>) || [];
  const critical = conflictFocuses.filter((f) => f.severity === 'critical');
  const significant = conflictFocuses.filter((f) => f.severity === 'significant');
  const minor = conflictFocuses.filter((f) => f.severity === 'minor');

  return (
    <div className="conflict-view">
      {/* Summary */}
      <div className="conflict-summary-bar">
        <div className="summary-card">
          <span className="summary-icon">⚔️</span>
          <span className="summary-text">
            冲突点: <strong>{conflictFocuses.length}</strong>
          </span>
        </div>
        {critical.length > 0 && (
          <div className="summary-card critical">
            <span className="summary-icon">🔴</span>
            <span className="summary-text">
              严重: <strong>{critical.length}</strong>
            </span>
          </div>
        )}
        {significant.length > 0 && (
          <div className="summary-card significant">
            <span className="summary-icon">🟡</span>
            <span className="summary-text">
              中等: <strong>{significant.length}</strong>
            </span>
          </div>
        )}
        <div className="summary-card">
          <span className="summary-icon">📊</span>
          <span className="summary-text">
            整体等级: <strong>{String(metrics.overall_conflict_level || 'none')}</strong>
          </span>
        </div>
      </div>

      {/* Critical Conflicts */}
      {critical.length > 0 && (
        <div className="conflict-section">
          <h3 className="section-title">🔴 严重冲突</h3>
          {critical.map((focus, i) => (
            <ConflictFocusCard key={i} focus={focus} />
          ))}
        </div>
      )}

      {/* Significant Conflicts */}
      {significant.length > 0 && (
        <div className="conflict-section">
          <h3 className="section-title">🟡 中等冲突</h3>
          {significant.map((focus, i) => (
            <ConflictFocusCard key={i} focus={focus} />
          ))}
        </div>
      )}

      {/* Minor Conflicts */}
      {minor.length > 0 && (
        <div className="conflict-section">
          <h3 className="section-title">🔵 轻微冲突</h3>
          {minor.map((focus, i) => (
            <ConflictFocusCard key={i} focus={focus} />
          ))}
        </div>
      )}

      {/* No conflicts */}
      {conflictFocuses.length === 0 && (
        <div className="no-findings">
          🎉 未发现冲突点。所有AI的回答高度一致。
        </div>
      )}
    </div>
  );
}

function getAIColor(aiId: string): string {
  const colors: Record<string, string> = {
    deepseek: '#4f8fff',
    gemini: '#8b5cf6',
    qianwen: '#f59e0b',
    chatgpt: '#10a37f',
    mimo: '#ff6b6b',
  };
  return colors[aiId] || '#6366f1';
}
