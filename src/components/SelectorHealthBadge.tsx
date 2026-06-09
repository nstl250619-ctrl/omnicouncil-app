interface SelectorHealthBadgeProps {
  degraded: boolean;
  degradedCount: number;
}

export function SelectorHealthBadge({ degraded, degradedCount }: SelectorHealthBadgeProps) {
  if (!degraded) {
    return (
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          fontFamily: "'DM Mono', monospace",
          fontSize: 10,
          padding: '2px 8px',
          borderRadius: 12,
          background: 'var(--green-glow)',
          color: 'var(--green)',
          border: '1px solid rgba(62,207,142,0.2)',
        }}
      >
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--green)' }} />
        选择器正常
      </span>
    );
  }

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        fontFamily: "'DM Mono', monospace",
        fontSize: 10,
        padding: '2px 8px',
        borderRadius: 12,
        background: 'var(--amber-glow)',
        color: 'var(--amber)',
        border: '1px solid rgba(245,158,11,0.2)',
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--amber)' }} />
      选择器降级 ({degradedCount})
    </span>
  );
}
