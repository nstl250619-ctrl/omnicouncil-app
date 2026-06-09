import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useAppStore, type RuntimeHealth } from '../stores/appStore';
import Titlebar from '../components/Titlebar';

interface PlatformInfo {
  id: string;
  name: string;
  url: string;
  homeUrl?: string;
  icon: string;
  status: 'connected' | 'disconnected' | 'idle';
  latency: string;
  circuitBreaker: 'CLOSED' | 'OPEN' | 'HALF_OPEN';
  lastHeartbeat: string;
  profileSize: string;
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

// Default platforms from backend
const DEFAULT_PLATFORMS: PlatformInfo[] = [
  { id: 'deepseek', name: 'DeepSeek', url: 'chat.deepseek.com', icon: 'DS', status: 'connected', latency: '1.2s', circuitBreaker: 'CLOSED', lastHeartbeat: '8s ago', profileSize: '24 MB' },
  { id: 'gemini', name: 'Gemini', url: 'gemini.google.com', icon: 'Ge', status: 'connected', latency: '2.1s', circuitBreaker: 'CLOSED', lastHeartbeat: '15s ago', profileSize: '31 MB' },
  { id: 'chatgpt', name: 'ChatGPT', url: 'chatgpt.com', icon: 'Gt', status: 'connected', latency: '3.4s', circuitBreaker: 'CLOSED', lastHeartbeat: '5s ago', profileSize: '42 MB' },
  { id: 'qianwen', name: '千问', url: 'tongyi.aliyun.com', icon: '千', status: 'connected', latency: '0.9s', circuitBreaker: 'CLOSED', lastHeartbeat: '22s ago', profileSize: '18 MB' },
  { id: 'mimo', name: 'MiMo', url: 'mimo.xiaomi.com', icon: 'Mi', status: 'connected', latency: '1.5s', circuitBreaker: 'CLOSED', lastHeartbeat: '3s ago', profileSize: '15 MB' },
  { id: 'claude', name: 'Claude', url: 'claude.ai', icon: 'Cl', status: 'disconnected', latency: '--', circuitBreaker: 'OPEN', lastHeartbeat: '12m ago', profileSize: '38 MB' },
];

/** Map RuntimeHealth state → status light color */
function healthColor(state: string): string {
  switch (state) {
    case 'healthy': return 'var(--green)';
    case 'degraded': return 'var(--amber)';
    case 'unavailable':
    case 'login_required': return 'var(--red)';
    default: return 'var(--text-muted)';
  }
}

/** Map RuntimeHealth state → label text */
function healthLabel(state: string): string {
  switch (state) {
    case 'healthy': return '健康';
    case 'degraded': return '异常';
    case 'login_required': return '需登录';
    case 'unavailable': return '不可用';
    default: return '未知';
  }
}

const API_BASE = 'http://127.0.0.1:8765';

interface PlatformSetupPageProps {
  onNavigateToConsole: () => void;
}

export function PlatformSetupPage({ onNavigateToConsole }: PlatformSetupPageProps) {
  const [platforms, setPlatforms] = useState<PlatformInfo[]>(DEFAULT_PLATFORMS);
  const [searchQuery, setSearchQuery] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showAddModal, setShowAddModal] = useState(false);
  const [newName, setNewName] = useState('');
  const [newUrl, setNewUrl] = useState('');
  const [newHomeUrl, setNewHomeUrl] = useState('');
  const [reauthing, setReauthing] = useState<Set<string>>(new Set());

  // RuntimeHealth from store (updated by WebSocket events + HTTP polling)
  const runtimeHealthMap = useAppStore((s) => s.runtimeHealthMap);
  const setRuntimeHealthMap = useAppStore((s) => s.setRuntimeHealthMap);

  // ── Poll /api/runtime/health every 30s ──
  const fetchHealthRef = useRef<() => void>(() => {});
  fetchHealthRef.current = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/runtime/health`);
      if (!res.ok) return;
      const data: Record<string, RuntimeHealth> = await res.json();
      setRuntimeHealthMap(data);
    } catch (e) {
      // Silent — backend may not be running
    }
  };

  useEffect(() => {
    fetchHealthRef.current();
    const interval = setInterval(() => fetchHealthRef.current(), 30000);
    return () => clearInterval(interval);
  }, []);

  // Merge health data into PlatformInfo status for display
  const mergedPlatforms = useMemo(() => {
    return platforms.map((p) => {
      const rh = runtimeHealthMap[p.id];
      if (!rh) return p;
      const state = rh.state;
      return {
        ...p,
        status: state === 'healthy' ? 'connected' as const : 'disconnected' as const,
        lastHeartbeat: rh.last_heartbeat
          ? `${Math.floor((Date.now() / 1000 - rh.last_heartbeat))}s ago`
          : p.lastHeartbeat,
      };
    });
  }, [platforms, runtimeHealthMap]);

  const filteredPlatforms = useMemo(
    () =>
      mergedPlatforms.filter(
        (p) =>
          p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          p.url.toLowerCase().includes(searchQuery.toLowerCase())
      ),
    [mergedPlatforms, searchQuery]
  );

  const toggleSelect = useCallback((id: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    setSelected((prev) =>
      prev.size === mergedPlatforms.length ? new Set() : new Set(mergedPlatforms.map((p) => p.id))
    );
  }, [mergedPlatforms]);

  // ── Backend API calls ──

  const reconnectPlatform = useCallback(
    async (id: string, e?: React.MouseEvent) => {
      e?.stopPropagation();
      if (reauthing.has(id)) return;
      setReauthing((prev) => new Set(prev).add(id));
      try {
        const res = await fetch(`${API_BASE}/api/providers/${id}/reauth`, { method: 'POST' });
        if (res.ok) {
          const data = await res.json();
          if (data.status === 'recovery_succeeded') {
            // Recovery worked — update immediately
            setPlatforms((prev) =>
              prev.map((p) =>
                p.id === id
                  ? { ...p, status: 'connected' as const, circuitBreaker: 'CLOSED' as const, lastHeartbeat: '0s ago' }
                  : p
              )
            );
          } else if (data.status === 'login_started') {
            // Login browser opened — show connecting state, wait for WS event
            setPlatforms((prev) =>
              prev.map((p) =>
                p.id === id
                  ? { ...p, status: 'idle' as const }
                  : p
              )
            );
            // Poll health until login completes (max 5 min)
            const pollId = setInterval(() => fetchHealthRef.current(), 5000);
            setTimeout(() => clearInterval(pollId), 300000);
          }
        }
      } catch (err) {
        console.error('reconnect failed:', err);
      } finally {
        setReauthing((prev) => { const next = new Set(prev); next.delete(id); return next; });
      }
      // Refresh health after a short delay
      setTimeout(() => fetchHealthRef.current(), 2000);
    },
    [reauthing]
  );

  const resetPlatform = useCallback((id: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    // Reset = reauth + cleanup
    reconnectPlatform(id);
  }, [reconnectPlatform]);

  const deletePlatform = useCallback(async (id: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    const p = mergedPlatforms.find((x) => x.id === id);
    if (!p || !window.confirm(`确认删除 ${p.name}？`)) return;
    try {
      const res = await fetch(`${API_BASE}/api/providers/${id}`, { method: 'DELETE' });
      if (res.ok) {
        setPlatforms((prev) => prev.filter((x) => x.id !== id));
        setSelected((prev) => { const next = new Set(prev); next.delete(id); return next; });
      } else {
        console.warn('DELETE /api/providers returned', res.status, '- falling back to local delete');
        setPlatforms((prev) => prev.filter((x) => x.id !== id));
        setSelected((prev) => { const next = new Set(prev); next.delete(id); return next; });
      }
    } catch {
      // Backend not available — local delete only
      setPlatforms((prev) => prev.filter((x) => x.id !== id));
      setSelected((prev) => { const next = new Set(prev); next.delete(id); return next; });
    }
  }, [mergedPlatforms]);

  const showWebPage = useCallback((id: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    // Open in built-in Chromium via backend login API (not window.open which uses Edge)
    reconnectPlatform(id);
  }, [reconnectPlatform]);

  const addPlatform = useCallback(async () => {
    if (!newName.trim() || !newUrl.trim()) return;
    const id = newName.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
    if (mergedPlatforms.find((p) => p.id === id)) return;
    const newPlatform: PlatformInfo = {
      id,
      name: newName,
      url: newUrl,
      homeUrl: newHomeUrl,
      icon: newName.slice(0, 2).toUpperCase(),
      status: 'idle',
      latency: '--',
      circuitBreaker: 'CLOSED',
      lastHeartbeat: '--',
      profileSize: '--',
    };
    setPlatforms((prev) => [...prev, newPlatform]);
    setShowAddModal(false);
    setNewName('');
    setNewUrl('');
    setNewHomeUrl('');

    // Also notify backend
    try {
      await fetch(`${API_BASE}/api/providers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName, url: newUrl, home_url: newHomeUrl }),
      });
    } catch {
      // Backend may not be running — platform is added locally
    }
  }, [newName, newUrl, newHomeUrl, mergedPlatforms]);

  const reconnectSelected = useCallback(() => {
    if (!selected.size) return;
    selected.forEach((id) => reconnectPlatform(id));
  }, [selected, reconnectPlatform]);

  const resetSelected = useCallback(() => {
    if (!selected.size) return;
    selected.forEach((id) => resetPlatform(id));
  }, [selected, resetPlatform]);

  const deleteSelected = useCallback(() => {
    if (!selected.size) return;
    const names = mergedPlatforms.filter((p) => selected.has(p.id)).map((p) => p.name).join(', ');
    if (!window.confirm(`确认删除 ${selected.size} 个平台？\n${names}`)) return;
    setPlatforms((prev) => prev.filter((p) => !selected.has(p.id)));
    setSelected(new Set());
  }, [selected, mergedPlatforms]);

  const connectedCount = mergedPlatforms.filter((p) => p.status === 'connected').length;
  const disconnectedCount = mergedPlatforms.filter((p) => p.status === 'disconnected').length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', position: 'relative', zIndex: 1 }}>
      <Titlebar statusText="平台管理" />

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', marginTop: 40 }}>
        {/* Left rail */}
        <div
          style={{
            width: 56,
            background: 'var(--bg-surface)',
            borderRight: '1px solid var(--border-subtle)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            padding: '16px 0',
            gap: 6,
            flexShrink: 0,
          }}
        >
          <button
            style={{
              width: 38,
              height: 38,
              borderRadius: 6,
              border: '1px solid rgba(212,168,83,0.25)',
              background: 'var(--accent-glow)',
              color: 'var(--accent)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 16,
            }}
            title="平台管理"
          >
            🖥
          </button>
          <button
            onClick={onNavigateToConsole}
            style={{
              width: 38,
              height: 38,
              borderRadius: 6,
              border: '1px solid transparent',
              background: 'transparent',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 16,
              position: 'relative',
            }}
            title="控制台"
          >
            ▶
            <span
              style={{
                position: 'absolute',
                top: 4,
                right: 4,
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: 'var(--green)',
                border: '2px solid var(--bg-surface)',
              }}
            />
          </button>
          <div style={{ width: 24, height: 1, background: 'var(--border-subtle)', margin: '4px 0' }} />
          <button
            onClick={() => setShowAddModal(true)}
            style={{
              width: 38,
              height: 38,
              borderRadius: 6,
              border: '1px solid transparent',
              background: 'transparent',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 16,
            }}
            title="添加平台"
          >
            ＋
          </button>
          <div style={{ flex: 1 }} />
          <button
            style={{
              width: 38,
              height: 38,
              borderRadius: 6,
              border: '1px solid transparent',
              background: 'transparent',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 16,
            }}
            title="设置"
          >
            ⚙
          </button>
        </div>

        {/* Main area */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Top bar */}
          <div
            style={{
              height: 52,
              background: 'var(--bg-surface)',
              borderBottom: '1px solid var(--border-subtle)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '0 24px',
              flexShrink: 0,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
              <div
                style={{
                  fontFamily: "'Syne', sans-serif",
                  fontWeight: 700,
                  fontSize: 16,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                }}
              >
                AI 平台管理
                <span
                  style={{
                    fontFamily: "'DM Mono', monospace",
                    fontSize: 11,
                    background: 'var(--accent-glow)',
                    color: 'var(--accent)',
                    padding: '2px 8px',
                    borderRadius: 10,
                    fontWeight: 500,
                  }}
                >
                  {mergedPlatforms.length}
                </span>
              </div>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  background: 'var(--bg-inset)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 6,
                  padding: '6px 12px',
                  width: 220,
                }}
              >
                <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>⌕</span>
                <input
                  type="text"
                  placeholder="搜索平台..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  style={{
                    background: 'none',
                    border: 'none',
                    outline: 'none',
                    fontFamily: "'DM Mono', monospace",
                    fontSize: 12,
                    color: 'var(--text-primary)',
                    width: '100%',
                  }}
                />
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button
                onClick={reconnectSelected}
                style={{
                  padding: '7px 14px',
                  borderRadius: 6,
                  fontFamily: "'Syne', sans-serif",
                  fontWeight: 600,
                  fontSize: 12,
                  cursor: 'pointer',
                  border: '1px solid var(--border)',
                  background: 'transparent',
                  color: 'var(--text-secondary)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                ⟳ 重连选中
              </button>
              <button
                onClick={resetSelected}
                style={{
                  padding: '7px 14px',
                  borderRadius: 6,
                  fontFamily: "'Syne', sans-serif",
                  fontWeight: 600,
                  fontSize: 12,
                  cursor: 'pointer',
                  border: '1px solid var(--border)',
                  background: 'transparent',
                  color: 'var(--text-secondary)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                ↺ 重置选中
              </button>
              <button
                onClick={deleteSelected}
                style={{
                  padding: '7px 14px',
                  borderRadius: 6,
                  fontFamily: "'Syne', sans-serif",
                  fontWeight: 600,
                  fontSize: 12,
                  cursor: 'pointer',
                  border: '1px solid rgba(239,68,68,0.3)',
                  background: 'transparent',
                  color: 'var(--red)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                ✕ 删除选中
              </button>
              <button
                onClick={() => setShowAddModal(true)}
                style={{
                  padding: '7px 14px',
                  borderRadius: 6,
                  fontFamily: "'Syne', sans-serif",
                  fontWeight: 600,
                  fontSize: 12,
                  cursor: 'pointer',
                  border: 'none',
                  background: 'var(--accent)',
                  color: 'var(--bg-deep)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                ＋ 添加平台
              </button>
            </div>
          </div>

          {/* Table */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ width: 36 }}>
                    <div
                      onClick={toggleAll}
                      style={{
                        width: 16,
                        height: 16,
                        borderRadius: 3,
                        border: `1.5px solid ${selected.size === platforms.length && platforms.length > 0 ? 'var(--accent)' : 'var(--border)'}`,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                        background: selected.size === platforms.length && platforms.length > 0 ? 'var(--accent)' : 'transparent',
                      }}
                    >
                      {selected.size === platforms.length && platforms.length > 0 && (
                        <span style={{ fontSize: 10, color: 'var(--bg-deep)', fontWeight: 700 }}>✓</span>
                      )}
                    </div>
                  </th>
                  <th style={thStyle}>平台</th>
                  <th style={{ ...thStyle, width: 110 }}>状态</th>
                  <th style={{ ...thStyle, width: 80 }}>延迟</th>
                  <th style={{ ...thStyle, width: 100 }}>熔断器</th>
                  <th style={{ ...thStyle, width: 100 }}>心跳</th>
                  <th style={{ ...thStyle, width: 90 }}>Profile</th>
                  <th style={{ ...thStyle, width: 120 }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {filteredPlatforms.map((p) => {
                  const iconStyle = AI_ICON_STYLES[p.id] || { gradient: 'linear-gradient(135deg,#6366f1,#4f46e5)', short: p.icon };
                  const isSelected = selected.has(p.id);

                  return (
                    <tr
                      key={p.id}
                      onClick={() => toggleSelect(p.id)}
                      style={{
                        borderBottom: '1px solid var(--border-subtle)',
                        cursor: 'pointer',
                        background: isSelected ? 'var(--accent-glow)' : 'transparent',
                        transition: 'background 0.25s',
                      }}
                    >
                      <td style={tdStyle}>
                        <div
                          onClick={(e) => toggleSelect(p.id, e)}
                          style={{
                            width: 16,
                            height: 16,
                            borderRadius: 3,
                            border: `1.5px solid ${isSelected ? 'var(--accent)' : 'var(--border)'}`,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            cursor: 'pointer',
                            background: isSelected ? 'var(--accent)' : 'transparent',
                          }}
                        >
                          {isSelected && <span style={{ fontSize: 10, color: 'var(--bg-deep)', fontWeight: 700 }}>✓</span>}
                        </div>
                      </td>
                      <td style={tdStyle}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <div
                            style={{
                              width: 32,
                              height: 32,
                              borderRadius: 6,
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              fontFamily: "'Syne', sans-serif",
                              fontWeight: 700,
                              fontSize: 11,
                              color: '#fff',
                              background: iconStyle.gradient,
                              flexShrink: 0,
                            }}
                          >
                            {iconStyle.short}
                          </div>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                            <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 600, fontSize: 13 }}>{p.name}</span>
                            <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 10, color: 'var(--text-muted)' }}>{p.url}</span>
                          </div>
                        </div>
                      </td>
                      <td style={tdStyle}>
                        {(() => {
                          const rh = runtimeHealthMap[p.id];
                          const state = rh?.state ?? 'unknown';
                          const color = healthColor(state);
                          const label = rh ? healthLabel(state) : (p.status === 'connected' ? '已连接' : p.status === 'disconnected' ? '未连接' : '空闲');
                          const isGreen = color === 'var(--green)';
                          const isRed = color === 'var(--red)';
                          const isAmber = color === 'var(--amber)';
                          return (
                            <span
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 5,
                                fontFamily: "'DM Mono', monospace",
                                fontSize: 11,
                                padding: '3px 10px',
                                borderRadius: 12,
                                ...(isGreen
                                  ? { background: 'var(--green-glow)', color: 'var(--green)', border: '1px solid rgba(62,207,142,0.2)' }
                                  : isRed
                                  ? { background: 'var(--red-glow)', color: 'var(--red)', border: '1px solid rgba(239,68,68,0.2)' }
                                  : isAmber
                                  ? { background: 'rgba(245,158,11,0.1)', color: 'var(--amber)', border: '1px solid rgba(245,158,11,0.2)' }
                                  : { background: 'rgba(255,255,255,0.03)', color: 'var(--text-muted)', border: '1px solid var(--border-subtle)' }),
                              }}
                            >
                              <span
                                style={{
                                  width: 6,
                                  height: 6,
                                  borderRadius: '50%',
                                  background: color,
                                  boxShadow: isGreen ? '0 0 6px rgba(62,207,142,0.5)' : isRed ? '0 0 6px rgba(239,68,68,0.5)' : 'none',
                                }}
                              />
                              {label}
                            </span>
                          );
                        })()}
                      </td>
                      <td style={tdStyle}>
                        <span
                          style={{
                            fontFamily: "'DM Mono', monospace",
                            fontSize: 11,
                            color: p.latency === '--' ? 'var(--red)' : parseFloat(p.latency) > 3 ? 'var(--amber)' : 'var(--text-secondary)',
                          }}
                        >
                          {p.latency}
                        </span>
                      </td>
                      <td style={tdStyle}>
                        <span
                          style={{
                            fontFamily: "'DM Mono', monospace",
                            fontSize: 11,
                            color: p.circuitBreaker === 'OPEN' ? 'var(--red)' : 'var(--text-secondary)',
                          }}
                        >
                          {p.circuitBreaker}
                        </span>
                      </td>
                      <td style={tdStyle}>
                        <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: 'var(--text-secondary)' }}>
                          {p.lastHeartbeat}
                        </span>
                      </td>
                      <td style={tdStyle}>
                        <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 11, color: 'var(--text-secondary)' }}>
                          {p.profileSize}
                        </span>
                      </td>
                      <td style={tdStyle}>
                        <div style={{ display: 'flex', gap: 4 }}>
                          {(() => {
                            const rh = runtimeHealthMap[p.id];
                            const needsRecovery = rh && (rh.state === 'degraded' || rh.state === 'login_required');
                            const isBusy = reauthing.has(p.id);
                            return (
                              <>
                                {needsRecovery && (
                                  <button
                                    onClick={(e) => reconnectPlatform(p.id, e)}
                                    style={{
                                      ...rowBtnStyle,
                                      color: isBusy ? 'var(--text-muted)' : 'var(--amber)',
                                      borderColor: isBusy ? 'var(--border-subtle)' : 'rgba(245,158,11,0.3)',
                                      cursor: isBusy ? 'default' : 'pointer',
                                    }}
                                    title={isBusy ? '恢复中...' : '恢复'}
                                    disabled={isBusy}
                                  >
                                    {isBusy ? '⋯' : '⟳'}
                                  </button>
                                )}
                                <button onClick={(e) => showWebPage(p.id, e)} style={rowBtnStyle} title="显示网页">⧉</button>
                                <button onClick={(e) => deletePlatform(p.id, e)} style={{ ...rowBtnStyle, color: 'var(--red)' }} title="删除">✕</button>
                              </>
                            );
                          })()}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Footer */}
          <div
            style={{
              height: 32,
              background: 'var(--bg-surface)',
              borderTop: '1px solid var(--border-subtle)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '0 20px',
              fontFamily: "'DM Mono', monospace",
              fontSize: 10,
              color: 'var(--text-muted)',
              flexShrink: 0,
            }}
          >
            <span>
              已连接: <span style={{ color: 'var(--green)' }}>{connectedCount}</span>
            </span>
            <span style={{ margin: '0 10px', opacity: 0.3 }}>|</span>
            <span>
              未连接: <span style={{ color: 'var(--red)' }}>{disconnectedCount}</span>
            </span>
            <span style={{ margin: '0 10px', opacity: 0.3 }}>|</span>
            <span>总计: {mergedPlatforms.length} 个平台</span>
            <span style={{ margin: '0 10px', opacity: 0.3 }}>|</span>
            <span
              onClick={onNavigateToConsole}
              style={{ color: 'var(--accent)', cursor: 'pointer' }}
            >
              ▶ 进入控制台 →
            </span>
          </div>
        </div>
      </div>

      {/* Add Modal */}
      {showAddModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.6)',
            zIndex: 100,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backdropFilter: 'blur(4px)',
          }}
          onClick={() => setShowAddModal(false)}
        >
          <div
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              borderRadius: 16,
              width: 440,
              animation: 'modalIn 0.3s ease',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              style={{
                padding: '20px 24px 16px',
                borderBottom: '1px solid var(--border-subtle)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 16 }}>添加 AI 平台</div>
              <button
                onClick={() => setShowAddModal(false)}
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: 6,
                  border: 'none',
                  background: 'transparent',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  fontSize: 16,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                ✕
              </button>
            </div>
            <div style={{ padding: '20px 24px' }}>
              <div style={{ marginBottom: 16 }}>
                <label style={labelStyle}>平台名称</label>
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="例如: ChatGPT"
                  style={inputStyle}
                />
              </div>
              <div style={{ marginBottom: 16 }}>
                <label style={labelStyle}>访问地址</label>
                <input
                  value={newUrl}
                  onChange={(e) => setNewUrl(e.target.value)}
                  placeholder="例如: chatgpt.com"
                  style={inputStyle}
                />
              </div>
              <div style={{ marginBottom: 16 }}>
                <label style={labelStyle}>主页 URL</label>
                <input
                  value={newHomeUrl}
                  onChange={(e) => setNewHomeUrl(e.target.value)}
                  placeholder="例如: https://chatgpt.com/"
                  style={inputStyle}
                />
              </div>
            </div>
            <div
              style={{
                padding: '16px 24px 20px',
                borderTop: '1px solid var(--border-subtle)',
                display: 'flex',
                justifyContent: 'flex-end',
                gap: 8,
              }}
            >
              <button
                onClick={() => setShowAddModal(false)}
                style={{
                  padding: '7px 14px',
                  borderRadius: 6,
                  fontFamily: "'Syne', sans-serif",
                  fontWeight: 600,
                  fontSize: 12,
                  cursor: 'pointer',
                  border: '1px solid var(--border)',
                  background: 'transparent',
                  color: 'var(--text-secondary)',
                }}
              >
                取消
              </button>
              <button
                onClick={addPlatform}
                style={{
                  padding: '7px 14px',
                  borderRadius: 6,
                  fontFamily: "'Syne', sans-serif",
                  fontWeight: 600,
                  fontSize: 12,
                  cursor: 'pointer',
                  border: 'none',
                  background: 'var(--accent)',
                  color: 'var(--bg-deep)',
                }}
              >
                确认添加
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Shared styles
const thStyle: React.CSSProperties = {
  fontFamily: "'DM Mono', monospace",
  fontSize: 10,
  fontWeight: 500,
  color: 'var(--text-muted)',
  textTransform: 'uppercase',
  letterSpacing: 0.08,
  textAlign: 'left',
  padding: '10px 14px',
  borderBottom: '1px solid var(--border-subtle)',
  position: 'sticky',
  top: 0,
  background: 'var(--bg-deep)',
  zIndex: 2,
};

const tdStyle: React.CSSProperties = {
  padding: '12px 14px',
  verticalAlign: 'middle',
};

const rowBtnStyle: React.CSSProperties = {
  width: 28,
  height: 28,
  borderRadius: 6,
  border: '1px solid var(--border-subtle)',
  background: 'transparent',
  color: 'var(--text-muted)',
  cursor: 'pointer',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  fontSize: 13,
};

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontFamily: "'DM Mono', monospace",
  fontSize: 11,
  color: 'var(--text-muted)',
  textTransform: 'uppercase',
  letterSpacing: 0.06,
  marginBottom: 6,
};

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '10px 14px',
  background: 'var(--bg-inset)',
  border: '1px solid var(--border)',
  borderRadius: 6,
  fontFamily: "'DM Mono', monospace",
  fontSize: 13,
  color: 'var(--text-primary)',
  outline: 'none',
};
