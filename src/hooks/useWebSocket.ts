import { useEffect, useRef, useCallback } from 'react';
import { useAppStore } from '../stores/appStore';

const WS_URL = 'ws://127.0.0.1:8765/ws';
const RECONNECT_DELAY = 2000;
const HEARTBEAT_INTERVAL = 15000;

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>();
  const heartbeatIntervalRef = useRef<ReturnType<typeof setInterval>>();

  const setConnectionStatus = useAppStore((s) => s.setConnectionStatus);
  const handleMessage = useAppStore((s) => s.handleMessage);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[WS] Connected');
      setConnectionStatus('connected');

      // Start heartbeat
      heartbeatIntervalRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping', data: {} }));
        }
      }, HEARTBEAT_INTERVAL);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleMessage(msg);
      } catch (e) {
        console.error('[WS] Failed to parse message:', e);
      }
    };

    ws.onclose = () => {
      console.log('[WS] Disconnected');
      setConnectionStatus('disconnected');
      clearInterval(heartbeatIntervalRef.current);

      // Auto reconnect
      reconnectTimeoutRef.current = setTimeout(() => {
        console.log('[WS] Reconnecting...');
        setConnectionStatus('reconnecting');
        connect();
      }, RECONNECT_DELAY);
    };

    ws.onerror = (error) => {
      console.error('[WS] Error:', error);
    };
  }, [setConnectionStatus, handleMessage]);

  const disconnect = useCallback(() => {
    clearTimeout(reconnectTimeoutRef.current);
    clearInterval(heartbeatIntervalRef.current);
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  const send = useCallback((type: string, data: Record<string, unknown> = {}) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type, data }));
    } else {
      console.warn('[WS] Not connected, cannot send');
    }
  }, []);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return { send, disconnect };
}
