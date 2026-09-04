import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';

// Shared mock functions accessible from tests
const mockConnect = jest.fn();
const mockSendMessage = jest.fn();
const mockDisconnect = jest.fn();

// Mock hooks
jest.mock('../../hooks/useWebSocket', () => ({
  useWebSocket: () => ({
    isConnected: false,
    connect: mockConnect,
    sendMessage: mockSendMessage,
    disconnect: mockDisconnect,
  }),
}));

jest.mock('../../hooks/useAudioCapture', () => ({
  useAudioCapture: () => ({
    isCapturing: false,
    startCapture: jest.fn(),
    stopCapture: jest.fn(),
  }),
}));

jest.mock('../../hooks/useAudioPlayer', () => ({
  useAudioPlayer: () => ({
    isPlaying: false,
    playAudioChunk: jest.fn(),
    stopPlaying: jest.fn(),
  }),
}));

import VoiceTutor from '../../components/VoiceTutor';

describe('VoiceTutor', () => {
  const OriginalWebSocket = global.WebSocket;

  beforeEach(() => {
    jest.clearAllMocks();
    const socket = {
      readyState: 0,
      send: jest.fn(),
      close: jest.fn(),
      onopen: null,
      onmessage: null,
      onclose: null,
      onerror: null,
    };
    global.WebSocket = jest.fn(() => socket);
    global.WebSocket.OPEN = 1;
  });

  afterAll(() => {
    global.WebSocket = OriginalWebSocket;
  });

  test('should render main interface', () => {
    render(<VoiceTutor />);

    expect(screen.getByText('AI语音导师')).toBeInTheDocument();
    expect(screen.getByText('工业领域专业讲师，语音交互学习助手')).toBeInTheDocument();
    expect(screen.getByText('对话历史')).toBeInTheDocument();
    expect(screen.getByText('开始对话')).toBeInTheDocument();
  });

  test('should render status indicator', () => {
    render(<VoiceTutor />);

    expect(screen.getByText('点击开始对话')).toBeInTheDocument();
  });

  test('should render voice button', () => {
    render(<VoiceTutor />);

    expect(screen.getByLabelText('开始对话')).toBeInTheDocument();
  });

  test('should render voice selector', () => {
    render(<VoiceTutor />);

    expect(screen.getByText('选择声音')).toBeInTheDocument();
    expect(screen.getByDisplayValue('YUMI（默认，正经青年女）')).toBeInTheDocument();
  });

  test('should toggle state on button click', async () => {
    render(<VoiceTutor />);

    await act(async () => {
      fireEvent.click(screen.getByLabelText('开始对话'));
    });

    expect(global.WebSocket).toHaveBeenCalledWith('ws://localhost:18000/voice/chat');
  });
});
