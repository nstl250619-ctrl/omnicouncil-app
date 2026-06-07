import { useState, useEffect } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { useAppStore } from './stores/appStore';
import { useConfigStore } from './stores/configStore';
import { PlatformSetupPage } from './pages/PlatformSetupPage';
import { ConsolePage } from './pages/ConsolePage';
import { AIPlatformManager } from './components/AIPlatformManager';
import { ErrorToast } from './components/ErrorToast';

type Page = 'platform-setup' | 'console';

function App() {
  const { send } = useWebSocket();
  const { isFirstLaunch, setupCompleted, completeSetup, loadConfig } = useConfigStore();
  const [configLoaded, setConfigLoaded] = useState(false);
  const [currentPage, setCurrentPage] = useState<Page>('console');
  const [error, setError] = useState<{ message: string; recoverable: boolean; suggestion?: string } | null>(null);

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

  // Show AI Platform Manager on first launch (legacy setup wizard)
  if (configLoaded && (isFirstLaunch || !setupCompleted)) {
    return (
      <AIPlatformManager
        isSetupMode={true}
        send={send}
        onComplete={() => {
          completeSetup();
        }}
      />
    );
  }

  return (
    <div className="app-wrapper">
      {currentPage === 'platform-setup' ? (
        <PlatformSetupPage onNavigateToConsole={() => setCurrentPage('console')} />
      ) : (
        <ConsolePage onNavigateToPlatforms={() => setCurrentPage('platform-setup')} />
      )}
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
