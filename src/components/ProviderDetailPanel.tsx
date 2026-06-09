import { SessionLifecycleBadge } from './SessionLifecycleBadge';
import { SelectorHealthBadge } from './SelectorHealthBadge';
import { CapabilityBadges } from './CapabilityBadges';
import { MetricsSummary } from './MetricsSummary';

interface ProviderHealth {
  platform: string;
  state: string;
  browser_alive: boolean;
  page_alive: boolean;
  session_valid: boolean;
  last_heartbeat: number;
  recovery_attempts: number;
  uptime_seconds: number;
  lifecycle_state?: string;
  selector_degraded?: boolean;
  selector_degraded_count?: number;
  capabilities?: Record<string, unknown>;
  metrics?: Record<string, number>;
}

interface ProviderDetailPanelProps {
  provider: ProviderHealth;
  displayName: string;
  onBack: () => void;
  onLogin: (platform: string) => void;
}

export function ProviderDetailPanel({
  provider,
  displayName,
  onBack,
  onLogin,
}: ProviderDetailPanelProps) {
  const stateColor =
    provider.state === 'healthy'
      ? 'var(--green)'
      : provider.state === 'degraded'
      ? 'var(--amber)'
      : 'var(--red)';

  const uptimeStr =
    provider.uptime_seconds > 3600
      ? `${Math.floor(provider.uptime_seconds / 3600)}h${Math.floor((provider.uptime_seconds % 3600) / 60)}m`
      : provider.uptime_seconds > 60
      ? `${Math.floor(provider.uptime_seconds / 60)}m`
      : `${Math.floor(provider.uptime_seconds)}s`;

  return (
    <div>
      {/* Back button */}
      <button
        onClick={onBack}
        style={{
          fontFamily: "'Syne', sans-serif",
          fontSize: 12,
          fontWeight: 600,
          color: 'var(--text-muted)',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          marginBottom: 16,
          padding: 0,
        }}
      >
        ← 返回 Dashboard
      </button>

      {/* Header */}
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 10,
          padding: 20,
          marginBottom: 16,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div>
            <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 800, fontSize: 20 }}>
              {displayName} 详情
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: stateColor, boxShadow: `0 0 8px ${stateColor}` }} />
              <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 13, color: 'var(--text-secondary)' }}>
                {provider.state.toUpperCase()}
              </span>
              {provider.lifecycle_state && <SessionLifecycleBadge state={provider.lifecycle_state} />}
            </div>
          </div>
          <button
            onClick={() => onLogin(provider.platform)}
            style={{
              fontFamily: "'Syne', sans-serif",
              fontSize: 12,
              fontWeight: 600,
              padding: '8px 16px',
              borderRadius: 8,
              border: '1px solid var(--accent-dim)',
              background: 'var(--accent)',
              color: '#0a0a0b',
              cursor: 'pointer',
            }}
          >
            恢复 / 登录
          </button>
        </div>

        {/* Status grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {[
            { label: '浏览器', value: provider.browser_alive ? '存活' : '关闭', ok: provider.browser_alive },
            { label: '页面', value: provider.page_alive ? '存活' : '关闭', ok: provider.page_alive },
            { label: 'Session', value: provider.session_valid ? '有效' : '无效', ok: provider.session_valid },
            { label: '恢复次数', value: String(provider.recovery_attempts), ok: provider.recovery_attempts === 0 },
          ].map((item) => (
            <div key={item.label} style={{ textAlign: 'center', padding: '8px 0' }}>
              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
                {item.label}
              </div>
              <div
                style={{
                  fontFamily: "'Syne', sans-serif",
                  fontWeight: 700,
                  fontSize: 14,
                  color: item.ok ? 'var(--green)' : 'var(--red)',
                }}
              >
                {item.value}
              </div>
            </div>
          ))}
        </div>

        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontFamily: "'DM Mono', monospace",
            fontSize: 10,
            color: 'var(--text-muted)',
            borderTop: '1px solid var(--border-subtle)',
            paddingTop: 10,
            marginTop: 12,
          }}
        >
          <span>运行时间: {uptimeStr}</span>
          <span>
            最后心跳: {provider.last_heartbeat > 0 ? `${Math.floor(Date.now() / 1000 - provider.last_heartbeat)}s ago` : '--'}
          </span>
        </div>
      </div>

      {/* Selector health */}
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 10,
          padding: 16,
          marginBottom: 16,
        }}
      >
        <div
          style={{
            fontFamily: "'DM Mono', monospace",
            fontSize: 10,
            color: 'var(--text-muted)',
            textTransform: 'uppercase',
            letterSpacing: 0.08,
            marginBottom: 12,
          }}
        >
          选择器健康
        </div>
        <SelectorHealthBadge
          degraded={provider.selector_degraded ?? false}
          degradedCount={provider.selector_degraded_count ?? 0}
        />
      </div>

      {/* Metrics */}
      {provider.metrics && (
        <MetricsSummary metrics={{ [provider.platform]: provider.metrics }} />
      )}
    </div>
  );
}
