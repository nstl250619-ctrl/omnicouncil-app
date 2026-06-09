interface MetricsSummaryProps {
  metrics: Record<string, Record<string, number>> | null;
}

export function MetricsSummary({ metrics }: MetricsSummaryProps) {
  if (!metrics || Object.keys(metrics).length === 0) {
    return (
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 10,
          padding: 16,
          fontFamily: "'DM Mono', monospace",
          fontSize: 11,
          color: 'var(--text-muted)',
          textAlign: 'center',
        }}
      >
        暂无运行指标
      </div>
    );
  }

  // Aggregate across all platforms
  let totalQueries = 0;
  let totalSucceeded = 0;
  let totalFailed = 0;
  let totalRecoveryStarted = 0;
  let totalRecoverySucceeded = 0;
  let totalEvictions = 0;
  let totalLeases = 0;

  for (const m of Object.values(metrics)) {
    totalQueries += m.query_total ?? 0;
    totalSucceeded += m.query_succeeded ?? 0;
    totalFailed += m.query_failed ?? 0;
    totalRecoveryStarted += m.recovery_started ?? 0;
    totalRecoverySucceeded += m.recovery_succeeded ?? 0;
    totalEvictions += m.eviction_completed ?? 0;
    totalLeases += m.page_lease_acquired ?? 0;
  }

  const items = [
    { label: '查询', value: totalQueries, color: 'var(--accent)' },
    { label: '成功', value: totalSucceeded, color: 'var(--green)' },
    { label: '失败', value: totalFailed, color: totalFailed > 0 ? 'var(--red)' : 'var(--text-muted)' },
    { label: '恢复', value: totalRecoverySucceeded, color: 'var(--blue)' },
    { label: 'Eviction', value: totalEvictions, color: 'var(--amber)' },
    { label: '租约', value: totalLeases, color: 'var(--text-secondary)' },
  ];

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
        运行指标
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
        {items.map((item) => (
          <div key={item.label} style={{ textAlign: 'center' }}>
            <div
              style={{
                fontFamily: "'Syne', sans-serif",
                fontWeight: 800,
                fontSize: 20,
                color: item.color,
              }}
            >
              {item.value}
            </div>
            <div
              style={{
                fontFamily: "'DM Mono', monospace",
                fontSize: 10,
                color: 'var(--text-muted)',
                marginTop: 2,
              }}
            >
              {item.label}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
