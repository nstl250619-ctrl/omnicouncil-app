import { SessionLifecycleBadge } from './SessionLifecycleBadge';
import { SelectorHealthBadge } from './SelectorHealthBadge';
import { CapabilityBadges } from './CapabilityBadges';

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
  capabilities?: {
    supports_streaming?: boolean;
    supports_file_upload?: boolean;
    supports_image?: boolean;
    max_input_chars?: number;
  };
}

interface ProviderStatusCardProps {
  provider: ProviderHealth;
  displayName: string;
  iconColor: string;
  iconShort: string;
  hasAlert: boolean;
  onClick: () => void;
}

export function ProviderStatusCard({
  provider,
  displayName,
  iconColor,
  iconShort,
  hasAlert,
  onClick,
}: ProviderStatusCardProps) {
  const stateColor =
    provider.state === 'healthy'
      ? 'var(--green)'
      : provider.state === 'degraded'
      ? 'var(--amber)'
      : provider.state === 'login_required'
      ? 'var(--red)'
      : provider.state === 'unavailable'
      ? 'var(--red)'
      : 'var(--text-muted)';

  return (
    <div
      onClick={onClick}
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        padding: 16,
        cursor: 'pointer',
        transition: 'all 0.2s',
        position: 'relative',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'var(--border-subtle)';
        e.currentTarget.style.transform = 'translateY(-1px)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'var(--border)';
        e.currentTarget.style.transform = 'translateY(0)';
      }}
    >
      {/* Alert badge */}
      {hasAlert && (
        <div
          style={{
            position: 'absolute',
            top: 8,
            right: 8,
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: 'var(--red)',
            boxShadow: '0 0 6px var(--red)',
          }}
        />
      )}

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: iconColor,
            fontFamily: "'Syne', sans-serif",
            fontWeight: 700,
            fontSize: 12,
            color: '#fff',
          }}
        >
          {iconShort}
        </div>
        <div>
          <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 14 }}>
            {displayName}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2 }}>
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: stateColor,
                boxShadow: stateColor !== 'var(--text-muted)' ? `0 0 6px ${stateColor}` : 'none',
              }}
            />
            <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: 'var(--text-secondary)' }}>
              {provider.state}
            </span>
          </div>
        </div>
      </div>

      {/* Lifecycle badge */}
      {provider.lifecycle_state && (
        <div style={{ marginBottom: 8 }}>
          <SessionLifecycleBadge state={provider.lifecycle_state} />
        </div>
      )}

      {/* Selector health */}
      <div style={{ marginBottom: 8 }}>
        <SelectorHealthBadge
          degraded={provider.selector_degraded ?? false}
          degradedCount={provider.selector_degraded_count ?? 0}
        />
      </div>

      {/* Capabilities */}
      {provider.capabilities && (
        <div style={{ marginBottom: 8 }}>
          <CapabilityBadges capabilities={provider.capabilities} />
        </div>
      )}

      {/* Footer stats */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontFamily: "'DM Mono', monospace",
          fontSize: 10,
          color: 'var(--text-muted)',
          borderTop: '1px solid var(--border-subtle)',
          paddingTop: 8,
          marginTop: 4,
        }}
      >
        <span>恢复: {provider.recovery_attempts}</span>
        <span>
          {provider.last_heartbeat > 0
            ? `${Math.floor(Date.now() / 1000 - provider.last_heartbeat)}s ago`
            : '--'}
        </span>
      </div>
    </div>
  );
}
