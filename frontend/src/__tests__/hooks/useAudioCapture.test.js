import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { useAudioCapture } from '../../hooks/useAudioCapture';

// Mock getUserMedia
const mockGetUserMedia = jest.fn();
navigator.mediaDevices = {
  getUserMedia: mockGetUserMedia,
};

// Mock AudioWorkletNode
class MockAudioWorkletNode {
  constructor() {
    this.port = {
      onmessage: null,
      postMessage: jest.fn(),
    };
  }
  connect() {}
  disconnect() {}
}

// Mock AudioContext
class MockAudioContext {
  constructor() {
    this.state = 'running';
    this.audioWorklet = {
      addModule: jest.fn().mockResolvedValue(undefined),
    };
  }
  createMediaStreamSource() {
    return {
      connect: jest.fn(),
    };
  }
  close() {}
}
window.AudioContext = MockAudioContext;
window.AudioWorkletNode = MockAudioWorkletNode;

// 测试组件
function TestComponent({ onAudioData }) {
  const { isCapturing, startCapture, stopCapture } = useAudioCapture({ onAudioData });

  return (
    <div>
      <span data-testid="capturing">{isCapturing.toString()}</span>
      <button onClick={startCapture}>Start</button>
      <button onClick={stopCapture}>Stop</button>
    </div>
  );
}

describe('useAudioCapture', () => {
  beforeEach(() => {
    mockGetUserMedia.mockResolvedValue({
      getTracks: () => [{ stop: jest.fn() }],
    });
  });

  test('应该能够开始采集', async () => {
    const onAudioData = jest.fn();
    render(<TestComponent onAudioData={onAudioData} />);

    expect(screen.getByTestId('capturing').textContent).toBe('false');

    await act(async () => {
      fireEvent.click(screen.getByText('Start'));
    });

    expect(screen.getByTestId('capturing').textContent).toBe('true');
  });

  test('应该能够停止采集', async () => {
    const onAudioData = jest.fn();
    render(<TestComponent onAudioData={onAudioData} />);

    await act(async () => {
      fireEvent.click(screen.getByText('Start'));
    });

    await act(async () => {
      fireEvent.click(screen.getByText('Stop'));
    });

    expect(screen.getByTestId('capturing').textContent).toBe('false');
  });
});
