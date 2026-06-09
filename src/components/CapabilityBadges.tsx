interface Capabilities {
  supports_streaming?: boolean;
  supports_file_upload?: boolean;
  supports_image?: boolean;
  max_input_chars?: number;
  response_format?: string;
  requires_chat_mode?: boolean;
}

interface CapabilityBadgesProps {
  capabilities: Capabilities | null;
}

export function CapabilityBadges({ capabilities }: CapabilityBadgesProps) {
  if (!capabilities) return null;

  const badges: { label: string; active: boolean }[] = [
    { label: '流式', active: capabilities.supports_streaming ?? true },
    { label: '文件', active: capabilities.supports_file_upload ?? false },
    { label: '图片', active: capabilities.supports_image ?? false },
  ];

  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
      {badges.map((b) => (
        <span
          key={b.label}
          style={{
            fontFamily: "'DM Mono', monospace",
            fontSize: 9,
            padding: '1px 6px',
            borderRadius: 8,
            background: b.active ? 'var(--accent-glow)' : 'rgba(255,255,255,0.03)',
            color: b.active ? 'var(--accent)' : 'var(--text-muted)',
            border: `1px solid ${b.active ? 'var(--accent-dim)' : 'var(--border-subtle)'}`,
          }}
        >
          {b.label}
        </span>
      ))}
      {capabilities.max_input_chars && (
        <span
          style={{
            fontFamily: "'DM Mono', monospace",
            fontSize: 9,
            padding: '1px 6px',
            borderRadius: 8,
            background: 'rgba(255,255,255,0.03)',
            color: 'var(--text-muted)',
            border: '1px solid var(--border-subtle)',
          }}
        >
          {Math.round(capabilities.max_input_chars / 1000)}k
        </span>
      )}
    </div>
  );
}
