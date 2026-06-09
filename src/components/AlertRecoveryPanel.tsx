interface Alert {
  platform: string;
  displayName: string;
  severity: 'critical' | 'warning' | 'info';
  message: string;
  state: string;
  waitingSince?: number;
  action?: 'login' | 'retry' | 'none';
}

interface AlertRecoveryPanelProps {
  alerts: Alert[];
  onLogin: (platform: string) => void;
}

export function AlertRecoveryPanel({ alerts, onLogin }: AlertRecoveryPanelProps) {
  if (alerts.length === 0) {
    return (
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 10,
          padding: 16,
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
          告警
        </div>
        <div
          style={{
            fontFamily: "'DM Mono', monospace",
            fontSize: 11,
            color: 'var(--text-muted)',
            textAlign: 'center',
            padding: '12px 0',
          }}
        >
          ✅ 无活跃告警
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        padding: 16,
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
        告警 ({alerts.length})
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {alerts.map((alert) => (
          <div
            key={alert.platform}
            style={{
              padding: '10px 14px',
              borderLeft: `3px solid ${
                alert.severity === 'critical'
                  ? 'var(--red)'
                  : alert.severity === 'warning'
                  ? 'var(--amber)'
                  : 'var(--blue)'
              }`,
              background:
                alert.severity === 'critical'
                  ? 'var(--red-glow)'
                  : alert.severity === 'warning'
                  ? 'var(--amber-glow)'
                  : 'var(--blue-glow)',
              borderRadius: '0 8px 8px 0',
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: 4,
              }}
            >
              <span
                style={{
                  fontFamily: "'Syne', sans-serif",
                  fontWeight: 700,
                  fontSize: 12,
                  color:
                    alert.severity === 'critical'
                      ? 'var(--red)'
                      : alert.severity === 'warning'
                      ? 'var(--amber)'
                      : 'var(--blue)',
                }}
              >
                {alert.severity === 'critical' ? '🔴' : alert.severity === 'warning' ? '🟡' : 'ℹ️'}{' '}
                {alert.displayName}
              </span>
              {alert.action === 'login' && (
                <button
                  onClick={() => onLogin(alert.platform)}
                  style={{
                    fontFamily: "'Syne', sans-serif",
                    fontSize: 10,
                    fontWeight: 600,
                    padding: '3px 10px',
                    borderRadius: 6,
                    border: '1px solid var(--accent-dim)',
                    background: 'var(--accent)',
                    color: '#0a0a0b',
                    cursor: 'pointer',
                  }}
                >
                  打开登录
                </button>
              )}
            </div>
            <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--text-secondary)' }}>
              {alert.message}
            </div>
            {alert.waitingSince && (
              <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, color: 'var(--text-muted)', marginTop: 4 }}>
                已等待 {Math.floor((Date.now() / 1000 - alert.waitingSince))}s
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
