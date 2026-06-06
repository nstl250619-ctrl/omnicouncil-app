import { useState } from 'react';
import { useAppStore } from '../stores/appStore';

const AI_NAMES: Record<string, string> = {
  deepseek: 'DeepSeek',
  gemini: 'Gemini',
  qianwen: '千问',
  chatgpt: 'ChatGPT',
  mimo: 'MiMo',
};

function ConsensusPointCard({ point }: { point: Record<string, unknown> }) {
  const [expanded, setExpanded] = useState(false);
  const confidence = String(point.confidence || 'low');
  const confidenceColor = confidence === 'high' ? '#22c55e' : confidence === 'medium' ? '#f59e0b' : '#888';
  const strength = (point.consensus_strength as number || 0) * 100;
  const coverage = (point.coverage as number || 0) * 100;
  const supportingAIs = (point.supporting_ais as string[]) || [];

  return (
    <div className="consensus-card">
      <div className="consensus-card-header" onClick={() => setExpanded(!expanded)}>
        <div className="consensus-title">
          <span className="consensus-icon">🏆</span>
          <span>{String(point.topic || '未命名共识')}</span>
        </div>
        <div className="consensus-meta">
          <span className="consensus-confidence" style={{ color: confidenceColor }}>
            {confidence.toUpperCase()}
          </span>
          <span className="consensus-expand">{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      <div className="consensus-strength-bar">
        <div className="strength-label">共识强度</div>
        <div className="strength-track">
          <div className="strength-fill" style={{ width: `${strength}%`, background: confidenceColor }} />
        </div>
        <span className="strength-value">{strength.toFixed(0)}%</span>
      </div>

      <div className="consensus-summary">
        {String(point.summary || '')}
      </div>

      <div className="consensus-support">
        <span className="support-label">支持AI:</span>
        <div className="support-ais">
          {supportingAIs.map((ai, i) => (
            <span key={i} className="support-ai" style={{ color: getAIColor(ai) }}>
              ✓ {AI_NAMES[ai] || ai}
            </span>
          ))}
        </div>
        <span className="coverage">覆盖率: {coverage.toFixed(0)}%</span>
      </div>

      {expanded && (
        <div className="consensus-details">
          <div className="consensus-distribution">
            <h4>支持分布</h4>
            <div className="distribution-grid">
              {supportingAIs.map((ai, i) => (
                <div key={i} className="distribution-item">
                  <span className="dist-ai">{AI_NAMES[ai] || ai}</span>
                  <div className="dist-bar" style={{ background: getAIColor(ai) }} />
                  <span className="dist-check">✓</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function ConsensusTab() {
  const consensus = useAppStore((s) => s.consensus);

  if (!consensus) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🤝</div>
        <div className="empty-title">等待共识分析</div>
        <div className="empty-desc">对比分析完成后自动提取共识</div>
      </div>
    );
  }

  const metrics = (consensus.metrics as Record<string, unknown>) || {};
  const consensusPoints = (consensus.consensus_points as Array<Record<string, unknown>>) || [];
  const highConfidence = consensusPoints.filter((p) => p.confidence === 'high');
  const mediumConfidence = consensusPoints.filter((p) => p.confidence === 'medium');
  const lowConfidence = consensusPoints.filter((p) => p.confidence === 'low');

  return (
    <div className="consensus-view">
      {/* Summary */}
      <div className="consensus-summary-bar">
        <div className="summary-card">
          <span className="summary-icon">🤝</span>
          <span className="summary-text">
            共识点: <strong>{consensusPoints.length}</strong>
          </span>
        </div>
        <div className="summary-card">
          <span className="summary-icon">📊</span>
          <span className="summary-text">
            全局共识指数: <strong>{((metrics.global_consensus_index as number || 0) * 100).toFixed(0)}%</strong>
          </span>
        </div>
        <div className="summary-card">
          <span className="summary-icon">📈</span>
          <span className="summary-text">
            覆盖率: <strong>{((metrics.unit_coverage_ratio as number || 0) * 100).toFixed(0)}%</strong>
          </span>
        </div>
      </div>

      {/* High Confidence */}
      {highConfidence.length > 0 && (
        <div className="consensus-section">
          <h3 className="section-title">🤝 高置信共识</h3>
          {highConfidence.map((point, i) => (
            <ConsensusPointCard key={i} point={point} />
          ))}
        </div>
      )}

      {/* Medium Confidence */}
      {mediumConfidence.length > 0 && (
        <div className="consensus-section">
          <h3 className="section-title">⚠️ 中置信共识</h3>
          {mediumConfidence.map((point, i) => (
            <ConsensusPointCard key={i} point={point} />
          ))}
        </div>
      )}

      {/* Low Confidence */}
      {lowConfidence.length > 0 && (
        <div className="consensus-section">
          <h3 className="section-title">❓ 低置信共识</h3>
          {lowConfidence.map((point, i) => (
            <ConsensusPointCard key={i} point={point} />
          ))}
        </div>
      )}

      {/* No consensus */}
      {consensusPoints.length === 0 && (
        <div className="no-findings">
          未发现共识点。各AI的回答差异较大。
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
