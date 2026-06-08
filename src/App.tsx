import { useState, useEffect, useCallback } from 'react';
import { useWebSocket, type HealthEvent } from './hooks/useWebSocket';
import { useAppStore } from './stores/appStore';
import { PlatformSetupPage } from './pages/PlatformSetupPage';
import { ConsolePage } from './pages/ConsolePage';
import { ErrorToast } from './components/ErrorToast';

type Page = 'platform-setup' | 'console';

/** Toast entry for health events */
interface ToastEntry {
  id: number;
  message: string;
  severity: 'error' | 'warning' | 'success';
  recoverable: boolean;
  suggestion?: string;
  onRetry?: () => void;
}

let toastId = 0;

function App() {
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const [currentPage, setCurrentPage] = useState<Page>('console');

  // Helper to add health toasts
  const addToast = useCallback((entry: Omit<ToastEntry, 'id'>) => {
    const id = ++toastId;
    setToasts((prev) => [...prev, { ...entry, id }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 5000);
  }, []);

  // Health event to toast mapping
  const onHealthEvent = useCallback(
    (event: HealthEvent) => {
      const names: Record<string, string> = {
        deepseek: 'DeepSeek', gemini: 'Gemini', chatgpt: 'ChatGPT',
        qianwen: '千问', mimo: 'MiMo', claude: 'Claude',
      };
      const displayName = names[event.ai_id] || event.ai_id;

      switch (event.type) {
        case 'ai_unavailable':
          addToast({
            message: `${displayName} 不可用，请检查登录状态`,
            severity: 'error',
            recoverable: true,
            suggestion: event.message,
          });
          break;
        case 'recovery_success':
          addToast({
            message: `${displayName} 已自动恢复`,
            severity: 'success',
            recoverable: false,
          });
          break;
        case 'session_expired':
          addToast({
            message: `${displayName} 登录已过期，正在尝试恢复...`,
            severity: 'warning',
            recoverable: true,
            suggestion: event.message,
          });
          break;
      }
    },
    [addToast]
  );

  const { send } = useWebSocket(onHealthEvent);
  const [error, setError] = useState<{ message: string; recoverable: boolean; suggestion?: string } | null>(null);

  // Listen for errors from WebSocket
  useEffect(() => {
    const unsubscribe = useAppStore.subscribe((state, prevState) => {
      const responses = state.responses;
      const prevResponses = prevState.responses;
      for (const aiId of Object.keys(responses)) {
        const current = responses[aiId];
        const prev = prevResponses[aiId];
        if (current && current.status === 'error' && prev && prev.status !== 'error') {
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

  // Render toasts
  const toastElements: React.ReactElement[] = [];
  for (const t of toasts) {
    toastElements.push(
      <ErrorToast
        key={t.id}
        error={t.message}
        recoverable={t.recoverable}
        suggestion={t.suggestion}
        severity={t.severity}
        onDismiss={() => setToasts((prev) => prev.filter((x) => x.id !== t.id))}
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
      {toastElements}
    </div>
  );
}

export default App;
