import { useEffect, useState } from 'react';

interface ErrorToastProps {
  error: string;
  recoverable: boolean;
  suggestion?: string;
  onRetry?: () => void;
  onDismiss: () => void;
  autoHideMs?: number;
  severity?: 'error' | 'warning' | 'success';
}

export function ErrorToast({ error, recoverable, suggestion, onRetry, onDismiss, autoHideMs = 5000, severity = 'error' }: ErrorToastProps) {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setVisible(false);
      setTimeout(onDismiss, 300);
    }, autoHideMs);
    return () => clearTimeout(timer);
  }, [autoHideMs, onDismiss]);

  const iconMap = {
    error: '⚠️',
    warning: '⚡',
    success: '✅',
  };

  return (
    <div className={`error-toast ${visible ? 'show' : 'hide'} toast-${severity}`}>
      <div className="error-toast-icon">{iconMap[severity]}</div>
      <div className="error-toast-content">
        <div className="error-toast-message">{error}</div>
        {suggestion && <div className="error-toast-suggestion">{suggestion}</div>}
      </div>
      <div className="error-toast-actions">
        {recoverable && onRetry && (
          <button className="error-toast-btn retry" onClick={onRetry}>重试</button>
        )}
        <button className="error-toast-btn dismiss" onClick={onDismiss}>✕</button>
      </div>
    </div>
  );
}
