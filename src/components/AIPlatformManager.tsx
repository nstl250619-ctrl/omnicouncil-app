import { useState, useEffect } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useAppStore } from '../stores/appStore';

interface AIPlatform {
  aiId: string;
  aiName: string;
  color: string;
  connected: boolean;
  connecting: boolean;
  enabled: boolean;
}

interface AIPlatformManagerProps {
  onComplete: () => void;
  isSetupMode?: boolean;  // true = first launch, false = settings page
}

export function AIPlatformManager({ onComplete, isSetupMode = false }: AIPlatformManagerProps) {
  const { send } = useWebSocket();
  const authStatus = useAppStore((s) => s.authStatus);
  const [platforms, setPlatforms] = useState<AIPlatform[]>([
    { aiId: 'deepseek', aiName: 'DeepSeek', color: '#4F8FFF', connected: false, connecting: false, enabled: true },
    { aiId: 'qianwen', aiName: '千问', color: '#F59E0B', connected: false, connecting: false, enabled: true },
  ]);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newName, setNewName] = useState('');
  const [newUrl, setNewUrl] = useState('');

  // Check saved sessions on mount
  useEffect(() => {
    fetch('http://localhost:8765/api/sessions/status')
      .then(res => res.json())
      .then(data => {
        if (data.sessions) {
          setPlatforms(prev => prev.map(p => ({
            ...p,
            connected: data.sessions[p.aiId] || false,
          })));
        }
      })
      .catch(() => {});
  }, []);

  // Listen for auth status updates
  useEffect(() => {
    setPlatforms(prev => prev.map(p => {
      const s = authStatus[p.aiId];
      if (s) {
        return {
          ...p,
          connected: s.status === 'authenticated',
          connecting: s.status === 'connecting',
        };
      }
      return p;
    }));
  }, [authStatus]);

  const handleConnect = (aiId: string) => {
    setPlatforms(prev => prev.map(p =>
      p.aiId === aiId ? { ...p, connecting: true } : p
    ));
    send('reauth', { ai_id: aiId });
  };

  const handleDisable = (aiId: string) => {
    // Reset login state
    setPlatforms(prev => prev.map(p =>
      p.aiId === aiId ? { ...p, connected: false, enabled: false } : p
    ));
    // TODO: Call backend to clear cookies
  };

  const handleDelete = (aiId: string) => {
    setPlatforms(prev => prev.filter(p => p.aiId !== aiId));
    // TODO: Call backend to delete all data for this AI
  };

  const handleAddPlatform = () => {
    if (!newName.trim() || !newUrl.trim()) return;
    const aiId = newName.toLowerCase().replace(/\s+/g, '_');
    setPlatforms(prev => [...prev, {
      aiId,
      aiName: newName,
      color: '#6C5CE7',
      connected: false,
      connecting: false,
      enabled: true,
    }]);
    setNewName('');
    setNewUrl('');
    setShowAddModal(false);
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
                  {platform.aiName.charAt(0)}
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
                {platform.connected && (
                  <button className="platform-btn disable" onClick={() => handleDisable(platform.aiId)}>
                    ⏸️ 停用
                  </button>
                )}
                <button className="platform-btn delete" onClick={() => handleDelete(platform.aiId)}>
                  🗑️ 删除
                </button>
              </div>
            </div>
          ))}

          {/* Add Platform Card */}
          <div className="platform-card add-card" onClick={() => setShowAddModal(true)}>
            <div className="add-card-content">
              <div className="add-icon">+</div>
              <div className="add-text">新增平台</div>
            </div>
          </div>
        </div>

        {/* Add Platform Modal */}
        {showAddModal && (
          <div className="add-modal-overlay" onClick={() => setShowAddModal(false)}>
            <div className="add-modal" onClick={(e) => e.stopPropagation()}>
              <h2>添加新 AI 平台</h2>
              <div className="add-form">
                <label>
                  平台名称
                  <input
                    type="text"
                    placeholder="例如: MiMo"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                  />
                </label>
                <label>
                  登录页面 URL
                  <input
                    type="text"
                    placeholder="例如: https://mimo.example.com"
                    value={newUrl}
                    onChange={(e) => setNewUrl(e.target.value)}
                  />
                </label>
              </div>
              <div className="add-actions">
                <button className="platform-btn" onClick={() => setShowAddModal(false)}>取消</button>
                <button className="platform-btn connect" onClick={handleAddPlatform}>添加</button>
              </div>
            </div>
          </div>
        )}

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
