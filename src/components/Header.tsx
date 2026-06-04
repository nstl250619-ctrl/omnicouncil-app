interface HeaderProps {
  onSettingsClick?: () => void;
}

export function Header({ onSettingsClick }: HeaderProps) {
  return (
    <header className="header">
      <div className="header-left">
        <h1 className="header-title">OmniCouncil</h1>
        <span className="header-subtitle">多AI共识决策系统</span>
      </div>
      <div className="header-right">
        <button className="settings-btn" onClick={onSettingsClick} title="设置">
          ⚙️
        </button>
      </div>
    </header>
  );
}
