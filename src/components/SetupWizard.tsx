import { useState } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';

type EngineMode = 'cdp' | 'embedded';
type WizardStep = 'mode' | 'connect' | 'complete';

interface SetupWizardProps {
  onComplete: (mode: EngineMode) => void;
}

interface AIItem {
  aiId: string;
  aiName: string;
  color: string;
  connected: boolean;
  connecting: boolean;
}

export function SetupWizard({ onComplete }: SetupWizardProps) {
  const { send } = useWebSocket();
  const [step, setStep] = useState<WizardStep>('mode');
  const [selectedMode, setSelectedMode] = useState<EngineMode | null>(null);
  const [ais, setAis] = useState<AIItem[]>([
    { aiId: 'deepseek', aiName: 'DeepSeek', color: '#4F8FFF', connected: false, connecting: false },
    { aiId: 'qianwen', aiName: '千问', color: '#F59E0B', connected: false, connecting: false },
  ]);

  const handleModeSelect = (mode: EngineMode) => {
    setSelectedMode(mode);
    setStep('connect');
  };

  const handleConnect = (aiId: string) => {
    setAis((prev) => prev.map((ai) => ai.aiId === aiId ? { ...ai, connecting: true } : ai));
    send('reauth', { ai_id: aiId });
  };

  const connectedCount = ais.filter((ai) => ai.connected).length;

  // Step 1: Mode Selection
  if (step === 'mode') {
    return (
      <div className="setup-wizard">
        <div className="setup-container">
          <div className="setup-step">
            <div className="setup-header">
              <div className="setup-icon">🔮</div>
              <h1>欢迎使用 OmniCouncil</h1>
              <p className="setup-subtitle">
                让多个AI共同思考，而不是让你重复劳动。<br />
                首先，选择连接模式：
              </p>
            </div>

            <div className="mode-cards">
              <div className="mode-card" onClick={() => handleModeSelect('cdp')}>
                <div className="mode-icon">🖥️</div>
                <h2>接管本地 Chrome</h2>
                <div className="mode-divider" />
                <p>复用你日常使用的 Chrome 登录态，无需重复登录</p>
                <ul className="mode-features">
                  <li className="feature-good">✅ 零配置</li>
                  <li className="feature-good">✅ 自动绕过验证码</li>
                  <li className="feature-good">✅ 登录一次永久有效</li>
                  <li className="feature-warn">⚠️ 需要 Chrome 浏览器</li>
                </ul>
                <div className="mode-badge recommended">推荐</div>
              </div>

              <div className="mode-card" onClick={() => handleModeSelect('embedded')}>
                <div className="mode-icon">🔒</div>
                <h2>内嵌浏览器</h2>
                <div className="mode-divider" />
                <p>使用内置的 Chromium，首次需手动登录</p>
                <ul className="mode-features">
                  <li className="feature-good">✅ 开箱即用</li>
                  <li className="feature-good">✅ 不依赖外部 Chrome</li>
                  <li className="feature-warn">⚠️ Cookie 过期需重新登录</li>
                  <li className="feature-warn">⚠️ 风控可能弹验证码</li>
                </ul>
              </div>
            </div>

            <div className="setup-hint">
              💡 提示：如果你日常使用 Chrome 浏览器，推荐选择"接管模式"
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Step 2: AI Connection
  if (step === 'connect') {
    return (
      <div className="setup-wizard">
        <div className="setup-container">
          <div className="setup-step">
            <div className="setup-header">
              <div className="setup-icon">🔗</div>
              <h1>连接 AI 账号</h1>
              <p className="setup-subtitle">
                {selectedMode === 'cdp'
                  ? '请确保 Chrome 已以调试模式启动，然后连接各 AI 账号。'
                  : '点击"连接"按钮，在弹出的浏览器窗口中登录各 AI 账号。'}
              </p>
            </div>

            <div className="login-cards">
              {ais.map((ai) => (
                <div key={ai.aiId} className="login-card">
                  <div className="login-header">
                    <span className="login-ai-name" style={{ color: ai.color }}>
                      {ai.aiName}
                    </span>
                    <span className={`login-status ${ai.connected ? 'status-connected' : ''}`}>
                      {ai.connected ? '✅ 已连接' : ai.connecting ? '⏳ 连接中...' : '未连接'}
                    </span>
                  </div>

                  {!ai.connected && !ai.connecting && (
                    <div style={{ padding: '16px', display: 'flex', gap: '8px' }}>
                      <button className="setup-next" onClick={() => handleConnect(ai.aiId)}>
                        连接 {ai.aiName}
                      </button>
                      <button className="setup-skip" onClick={() => setStep('complete')}>
                        跳过
                      </button>
                    </div>
                  )}

                  {ai.connecting && (
                    <div style={{ padding: '24px', textAlign: 'center' }}>
                      <div className="pulse-loader" style={{ justifyContent: 'center', marginBottom: '12px' }}>
                        <div className="pulse-dot" style={{ background: ai.color }} />
                        <div className="pulse-dot" style={{ background: ai.color }} />
                        <div className="pulse-dot" style={{ background: ai.color }} />
                      </div>
                      <p style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>
                        请在弹出的浏览器窗口中完成登录...
                      </p>
                    </div>
                  )}

                  {ai.connected && (
                    <div style={{ padding: '16px', textAlign: 'center', color: 'var(--success)', fontSize: '13px' }}>
                      ✅ 登录成功，可以使用
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="setup-privacy">
              🔒 登录信息仅保存在本地，不会上传到任何服务器
            </div>

            <div className="setup-actions">
              <button className="setup-back" onClick={() => setStep('mode')}>
                ← 返回
              </button>
              <button
                className="setup-next"
                onClick={() => setStep('complete')}
                disabled={connectedCount === 0}
              >
                {connectedCount > 0
                  ? `完成设置 → (${connectedCount} 个已连接)`
                  : '请至少连接 1 个 AI'}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Step 3: Complete
  return (
    <div className="setup-wizard">
      <div className="setup-container">
        <div className="setup-step">
          <div className="setup-header">
            <div className="setup-icon">🎉</div>
            <h1>设置完成！</h1>
            <p className="setup-subtitle">
              已连接 {connectedCount} 个 AI。<br />
              现在可以开始使用 OmniCouncil 了。
            </p>
          </div>

          <div style={{ textAlign: 'center', marginTop: '24px' }}>
            <button
              className="setup-next"
              style={{ padding: '14px 32px', fontSize: '16px' }}
              onClick={() => onComplete(selectedMode || 'embedded')}
            >
              进入控制台 →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
