import { useState, useEffect } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { useAppStore } from './stores/appStore';
import { useConfigStore } from './stores/configStore';
import { Header } from './components/Header';
import { QueryInput } from './components/QueryInput';
import { TabBar } from './components/TabBar';
import { ResponsesTab } from './components/ResponsesTab';
import { ComparisonTab } from './components/ComparisonTab';
import { ConsensusTab } from './components/ConsensusTab';
import { ConflictTab } from './components/ConflictTab';
import { StatusBar } from './components/StatusBar';
import { SetupWizard } from './components/SetupWizard';
import { Settings } from './components/Settings';

function App() {
  useWebSocket();

  const activeTab = useAppStore((s) => s.activeTab);
  const { isFirstLaunch, setupCompleted, completeSetup, loadConfig } = useConfigStore();
  const [showSettings, setShowSettings] = useState(false);
  const [configLoaded, setConfigLoaded] = useState(false);

  // Load config on mount
  useEffect(() => {
    loadConfig().then(() => setConfigLoaded(true));
  }, [loadConfig]);

  // Show setup wizard on first launch
  if (configLoaded && (isFirstLaunch || !setupCompleted)) {
    return <SetupWizard onComplete={completeSetup} />;
  }

  return (
    <div className="app">
      <Header onSettingsClick={() => setShowSettings(true)} />
      <QueryInput />
      <TabBar />
      <div className="tab-content">
        {activeTab === 'responses' && <ResponsesTab />}
        {activeTab === 'comparison' && <ComparisonTab />}
        {activeTab === 'consensus' && <ConsensusTab />}
        {activeTab === 'conflict' && <ConflictTab />}
      </div>
      <StatusBar />
      {showSettings && <Settings onClose={() => setShowSettings(false)} />}
    </div>
  );
}

export default App;
