import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { useAudioPlayer } from '../../hooks/useAudioPlayer';

const audioContexts = [];
const audioSources = [];

// Mock AudioContext
class MockAudioBuffer {
  constructor() {
    this.getChannelData = jest.fn().mockReturnValue(new Float32Array(1024));
  }
}

class MockAudioBufferSource {
  constructor() {
    this.buffer = null;
    this.onended = null;
    this.start = jest.fn();
    this.stop = jest.fn();
    this.connect = jest.fn();
    audioSources.push(this);
  }
}

class MockAudioContext {
  constructor() {
    this.state = 'running';
    this.destination = {};
    this.close = jest.fn().mockResolvedValue(undefined);
    this.resume = jest.fn().mockResolvedValue(undefined);
    audioContexts.push(this);
  }
  createBuffer(channels, length, sampleRate) {
    return new MockAudioBuffer();
  }
  createBufferSource() {
    return new MockAudioBufferSource();
  }
}
window.AudioContext = MockAudioContext;

// 测试组件
function TestComponent() {
  const { isPlaying, playAudioChunk, stopPlaying } = useAudioPlayer();

  return (
    <div>
      <span data-testid="playing">{isPlaying.toString()}</span>
      <button onClick={() => playAudioChunk('dGVzdA==')}>Play</button>
      <button onClick={stopPlaying}>Stop</button>
    </div>
  );
}

describe('useAudioPlayer', () => {
  beforeEach(() => {
    audioContexts.length = 0;
    audioSources.length = 0;
  });

  test('应该能够播放音频', async () => {
    render(<TestComponent />);

    expect(screen.getByTestId('playing').textContent).toBe('false');

    await act(async () => {
      fireEvent.click(screen.getByText('Play'));
    });

    expect(screen.getByTestId('playing').textContent).toBe('true');
  });

  test('应该能够停止播放', async () => {
    render(<TestComponent />);

    await act(async () => {
      fireEvent.click(screen.getByText('Play'));
    });

    act(() => {
      fireEvent.click(screen.getByText('Stop'));
    });

    expect(screen.getByTestId('playing').textContent).toBe('false');
    expect(audioSources[0].stop).toHaveBeenCalledTimes(1);
    expect(audioContexts[0].close).toHaveBeenCalledTimes(1);
  });

  test('长回复的多个音频块应该复用同一个 AudioContext', async () => {
    render(<TestComponent />);

    act(() => {
      fireEvent.click(screen.getByText('Play'));
      fireEvent.click(screen.getByText('Play'));
    });

    expect(audioContexts).toHaveLength(1);
    expect(audioSources).toHaveLength(1);

    act(() => {
      audioSources[0].onended();
    });

    expect(audioSources).toHaveLength(2);
    expect(audioContexts).toHaveLength(1);
  });
});
