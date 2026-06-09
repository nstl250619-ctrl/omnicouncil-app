interface SessionLifecycleBadgeProps {
  state: string;
}

const STATE_CONFIG: Record<string, { label: string; color: string; glow: string; pulse: boolean }> = {
  valid:               { label: '有效',   color: 'var(--green)',  glow: 'var(--green-glow)',  pulse: false },
  expiring:            { label: '即将过期', color: 'var(--amber)',  glow: 'var(--amber-glow)',  pulse: true },
  refreshing:          { label: '刷新中',  color: 'var(--blue)',   glow: 'var(--blue-glow)',   pulse: true },
  expired:             { label: '已过期',  color: 'var(--red)',    glow: 'var(--red-glow)',    pulse: false },
  login_required:      { label: '需登录',  color: 'var(--red)',    glow: 'var(--red-glow)',    pulse: false },
  recovery_pending:    { label: '等待恢复', color: 'var(--amber)',  glow: 'var(--amber-glow)',  pulse: true },
  recovery_in_progress:{ label: '恢复中',  color: 'var(--blue)',   glow: 'var(--blue-glow)',   pulse: true },
  unknown:             { label: '未知',   color: 'var(--text-muted)', glow: 'transparent',    pulse: false },
};

export function SessionLifecycleBadge({ state }: SessionLifecycleBadgeProps) {
  const cfg = STATE_CONFIG[state] ?? STATE_CONFIG.unknown;
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        fontFamily: "'DM Mono', monospace",
        fontSize: 10,
        padding: '2px 8px',
        borderRadius: 12,
        background: cfg.glow,
        color: cfg.color,
        border: `1px solid ${cfg.color}30`,
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: cfg.color,
          boxShadow: cfg.pulse ? `0 0 6px ${cfg.color}` : 'none',
          animation: cfg.pulse ? 'pulse 1.5s ease-in-out infinite' : 'none',
        }}
      />
      {cfg.label}
    </span>
  );
}
