import { renderHook, act, waitFor } from '@testing-library/react';
import { useWebSocket } from '../../hooks/useWebSocket';

// Mock WebSocket
class MockWebSocket {
  constructor(url) {
    this.url = url;
    this.readyState = WebSocket.CONNECTING;
    this.onopen = null;
    this.onclose = null;
    this.onerror = null;
    this.onmessage = null;
    this.sentMessages = [];

    // 模拟连接成功
    setTimeout(() => {
      this.readyState = WebSocket.OPEN;
      if (this.onopen) this.onopen();
    }, 0);
  }

  send(data) {
    this.sentMessages.push(JSON.parse(data));
  }

  close(code) {
    this.readyState = WebSocket.CLOSED;
    if (this.onclose) this.onclose({ code });
  }

  // 模拟接收消息
  simulateMessage(data) {
    if (this.onmessage) {
      this.onmessage({ data: JSON.stringify(data) });
    }
  }
}

global.WebSocket = MockWebSocket;

describe('useWebSocket', () => {
  const WS_URL = 'ws://localhost:8000/voice/chat';

  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  test('should establish WebSocket connection', async () => {
    const { result } = renderHook(() =>
      useWebSocket(WS_URL)
    );

    expect(result.current.isConnected).toBe(false);

    // Advance timers to allow MockWebSocket's setTimeout(0) to fire
    await act(async () => {
      jest.advanceTimersByTime(1);
    });

    await waitFor(() => {
      expect(result.current.isConnected).toBe(true);
    });
  });

  test('should send messages', async () => {
    const wsInstances = [];
    const OriginalWebSocket = global.WebSocket;

    global.WebSocket = function (url) {
      const ws = new OriginalWebSocket(url);
      wsInstances.push(ws);
      return ws;
    };
    global.WebSocket.CONNECTING = 0;
    global.WebSocket.OPEN = 1;
    global.WebSocket.CLOSED = 3;

    const { result } = renderHook(() =>
      useWebSocket(WS_URL)
    );

    // Wait for connection
    await act(async () => {
      jest.advanceTimersByTime(1);
    });

    await waitFor(() => {
      expect(result.current.isConnected).toBe(true);
    });

    const testMessage = { type: 'test', data: 'hello' };
    act(() => {
      result.current.sendMessage(testMessage);
    });

    expect(wsInstances[0].sentMessages).toContainEqual(testMessage);
  });

  test('should handle received messages', async () => {
    const onMessage = jest.fn();
    const wsInstances = [];
    const OriginalWebSocket = global.WebSocket;

    global.WebSocket = function (url) {
      const ws = new OriginalWebSocket(url);
      wsInstances.push(ws);
      return ws;
    };
    global.WebSocket.CONNECTING = 0;
    global.WebSocket.OPEN = 1;
    global.WebSocket.CLOSED = 3;

    const { result } = renderHook(() =>
      useWebSocket(WS_URL, { onMessage })
    );

    // Wait for connection
    await act(async () => {
      jest.advanceTimersByTime(1);
    });

    await waitFor(() => {
      expect(result.current.isConnected).toBe(true);
    });

    const testMessage = { type: 'stt_final', text: 'test text' };
    act(() => {
      wsInstances[0].simulateMessage(testMessage);
    });

    expect(onMessage).toHaveBeenCalledWith(testMessage);
  });

  test('should disconnect', async () => {
    const { result } = renderHook(() =>
      useWebSocket(WS_URL)
    );

    // Wait for connection
    await act(async () => {
      jest.advanceTimersByTime(1);
    });

    await waitFor(() => {
      expect(result.current.isConnected).toBe(true);
    });

    act(() => {
      result.current.disconnect();
    });

    expect(result.current.isConnected).toBe(false);
  });
});
