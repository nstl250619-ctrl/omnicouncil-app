interface AIIconSelectorProps {
  ais: Array<{ id: string; name: string; connected: boolean }>;
  selected: string[];
  onToggle: (id: string) => void;
}

const AI_ICON_STYLES: Record<string, { gradient: string; short: string }> = {
  deepseek:   { gradient: 'linear-gradient(135deg,#4d7cfe,#3b5bdb)', short: 'DS' },
  gemini:     { gradient: 'linear-gradient(135deg,#8b5cf6,#6d28d9)', short: 'Ge' },
  chatgpt:    { gradient: 'linear-gradient(135deg,#10b981,#059669)', short: 'Gt' },
  qianwen:    { gradient: 'linear-gradient(135deg,#f97316,#ea580c)', short: '千' },
  mimo:       { gradient: 'linear-gradient(135deg,#ef4444,#dc2626)', short: 'Mi' },
  claude:     { gradient: 'linear-gradient(135deg,#d4a853,#b8923f)', short: 'Cl' },
  copilot:    { gradient: 'linear-gradient(135deg,#6366f1,#4f46e5)', short: 'Co' },
  perplexity: { gradient: 'linear-gradient(135deg,#20b2aa,#178a84)', short: 'Px' },
  grok:       { gradient: 'linear-gradient(135deg,#64748b,#475569)', short: 'Gr' },
  kimi:       { gradient: 'linear-gradient(135deg,#ec4899,#db2777)', short: 'Ki' },
  lmstudio:   { gradient: 'linear-gradient(135deg,#78716c,#57534e)', short: 'LM' },
  ollama:     { gradient: 'linear-gradient(135deg,#a3e635,#65a30d)', short: 'Ol' },
};

export function AIIconSelector({ ais, selected, onToggle }: AIIconSelectorProps) {
  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      {ais.map((ai) => {
        const isSelected = selected.includes(ai.id);
        const style = AI_ICON_STYLES[ai.id] || {
          gradient: 'linear-gradient(135deg,#6366f1,#4f46e5)',
          short: ai.name.slice(0, 2).toUpperCase(),
        };

        return (
          <div
            key={ai.id}
            onClick={() => onToggle(ai.id)}
            style={{
              width: 36,
              height: 36,
              borderRadius: 6,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontFamily: "'Syne', sans-serif",
              fontWeight: 700,
              fontSize: 11,
              color: '#fff',
              cursor: 'pointer',
              transition: 'all 0.25s',
              position: 'relative',
              background: style.gradient,
              filter: isSelected ? 'none' : 'grayscale(1) brightness(0.45)',
              opacity: isSelected ? 1 : 0.45,
              border: isSelected ? '2px solid var(--accent)' : '2px solid transparent',
              boxShadow: isSelected ? '0 0 10px rgba(212,168,83,0.2)' : 'none',
            }}
            onMouseEnter={(e) => {
              if (!isSelected) {
                e.currentTarget.style.filter = 'grayscale(0.5) brightness(0.7)';
                e.currentTarget.style.opacity = '0.7';
              }
            }}
            onMouseLeave={(e) => {
              if (!isSelected) {
                e.currentTarget.style.filter = 'grayscale(1) brightness(0.45)';
                e.currentTarget.style.opacity = '0.45';
              }
            }}
          >
            {style.short}
            {isSelected && (
              <span
                style={{
                  position: 'absolute',
                  top: -3,
                  right: -3,
                  width: 12,
                  height: 12,
                  borderRadius: '50%',
                  background: 'var(--accent)',
                  border: '2px solid var(--bg-surface)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 7,
                  color: 'var(--bg-deep)',
                  fontWeight: 700,
                }}
              >
                ✓
              </span>
            )}
            <span
              style={{
                position: 'absolute',
                bottom: 'calc(100% + 6px)',
                left: '50%',
                transform: 'translateX(-50%)',
                fontFamily: "'DM Mono', monospace",
                fontSize: 10,
                color: 'var(--text-secondary)',
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                padding: '3px 8px',
                borderRadius: 4,
                whiteSpace: 'nowrap',
                opacity: 0,
                pointerEvents: 'none',
                transition: 'opacity 0.2s',
              }}
              className="ai-icon-tooltip"
            >
              {ai.name}
            </span>
          </div>
        );
      })}
    </div>
  );
}
