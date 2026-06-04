import { useState } from 'react';

type EngineMode = 'cdp' | 'embedded';

interface SetupWizardProps {
  onComplete: (mode: EngineMode) => void;
}

export function SetupWizard({ onComplete }: SetupWizardProps) {
  const [step, setStep] = useState<'mode' | 'cdp' | 'embedded' | 'complete'>('mode');
  const [selectedMode, setSelectedMode] = useState<EngineMode | null>(null);
  const [chromeStatus, setChromeStatus] = useState<'idle' | 'launching' | 'connected' | 'error'>('idle');

  const handleModeSelect = (mode: EngineMode) => {
    setSelectedMode(mode);
    if (mode === 'cdp') {
      setStep('cdp');
    } else {
      setStep('embedded');
    }
  };

  const handleLaunchChrome = () => {
    setChromeStatus('launching');
    // In Tauri, this would call a command to launch Chrome
    // For now, simulate
    setTimeout(() => {
      setChromeStatus('connected');
    }, 3000);
  };

  const handleComplete = () => {
    if (selectedMode) {
      onComplete(selectedMode);
    }
  };

  return (
    <div className="setup-wizard">
      <div className="setup-container">
        {/* Step 1: Mode Selection */}
        {step === 'mode' && (
          <div className="setup-step">
            <div className="setup-header">
              <div className="setup-icon">🔮</div>
              <h1>欢迎使用 OmniCouncil</h1>
              <p className="setup-subtitle">
                OmniCouncil 需要连接到 AI 网站来获取回答。<br />
                请选择连接模式：
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

            <button className="setup-skip" onClick={() => handleComplete()}>
              跳过，稍后设置
            </button>
          </div>
        )}

        {/* Step 2: CDP Mode Setup */}
        {step === 'cdp' && (
          <div className="setup-step">
            <div className="setup-header">
              <div className="setup-icon">🖥️</div>
              <h1>连接本地 Chrome</h1>
            </div>

            <div className="setup-instructions">
              <div className="instruction-step">
                <span className="step-number">1</span>
                <span>关闭所有 Chrome 窗口</span>
              </div>
              <div className="instruction-step">
                <span className="step-number">2</span>
                <span>点击下方按钮启动调试模式 Chrome</span>
              </div>

              <button
                className={`launch-chrome-btn ${chromeStatus}`}
                onClick={handleLaunchChrome}
                disabled={chromeStatus === 'launching' || chromeStatus === 'connected'}
              >
                {chromeStatus === 'idle' && '🚀 一键启动 Chrome (调试模式)'}
                {chromeStatus === 'launching' && '⏳ 启动中...'}
                {chromeStatus === 'connected' && '✅ Chrome 已连接'}
                {chromeStatus === 'error' && '❌ 启动失败，重试'}
              </button>

              {chromeStatus === 'idle' && (
                <div className="command-hint">
                  执行命令: <code>chrome.exe --remote-debugging-port=9222</code>
                </div>
              )}

              <div className="instruction-step">
                <span className="step-number">3</span>
                <span>在弹出的 Chrome 中登录 DeepSeek / 千问</span>
              </div>
            </div>

            <div className="setup-status">
              {chromeStatus === 'connected' ? (
                <div className="status-success">
                  ✅ Chrome 已连接<br />
                  <span className="status-detail">请在 Chrome 中登录 AI 网站，完成后点击下方按钮</span>
                </div>
              ) : (
                <div className="status-waiting">
                  🔄 等待 Chrome 启动...
                </div>
              )}
            </div>

            <div className="setup-actions">
              <button className="setup-back" onClick={() => setStep('mode')}>← 返回</button>
              <button
                className="setup-next"
                onClick={handleComplete}
                disabled={chromeStatus !== 'connected'}
              >
                完成设置 →
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Embedded Chromium Setup */}
        {step === 'embedded' && (
          <div className="setup-step">
            <div className="setup-header">
              <div className="setup-icon">🔒</div>
              <h1>登录 AI 账号</h1>
              <p className="setup-subtitle">
                OmniCouncil 将使用内置浏览器访问 AI 网站。<br />
                请在下方完成登录：
              </p>
            </div>

            <div className="login-cards">
              <div className="login-card">
                <div className="login-header">
                  <span className="login-ai-name">DeepSeek</span>
                  <span className="login-status">未登录</span>
                </div>
                <div className="login-iframe">
                  {/* In Tauri, this would be a WebView */}
                  <div className="login-placeholder">
                    内嵌 Chromium 将在此显示 DeepSeek 登录页
                  </div>
                </div>
              </div>

              <div className="login-card">
                <div className="login-header">
                  <span className="login-ai-name">千问</span>
                  <span className="login-status">未登录</span>
                </div>
                <div className="login-iframe">
                  <div className="login-placeholder">
                    内嵌 Chromium 将在此显示千问登录页
                  </div>
                </div>
              </div>
            </div>

            <div className="setup-privacy">
              🔒 登录信息仅保存在本地，不会上传到任何服务器
            </div>

            <div className="setup-actions">
              <button className="setup-back" onClick={() => setStep('mode')}>← 返回</button>
              <button className="setup-skip" onClick={() => handleComplete()}>跳过</button>
              <button className="setup-next" onClick={handleComplete()}>
                完成设置 →
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
