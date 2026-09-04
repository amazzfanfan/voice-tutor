import { useRef, useState, useCallback, useEffect } from 'react';
import { WS_CONFIG } from '../utils/constants';

export function useWebSocket(url, options = {}) {
  const { onMessage, onOpen, onClose, onError } = options;

  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef(null);

  // 使用 useRef 保存回调的最新引用，避免 connect 重建
  const onMessageRef = useRef(onMessage);
  const onOpenRef = useRef(onOpen);
  const onCloseRef = useRef(onClose);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    onOpenRef.current = onOpen;
  }, [onOpen]);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  // 建立连接
  const connect = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      return;
    }

    const ws = new WebSocket(url);

    ws.onopen = () => {
      console.log('WebSocket connected');
      setIsConnected(true);
      reconnectAttemptsRef.current = 0;
      if (onOpenRef.current) onOpenRef.current();
    };

    ws.onclose = (event) => {
      console.log('WebSocket closed', event.code);
      setIsConnected(false);
      if (onCloseRef.current) onCloseRef.current(event);

      // 尝试重连（指数退避）
      if (event.code !== 1000 && reconnectAttemptsRef.current < WS_CONFIG.MAX_RECONNECT_ATTEMPTS) {
        const delay = WS_CONFIG.RECONNECT_INTERVAL * Math.pow(2, reconnectAttemptsRef.current);
        reconnectTimerRef.current = setTimeout(() => {
          reconnectAttemptsRef.current++;
          connect();
        }, delay);
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket error', error);
      if (onErrorRef.current) onErrorRef.current(error);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (onMessageRef.current) onMessageRef.current(data);
      } catch (e) {
        console.error('Failed to parse WebSocket message', e);
      }
    };

    wsRef.current = ws;
  }, [url]); // 只依赖 url

  // 发送消息
  const sendMessage = useCallback((message) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
      return true;
    }
    return false;
  }, []);

  // 断开连接
  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
    }
    if (wsRef.current) {
      wsRef.current.close(1000);
      wsRef.current = null;
    }
    setIsConnected(false);
  }, []);

  // 组件挂载时自动连接，卸载时断开连接
  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return {
    isConnected,
    connect,
    sendMessage,
    disconnect,
  };
}
