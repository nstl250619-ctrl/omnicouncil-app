import { useState, useEffect, useCallback, useRef } from 'react';
import { ProviderStatusCard } from '../components/ProviderStatusCard';
import { MetricsSummary } from '../components/MetricsSummary';
import { AlertRecoveryPanel } from '../components/AlertRecoveryPanel';
import { ProviderDetailPanel } from '../components/ProviderDetailPanel';

const API_BASE = 'http://127.0.0.1:8765';

const AI_META: Record<string, { name: string; color: string; short: string }> = {
  deepseek: { name: 'DeepSeek', color: '#4d7cfe', short: 'DS' },
  gemini:   { name: 'Gemini',   color: '#8b5cf6', short: 'Ge' },
  chatgpt:  { name: 'ChatGPT',  color: '#10b981', short: 'Gt' },
  qianwen:  { name: '千问',     color: '#f97316', short: '千' },
  mimo:     { name: 'MiMo',     color: '#ef4444', short: 'Mi' },
  grok:     { name: 'Grok',     color: '#64748b', short: 'Gr' },
};

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

interface DashboardPageProps {
  onNavigateToConsole?: () => void;
}

export function DashboardPage({ onNavigateToConsole }: DashboardPageProps) {
  const [providers, setProviders] = useState<ProviderHealth[]>([]);
  const [metrics, setMetrics] = useState<Record<string, Record<string, number>>>({});
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null);
  const fetchRef = useRef<() => void>(() => {});

  // Fetch dashboard data
  fetchRef.current = async () => {
    try {
      const [healthRes, metricsRes] = await Promise.all([
        fetch(`${API_BASE}/api/dashboard/health`),
        fetch(`${API_BASE}/api/dashboard/metrics`),
      ]);

      if (healthRes.ok) {
        const healthData = await healthRes.json();
        const list: ProviderHealth[] = Object.entries(healthData.providers || {}).map(
          ([platform, data]: [string, any]) => ({
            platform,
            ...data,
          })
        );
        setProviders(list);
      }

      if (metricsRes.ok) {
        const metricsData = await metricsRes.json();
        setMetrics(metricsData.providers || {});
      }
    } catch {
      // Silent — backend may not be running
    }
  };

  useEffect(() => {
    fetchRef.current();
    const interval = setInterval(() => fetchRef.current(), 30000);
    return () => clearInterval(interval);
  }, []);

  // Build alerts
  const alerts = providers
    .filter((p) => ['login_required', 'degraded', 'unavailable'].includes(p.state))
    .map((p) => ({
      platform: p.platform,
      displayName: AI_META[p.platform]?.name ?? p.platform,
      severity: p.state === 'login_required' ? 'critical' as const : 'warning' as const,
      message:
        p.state === 'login_required'
          ? '需要手动登录'
          : p.state === 'degraded'
          ? '平台降级运行'
          : '平台不可用',
      state: p.state,
      action: p.state === 'login_required' ? 'login' as const : 'none' as const,
    }));

  const handleLogin = useCallback((platform: string) => {
    fetch(`${API_BASE}/api/providers/${platform}/reauth`, { method: 'POST' }).catch(() => {});
  }, []);

  // Detail view
  if (selectedProvider) {
    const provider = providers.find((p) => p.platform === selectedProvider);
    if (provider) {
      return (
        <div style={{ padding: '24px 32px', overflowY: 'auto', height: '100%' }}>
          <ProviderDetailPanel
            provider={provider}
            displayName={AI_META[provider.platform]?.name ?? provider.platform}
            onBack={() => setSelectedProvider(null)}
            onLogin={handleLogin}
          />
        </div>
      );
    }
  }

  // Dashboard view
  const onlineCount = providers.filter((p) => p.state === 'healthy').length;

  return (
    <div style={{ padding: '24px 32px', overflowY: 'auto', height: '100%' }}>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 800, fontSize: 20, marginBottom: 4 }}>
          Dashboard
        </div>
        <div style={{ fontFamily: "'DM Mono', monospace", fontSize: 12, color: 'var(--text-muted)' }}>
          {providers.length} 平台 · {onlineCount} 在线
        </div>
      </div>

      {/* Provider cards grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
          gap: 12,
          marginBottom: 24,
        }}
      >
        {providers.map((p) => (
          <ProviderStatusCard
            key={p.platform}
            provider={p}
            displayName={AI_META[p.platform]?.name ?? p.platform}
            iconColor={AI_META[p.platform]?.color ?? '#6366f1'}
            iconShort={AI_META[p.platform]?.short ?? p.platform.slice(0, 2).toUpperCase()}
            hasAlert={alerts.some((a) => a.platform === p.platform)}
            onClick={() => setSelectedProvider(p.platform)}
          />
        ))}
      </div>

      {/* Bottom row: metrics + alerts */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <MetricsSummary metrics={metrics} />
        <AlertRecoveryPanel alerts={alerts} onLogin={handleLogin} />
      </div>
    </div>
  );
}
