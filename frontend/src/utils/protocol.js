// 前端发送的消息类型
export const CLIENT_MESSAGES = {
  START_SESSION: 'start_session',
  AUDIO_DATA: 'audio_data',
  STOP_AUDIO: 'stop_audio',
  INTERRUPT: 'interrupt',
  PLAYBACK_FINISHED: 'playback_finished',
  END_SESSION: 'end_session',
  SWITCH_VOICE: 'switch_voice',
  UPDATE_CONFIG: 'update_config',
};

// 后端返回的消息类型
export const SERVER_MESSAGES = {
  SESSION_STARTED: 'session_started',
  STT_PARTIAL: 'stt_partial',
  STT_FINAL: 'stt_final',
  AGENT_THINKING: 'agent_thinking',
  AGENT_TEXT: 'agent_text',
  AUDIO_CHUNK: 'audio_chunk',
  AUDIO_STREAM_END: 'audio_stream_end',
  STOP_CAPTURE: 'stop_capture',
  START_CAPTURE: 'start_capture',
  SESSION_ENDED: 'session_ended',
  ERROR: 'error',
};

// 生成会话ID
export function generateSessionId() {
  return `sess-voice-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

// 创建开始会话消息
export function createStartSessionMessage(userId, voiceId, chatHistory = []) {
  const conversationHistory = chatHistory.slice(-10).map((item) => ({
    role: item.role === 'ai' ? 'assistant' : 'user',
    content: item.text,
  }));

  return {
    type: CLIENT_MESSAGES.START_SESSION,
    user_id: userId,
    session_id: generateSessionId(),
    voice_id: voiceId,
    config: {
      conversation_history: conversationHistory,
    },
  };
}

// 创建音频数据消息
export function createAudioDataMessage(base64Audio) {
  return {
    type: CLIENT_MESSAGES.AUDIO_DATA,
    audio: base64Audio,
    format: 'pcm',
  };
}

// 创建停止本轮语音输入消息
export function createStopAudioMessage() {
  return {
    type: CLIENT_MESSAGES.STOP_AUDIO,
  };
}

// 创建打断消息
export function createInterruptMessage() {
  return {
    type: CLIENT_MESSAGES.INTERRUPT,
  };
}

// 创建播放完成消息
export function createPlaybackFinishedMessage() {
  return {
    type: CLIENT_MESSAGES.PLAYBACK_FINISHED,
  };
}

// 创建结束会话消息
export function createEndSessionMessage() {
  return {
    type: CLIENT_MESSAGES.END_SESSION,
  };
}

// 创建切换音色消息
export function createSwitchVoiceMessage(voiceId) {
  return {
    type: CLIENT_MESSAGES.SWITCH_VOICE,
    voice_id: voiceId,
  };
}
