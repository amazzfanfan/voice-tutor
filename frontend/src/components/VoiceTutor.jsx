import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useAudioCapture } from '../hooks/useAudioCapture';
import { useAudioPlayer } from '../hooks/useAudioPlayer';
import { useVoiceState } from '../hooks/useVoiceState';
import { VOICE_STATUS } from '../utils/constants';
import {
  SERVER_MESSAGES,
  createStartSessionMessage,
  createAudioDataMessage,
  createStopAudioMessage,
  createInterruptMessage,
  createPlaybackFinishedMessage,
  createEndSessionMessage,
  createSwitchVoiceMessage,
} from '../utils/protocol';
import StatusIndicator from './StatusIndicator';
import VoiceButton from './VoiceButton';
import SubtitleDisplay from './SubtitleDisplay';
import VoiceSelector from './VoiceSelector';
import ChatHistory from './ChatHistory';
import '../styles/VoiceTutor.css';

// WebSocket URL
const WS_URL = 'ws://localhost:18000/voice/chat';

function VoiceTutor() {
  const {
    state,
    setStatus,
    setSessionId,
    setPartialText,
    setAgentText,
    setCurrentVoice,
    setError,
    addToChatHistory,
    clearText,
  } = useVoiceState();

  // Audio playback
  const { isPlaying, playAudioChunk, stopPlaying } = useAudioPlayer();

  // 跟踪后端是否已发送 is_last 音频块
  const isLastReceivedRef = useRef(false);

  // WebSocket ref for manual connection
  const wsRef = useRef(null);

  // Send message helper
  const sendMessage = useCallback((message) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      console.log('Sending message:', message.type);
      wsRef.current.send(JSON.stringify(message));
      return true;
    }
    console.warn('WebSocket not connected, cannot send message');
    return false;
  }, []);

  // Audio capture
  const handleAudioData = useCallback(
    (base64Audio) => {
      sendMessage(createAudioDataMessage(base64Audio));
    },
    [sendMessage]
  );

  const handleSpeechEnd = useCallback(() => {
    sendMessage(createStopAudioMessage());
  }, [sendMessage]);

  const { isCapturing, startCapture, stopCapture } = useAudioCapture({
    onAudioData: handleAudioData,
    onSpeechEnd: handleSpeechEnd,
  });

  // 当音频播放完毕且收到最后一个音频块时，通知后端可以重新开启麦克风
  // 条件：isPlaying=false（队列清空，所有音频播完）AND isLastReceived=true（后端已确认没有更多音频）
  // 不需要安全超时：空音频块被跳过 → 队列自然排空 → onended 触发 → isPlaying=false → 此时 effect 触发
  useEffect(() => {
    console.log(`[VoiceTutor] playback effect: isPlaying=${isPlaying}, isLastReceived=${isLastReceivedRef.current}, status=${state.status}`);
    if (!isPlaying && isLastReceivedRef.current && state.status === VOICE_STATUS.SPEAKING) {
      console.log('[VoiceTutor] ✅ Audio playback truly finished, sending playback_finished');
      sendMessage(createPlaybackFinishedMessage());
    }
  }, [isPlaying, state.status, sendMessage]);

  // Handle incoming WebSocket messages
  const handleWebSocketMessage = useCallback(
    (message) => {
      switch (message.type) {
        case SERVER_MESSAGES.SESSION_STARTED:
          setSessionId(message.session_id);
          setStatus(VOICE_STATUS.LISTENING);
          break;

        case SERVER_MESSAGES.STT_PARTIAL:
          setPartialText(message.text);
          break;

        case SERVER_MESSAGES.STT_FINAL:
          setPartialText('');
          addToChatHistory('user', message.text);
          setStatus(VOICE_STATUS.PROCESSING);
          break;

        case SERVER_MESSAGES.AGENT_THINKING:
          setStatus(VOICE_STATUS.PROCESSING);
          break;

        case SERVER_MESSAGES.AGENT_TEXT:
          setAgentText(message.text);
          if (message.is_final) {
            addToChatHistory('ai', message.text);
          }
          break;

        case SERVER_MESSAGES.AUDIO_CHUNK:
          console.log(`[VoiceTutor] 📦 Received audio chunk, audio length=${message.audio?.length || 0}`);
          // 首个真实音频块到达且当前未播放 → 新一轮播放开始
          if (!isPlaying) {
            isLastReceivedRef.current = false;
          }
          playAudioChunk(message.audio);
          setStatus(VOICE_STATUS.SPEAKING);
          break;

        case SERVER_MESSAGES.AUDIO_STREAM_END:
          // 所有 TTS 音频块已发送完毕，使用独立消息类型确保不被 WebSocket 堵塞
          console.log('[VoiceTutor] 🔚 Received audio_stream_end');
          isLastReceivedRef.current = true;
          break;

        case SERVER_MESSAGES.STOP_CAPTURE:
          console.log('[VoiceTutor] 🎤 Received STOP_CAPTURE from backend');
          stopCapture();
          break;

        case SERVER_MESSAGES.START_CAPTURE:
          console.log('[VoiceTutor] 🎤 Received START_CAPTURE from backend');
          setStatus(VOICE_STATUS.LISTENING);
          startCapture();
          break;

        case SERVER_MESSAGES.SESSION_ENDED:
          setStatus(VOICE_STATUS.IDLE);
          clearText();
          isLastReceivedRef.current = false;
          break;

        case SERVER_MESSAGES.ERROR:
          setError(message.message);
          break;

        default:
          break;
      }
    },
    [
      setStatus,
      setSessionId,
      setPartialText,
      setAgentText,
      setError,
      addToChatHistory,
      clearText,
      playAudioChunk,
      stopCapture,
      startCapture,
    ]
  );

  const [isConnected, setIsConnected] = useState(false);

  // Handle button click
  const handleButtonClick = useCallback(async () => {
    if (state.status === VOICE_STATUS.IDLE) {
      // Start conversation
      try {
        // 创建 WebSocket 连接
        const ws = new WebSocket(WS_URL);

        ws.onopen = () => {
          console.log('WebSocket connected, sending start_session');
          wsRef.current = ws;
          setIsConnected(true);

          // 发送 start_session 消息
          ws.send(JSON.stringify(createStartSessionMessage(
            'USR-10001',
            state.currentVoice,
            state.chatHistory
          )));
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            console.log('Received message:', data.type);

            // 收到 session_started 后，先更新状态，再捕获音频
            if (data.type === SERVER_MESSAGES.SESSION_STARTED) {
              console.log('Session started, setting status to LISTENING');
              setStatus(VOICE_STATUS.LISTENING);
              setSessionId(data.session_id);

              // 等待状态更新后再开始捕获音频
              setTimeout(() => {
                console.log('Now capturing audio');
                startCapture();
              }, 100);
              return; // 不再调用 handleWebSocketMessage
            }

            handleWebSocketMessage(data);
          } catch (e) {
            console.error('Failed to parse WebSocket message', e);
          }
        };

        ws.onclose = (event) => {
          console.log('WebSocket closed', event.code);
          setIsConnected(false);
          wsRef.current = null;
        };

        ws.onerror = (error) => {
          console.error('WebSocket error', error);
          setError('WebSocket连接失败');
        };
      } catch (error) {
        console.error('Failed to start conversation', error);
        setError('开始对话失败，请重试');
      }
    } else {
      // End conversation
      sendMessage(createEndSessionMessage());
      stopCapture();
      stopPlaying();
      if (wsRef.current) {
        wsRef.current.close(1000);
        wsRef.current = null;
        setIsConnected(false);
      }
      setStatus(VOICE_STATUS.IDLE);
    }
  }, [
    state.status,
    state.currentVoice,
    state.chatHistory,
    startCapture,
    stopCapture,
    stopPlaying,
    sendMessage,
    setStatus,
    setError,
    handleWebSocketMessage,
  ]);

  // Handle voice change
  const handleVoiceChange = useCallback(
    (voiceId) => {
      setCurrentVoice(voiceId);
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        sendMessage(createSwitchVoiceMessage(voiceId));
      }
    },
    [sendMessage, setCurrentVoice]
  );

  // 自动打断检测 (需要集成VAD后启用，暂时禁用)
  // useEffect(() => {
  //   if (state.status === VOICE_STATUS.SPEAKING && isCapturing) {
  //     const handleVoiceActivity = () => {
  //       if (state.status === VOICE_STATUS.SPEAKING) {
  //         sendMessage(createInterruptMessage());
  //         setStatus(VOICE_STATUS.LISTENING);
  //       }
  //     };
  //     const timer = setTimeout(handleVoiceActivity, 2000);
  //     return () => clearTimeout(timer);
  //   }
  // }, [state.status, isCapturing, sendMessage, setStatus]);

  // 清理函数
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close(1000);
        wsRef.current = null;
      }
      stopCapture();
      stopPlaying();
    };
  }, [stopCapture, stopPlaying]);

  return (
    <div className="voice-tutor">
      <header className="voice-tutor-header">
        <h1>AI语音导师</h1>
        <p>工业领域专业讲师，语音交互学习助手</p>
      </header>

      <main className="voice-tutor-content">
        <div className="left-panel">
          <ChatHistory chatHistory={state.chatHistory} />
        </div>

        <div className="right-panel">
          <div className="voice-area">
            <StatusIndicator status={state.status} />

            <VoiceButton
              status={state.status}
              onClick={handleButtonClick}
            />

            <SubtitleDisplay
              status={state.status}
              partialText={state.partialText}
              agentText={state.agentText}
            />

            <div className="voice-hint">
              直接说话即可打断，点击按钮结束对话
            </div>

            <VoiceSelector
              currentVoice={state.currentVoice}
              onVoiceChange={handleVoiceChange}
            />
          </div>
        </div>
      </main>
    </div>
  );
}

export default VoiceTutor;
