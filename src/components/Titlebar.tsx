import { useState, useEffect } from 'react';

interface TitlebarProps {
  statusText?: string;
}

export default function Titlebar({ statusText = '就绪' }: TitlebarProps) {
  const [isMaximized, setIsMaximized] = useState(false);

  useEffect(() => {
    // Listen for window resize to update maximize state
    const update = async () => {
      try {
        const { getCurrentWindow } = await import('@tauri-apps/api/window');
        const win = getCurrentWindow();
        setIsMaximized(await win.isMaximized());
      } catch {
        // Not in Tauri environment
      }
    };
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  const handleMinimize = async () => {
    try {
      const { getCurrentWindow } = await import('@tauri-apps/api/window');
      await getCurrentWindow().minimize();
    } catch { /* not in tauri */ }
  };

  const handleToggleMaximize = async () => {
    try {
      const { getCurrentWindow } = await import('@tauri-apps/api/window');
      await getCurrentWindow().toggleMaximize();
    } catch { /* not in tauri */ }
  };

  const handleClose = async () => {
    try {
      const { getCurrentWindow } = await import('@tauri-apps/api/window');
      await getCurrentWindow().close();
    } catch { /* not in tauri */ }
  };

  return (
    <div
      data-tauri-drag-region
      className="titlebar"
    >
      {/* Left: Brand + Status */}
      <div className="titlebar-left" data-tauri-drag-region>
        <div className="titlebar-logo">
          <span className="titlebar-logo-text">Ω</span>
        </div>
        <span className="titlebar-brand">OMNICOUNCIL</span>
        <span className={`titlebar-status-dot ${statusText === '分析中...' ? 'pulse' : ''}`} />
        <span className="titlebar-status-text">{statusText}</span>
      </div>

      {/* Center: Drag area */}
      <div className="titlebar-center" data-tauri-drag-region onDoubleClick={handleToggleMaximize} />

      {/* Right: Window controls */}
      <div className="titlebar-controls">
        <button className="titlebar-btn" onClick={handleMinimize} title="最小化">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M20 12H4" />
          </svg>
        </button>
        <button className="titlebar-btn" onClick={handleToggleMaximize} title={isMaximized ? '还原' : '最大化'}>
          {isMaximized ? (
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M8 16H4V4h12v4M16 8h4v12H8v-4" />
            </svg>
          ) : (
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <rect x="4" y="4" width="16" height="16" />
            </svg>
          )}
        </button>
        <button className="titlebar-btn close" onClick={handleClose} title="关闭">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  );
}
