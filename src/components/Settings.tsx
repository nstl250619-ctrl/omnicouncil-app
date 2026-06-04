import { useState } from 'react';
import { useConfigStore, EngineMode } from '../stores/configStore';

type SettingsTab = 'ai' | 'engine' | 'reset' | 'about';

export function Settings({ onClose }: { onClose: () => void }) {
  const [activeTab, setActiveTab] = useState<SettingsTab>('ai');
  const { engineMode, setEngineMode, ais, toggleAI, updateAIStatus } = useConfigStore();

  return (
    <div className="settings-overlay">
      <div className="settings-window">
        <div className="settings-header">
          <h1>⚙️ 设置</h1>
          <button className="settings-close" onClick={onClose}>✕</button>
        </div>

        <div className="settings-body">
          {/* Sidebar */}
          <div className="settings-sidebar">
            <button
              className={`settings-nav ${activeTab === 'ai' ? 'active' : ''}`}
              onClick={() => setActiveTab('ai')}
            >
              🤖 AI 管理
            </button>
            <button
              className={`settings-nav ${activeTab === 'engine' ? 'active' : ''}`}
              onClick={() => setActiveTab('engine')}
            >
              🔧 引擎
            </button>
            <button
              className={`settings-nav ${activeTab === 'about' ? 'active' : ''}`}
              onClick={() => setActiveTab('about')}
            >
              ℹ️ 关于
            </button>
            <button
              className={`settings-nav ${activeTab === 'reset' ? 'active' : ''}`}
              onClick={() => setActiveTab('reset')}
            >
              🔄 向导与重置
            </button>
          </div>

          {/* Content */}
          <div className="settings-content">
            {activeTab === 'ai' && (
              <div className="settings-section">
                <h2>🤖 AI 管理</h2>
                <div className="ai-list">
                  {ais.map((ai) => (
                    <div key={ai.aiId} className="ai-item">
                      <div className="ai-info">
                        <span className="ai-name">{ai.aiName}</span>
                        <span className={`ai-status status-${ai.status}`}>
                          {ai.status === 'connected' && '✅ 已连接'}
                          {ai.status === 'disconnected' && '⚪ 未连接'}
                          {ai.status === 'expired' && '⚠️ 已过期'}
                        </span>
                      </div>
                      <div className="ai-actions">
                        <label className="toggle">
                          <input
                            type="checkbox"
                            checked={ai.enabled}
                            onChange={() => toggleAI(ai.aiId)}
                          />
                          <span className="toggle-slider" />
                        </label>
                        {ai.status === 'expired' && (
                          <button className="btn-small" onClick={() => updateAIStatus(ai.aiId, 'connected')}>
                            重新登录
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                <button className="btn-add-ai">+ 添加新 AI</button>
              </div>
            )}

            {activeTab === 'engine' && (
              <div className="settings-section">
                <h2>🔧 引擎设置</h2>
                <div className="setting-group">
                  <label>连接模式</label>
                  <div className="mode-options">
                    <label className="mode-option">
                      <input
                        type="radio"
                        name="engine"
                        value="cdp"
                        checked={engineMode === 'cdp'}
                        onChange={() => setEngineMode('cdp' as EngineMode)}
                      />
                      <span>🖥️ 接管本地 Chrome（推荐）</span>
                    </label>
                    <label className="mode-option">
                      <input
                        type="radio"
                        name="engine"
                        value="embedded"
                        checked={engineMode === 'embedded'}
                        onChange={() => setEngineMode('embedded' as EngineMode)}
                      />
                      <span>🔒 内嵌 Chromium</span>
                    </label>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'about' && (
              <div className="settings-section">
                <h2>ℹ️ 关于 OmniCouncil</h2>
                <div className="about-info">
                  <p><strong>版本:</strong> 0.1.0</p>
                  <p><strong>描述:</strong> 多AI共识决策操作系统</p>
                  <p><strong>架构:</strong> Tauri + Python + Playwright</p>
                </div>
              </div>
            )}

            {activeTab === 'reset' && (
              <div className="settings-section">
                <h2>🔄 向导与重置</h2>
                <div className="setting-group">
                  <p style={{ color: 'var(--text-secondary)', marginBottom: '16px', fontSize: '13px' }}>
                    如果首次设置出现问题，可以重新运行初始向导或清除所有本地状态。
                  </p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <button
                      className="btn-add-ai"
                      style={{ borderColor: 'var(--accent)', color: 'var(--accent)' }}
                      onClick={() => {
                        useConfigStore.getState().completeSetup('embedded');
                        window.location.reload();
                      }}
                    >
                      🔄 重新运行初始向导
                    </button>
                    <button
                      style={{
                        padding: '10px 16px',
                        background: 'transparent',
                        border: '1px solid var(--error)',
                        borderRadius: '8px',
                        color: 'var(--error)',
                        cursor: 'pointer',
                        width: '100%',
                      }}
                      onClick={() => {
                        if (confirm('确定要清除所有本地状态吗？这将删除所有登录信息和配置。')) {
                          useConfigStore.getState().completeSetup('embedded');
                          window.location.reload();
                        }
                      }}
                    >
                      🗑️ 清除所有本地状态（恢复出厂）
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
