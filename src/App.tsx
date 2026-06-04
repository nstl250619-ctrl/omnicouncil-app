import { useState, useEffect } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { useAppStore } from './stores/appStore';
import { useConfigStore } from './stores/configStore';
import Titlebar from './components/Titlebar';
import { QueryInput } from './components/QueryInput';
import { TabBar } from './components/TabBar';
import { ResponsesTab } from './components/ResponsesTab';
import { ComparisonTab } from './components/ComparisonTab';
import { ConsensusTab } from './components/ConsensusTab';
import { ConflictTab } from './components/ConflictTab';
import { HistoryView } from './components/HistoryView';
import { StatusBar } from './components/StatusBar';
import { SetupWizard } from './components/SetupWizard';
import { Settings } from './components/Settings';
import { ErrorToast } from './components/ErrorToast';

function App() {
  useWebSocket();

  const activeTab = useAppStore((s) => s.activeTab);
  const connectionStatus = useAppStore((s) => s.connectionStatus);
  const responses = useAppStore((s) => s.responses);
  const { isFirstLaunch, setupCompleted, completeSetup, loadConfig } = useConfigStore();
  const [showSettings, setShowSettings] = useState(false);
  const [configLoaded, setConfigLoaded] = useState(false);
  const [error, setError] = useState<{ message: string; recoverable: boolean; suggestion?: string } | null>(null);

  // Compute titlebar status
  const isRunning = Object.values(responses).some((r) => r.status === 'waiting' || r.status === 'streaming');
  const titlebarStatus = isRunning ? '分析中...' : connectionStatus === 'connected' ? '就绪' : '未连接';

  // Listen for errors from WebSocket
  useEffect(() => {
    const unsubscribe = useAppStore.subscribe((state, prevState) => {
      const responses = state.responses;
      const prevResponses = prevState.responses;
      for (const aiId of Object.keys(responses)) {
        const current = responses[aiId];
        const prev = prevResponses[aiId];
        if (current?.status === 'error' && prev?.status !== 'error') {
          setError({
            message: current.error || '未知错误',
            recoverable: true,
            suggestion: '请检查网络连接后重试',
          });
        }
      }
    });
    return unsubscribe;
  }, []);

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
      <Titlebar statusText={titlebarStatus} />
      <QueryInput />
      <TabBar />
      <div className="tab-content">
        {activeTab === 'responses' && <ResponsesTab />}
        {activeTab === 'comparison' && <ComparisonTab />}
        {activeTab === 'consensus' && <ConsensusTab />}
        {activeTab === 'conflict' && <ConflictTab />}
        {activeTab === 'history' && <HistoryView />}
      </div>
      <StatusBar />
      {showSettings && <Settings onClose={() => setShowSettings(false)} />}
      {error && (
        <ErrorToast
          error={error.message}
          recoverable={error.recoverable}
          suggestion={error.suggestion}
          onRetry={() => setError(null)}
          onDismiss={() => setError(null)}
        />
      )}
    </div>
  );
}

export default App;
