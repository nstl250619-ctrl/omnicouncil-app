import { useAppStore } from '../stores/appStore';

export function StatusBar() {
  const connectionStatus = useAppStore((s) => s.connectionStatus);
  const responses = useAppStore((s) => s.responses);
  const currentTaskId = useAppStore((s) => s.currentTaskId);

  const total = Object.keys(responses).length;
  const completed = Object.values(responses).filter((r) => r.status === 'completed').length;
  const failed = Object.values(responses).filter((r) => r.status === 'error').length;
  const isRunning = Object.values(responses).some((r) => r.status === 'waiting' || r.status === 'streaming');

  const statusIcon = connectionStatus === 'connected' ? '✅' : connectionStatus === 'reconnecting' ? '🔄' : '❌';
  const statusText = connectionStatus === 'connected' ? '已连接' : connectionStatus === 'reconnecting' ? '重连中...' : '未连接';

  return (
    <footer className="status-bar">
      <span>{statusIcon} {statusText}</span>
      {total > 0 && (
        <span>
          {isRunning ? `⏳ 分析中 (${completed}/${total})` : `✅ 完成 ${completed}/${total}`}
          {failed > 0 && ` · ❌ ${failed} 失败`}
        </span>
      )}
    </footer>
  );
}
