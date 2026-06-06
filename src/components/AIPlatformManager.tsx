import { useState, useEffect, useMemo } from 'react';
import { useAppStore } from '../stores/appStore';

interface AIPlatformManagerProps {
  onComplete: () => void;
  isSetupMode?: boolean;  // true = first launch, false = settings page
  send: (type: string, data?: Record<string, unknown>) => void;
}

export function AIPlatformManager({ onComplete, isSetupMode = false, send }: AIPlatformManagerProps) {
  const authStatus = useAppStore((s) => s.authStatus);
  const aiList = useAppStore((s) => s.aiList);
  const connectionStatus = useAppStore((s) => s.connectionStatus);

  const [sessionStatus, setSessionStatus] = useState<Record<string, boolean>>({});

  // Request provider list when WebSocket is connected
  useEffect(() => {
    if (connectionStatus === 'connected') {
      send('get_ais');
    }
  }, [connectionStatus, send]);

  // Check saved sessions via API on mount
  useEffect(() => {
    const checkSessions = async () => {
      try {
        const res = await fetch('http://localhost:8765/api/sessions/status');
        if (res.ok) {
          const data = await res.json();
          if (data.sessions) {
            setSessionStatus(data.sessions);
          }
        }
      } catch {}

      // Fallback: check via Tauri config
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        const configStr = await invoke<string>('read_config');
        const config = JSON.parse(configStr);
        if (config.ais) {
          const tauriSessions: Record<string, boolean> = {};
          for (const ai of config.ais) {
            tauriSessions[ai.aiId] = ai.status === 'authenticated';
          }
          setSessionStatus(prev => ({ ...tauriSessions, ...prev }));
        }
      } catch {}
    };
    checkSessions();
  }, []);

  // Build platform list from backend aiList + session/auth status
  const platforms = useMemo(() => {
    return aiList.map(ai => {
      const auth = authStatus[ai.provider_id];
      const sessionOk = sessionStatus[ai.provider_id] || false;
      const authOk = auth?.status === 'authenticated';
      const connecting = auth?.status === 'connecting';

      return {
        aiId: ai.provider_id,
        aiName: ai.display_name,
        color: ai.icon_color || '#6366f1',
        emoji: ai.icon_emoji || '🤖',
        connected: authOk || sessionOk,
        connecting,
        enabled: ai.enabled,
      };
    });
  }, [aiList, authStatus, sessionStatus]);

  const handleConnect = (aiId: string) => {
    send('reauth', { ai_id: aiId });
  };

  const connectedCount = platforms.filter(p => p.connected).length;

  return (
    <div className="platform-manager">
      <div className="platform-container">
        <div className="platform-header">
          <div className="platform-icon">🤖</div>
          <h1>AI 平台管理</h1>
          <p className="platform-subtitle">
            管理你的 AI 平台连接状态。已连接的平台会保存登录状态，下次启动自动恢复。
          </p>
        </div>

        <div className="platform-grid">
          {platforms.map((platform) => (
            <div key={platform.aiId} className={`platform-card ${platform.connected ? 'connected' : 'disconnected'}`}>
              <div className="platform-card-header">
                <div className="platform-card-icon" style={{ background: platform.color }}>
                  {platform.emoji}
                </div>
                <div className="platform-card-info">
                  <div className="platform-card-name">{platform.aiName}</div>
                  <div className={`platform-card-status ${platform.connected ? 'connected' : 'disconnected'}`}>
                    {platform.connected ? '✅ 已连接' : platform.connecting ? '⏳ 连接中...' : '🚫 未连接'}
                  </div>
                </div>
              </div>

              {platform.connecting && (
                <div className="platform-card-connecting">
                  <div className="pulse-loader">
                    <div className="pulse-dot" style={{ background: platform.color }} />
                    <div className="pulse-dot" style={{ background: platform.color }} />
                    <div className="pulse-dot" style={{ background: platform.color }} />
                  </div>
                  <span>请在弹出的浏览器窗口中完成登录...</span>
                </div>
              )}

              <div className="platform-card-actions">
                {!platform.connected && !platform.connecting && (
                  <button className="platform-btn connect" onClick={() => handleConnect(platform.aiId)}>
                    🔗 连接
                  </button>
                )}
              </div>
            </div>
          ))}

          {platforms.length === 0 && (
            <div className="platform-card disconnected">
              <div className="platform-card-header">
                <div className="platform-card-icon" style={{ background: '#6366f1' }}>⏳</div>
                <div className="platform-card-info">
                  <div className="platform-card-name">加载中...</div>
                  <div className="platform-card-status disconnected">正在获取可用平台列表</div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="platform-footer">
          <div className="platform-summary">
            {connectedCount > 0
              ? `✅ ${connectedCount} 个平台已连接`
              : '🚫 暂无已连接的平台'}
          </div>
          {isSetupMode ? (
            <button
              className="platform-btn connect"
              onClick={onComplete}
              disabled={connectedCount === 0}
            >
              {connectedCount > 0 ? '进入控制台 →' : '请至少连接 1 个平台'}
            </button>
          ) : (
            <button className="platform-btn" onClick={onComplete}>
              完成
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
