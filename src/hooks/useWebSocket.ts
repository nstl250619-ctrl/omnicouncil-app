import { useEffect, useRef, useCallback } from 'react';
import { useAppStore } from '../stores/appStore';

const WS_URL = 'ws://127.0.0.1:8765/ws';
const RECONNECT_DELAY = 2000;
const HEARTBEAT_INTERVAL = 15000;

export interface HealthEvent {
  type: 'session_expired' | 'recovery_success' | 'ai_unavailable'
    | 'session:login_required' | 'session:recovery_pending'
    | 'session:recovery_in_progress' | 'selector:degraded';
  ai_id: string;
  platform?: string;
  message: string;
}

export function useWebSocket(onHealthEvent?: (event: HealthEvent) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>();
  const heartbeatIntervalRef = useRef<ReturnType<typeof setInterval>>();

  const setConnectionStatus = useAppStore((s) => s.setConnectionStatus);
  const handleMessage = useAppStore((s) => s.handleMessage);

  // Stable refs so the effect doesn't re-run when store functions change
  const setConnectionStatusRef = useRef(setConnectionStatus);
  const handleMessageRef = useRef(handleMessage);
  setConnectionStatusRef.current = setConnectionStatus;
  handleMessageRef.current = handleMessage;

  const send = useCallback((type: string, data: Record<string, unknown> = {}) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type, data }));
    } else {
      console.warn('[WS] Not connected, cannot send');
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let currentWs: WebSocket | null = null;

    const doConnect = () => {
      if (cancelled) return;

      const ws = new WebSocket(WS_URL);
      currentWs = ws;
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelled) { ws.close(); return; }
        console.log('[WS] Connected');
        setConnectionStatusRef.current('connected');

        heartbeatIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping', data: {} }));
          }
        }, HEARTBEAT_INTERVAL);
      };

      ws.onmessage = (event) => {
        if (cancelled) return;
        try {
          const msg = JSON.parse(event.data);

          // Fire health event callback for toast notifications
          if (onHealthEvent && ['session_expired', 'recovery_success', 'ai_unavailable'].includes(msg.type)) {
            onHealthEvent({
              type: msg.type as HealthEvent['type'],
              ai_id: msg.data?.ai_id ?? '',
              message: msg.data?.message ?? '',
            });
          }

          handleMessageRef.current(msg);
        } catch (e) {
          console.error('[WS] Failed to parse message:', e);
        }
      };

      ws.onclose = () => {
        clearInterval(heartbeatIntervalRef.current);

        // Only handle close for the current connection, not stale ones
        if (cancelled || ws !== currentWs) return;

        console.log('[WS] Disconnected');
        setConnectionStatusRef.current('disconnected');
        wsRef.current = null;

        reconnectTimeoutRef.current = setTimeout(() => {
          if (cancelled) return;
          console.log('[WS] Reconnecting...');
          setConnectionStatusRef.current('reconnecting');
          doConnect();
        }, RECONNECT_DELAY);
      };

      ws.onerror = (error) => {
        if (!cancelled) console.error('[WS] Error:', error);
      };
    };

    doConnect();

    return () => {
      cancelled = true;
      clearTimeout(reconnectTimeoutRef.current);
      clearInterval(heartbeatIntervalRef.current);
      if (currentWs) {
        currentWs.close();
        currentWs = null;
      }
      wsRef.current = null;
    };
  }, []); // Empty deps — run once on mount, cleanup on unmount only

  return { send };
}
