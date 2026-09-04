import { useReducer, useCallback } from 'react';
import { VOICE_STATUS, DEFAULT_VOICE } from '../utils/constants';

// 状态初始值
const initialState = {
  status: VOICE_STATUS.IDLE,
  sessionId: null,
  partialText: '',
  finalText: '',
  agentText: '',
  currentVoice: DEFAULT_VOICE,
  error: null,
  chatHistory: [],
};

// 状态 reducer
function voiceReducer(state, action) {
  switch (action.type) {
    case 'SET_STATUS':
      return { ...state, status: action.payload };

    case 'SET_SESSION_ID':
      return { ...state, sessionId: action.payload };

    case 'SET_PARTIAL_TEXT':
      return { ...state, partialText: action.payload };

    case 'SET_FINAL_TEXT':
      return { ...state, finalText: action.payload };

    case 'SET_AGENT_TEXT':
      return { ...state, agentText: action.payload };

    case 'SET_CURRENT_VOICE':
      return { ...state, currentVoice: action.payload };

    case 'SET_ERROR':
      return { ...state, error: action.payload };

    case 'ADD_CHAT_HISTORY':
      return {
        ...state,
        chatHistory: [...state.chatHistory, action.payload],
      };

    case 'CLEAR_TEXT':
      return {
        ...state,
        partialText: '',
        finalText: '',
        agentText: '',
      };

    case 'RESET':
      return initialState;

    default:
      return state;
  }
}

export function useVoiceState() {
  const [state, dispatch] = useReducer(voiceReducer, initialState);

  // 状态操作方法
  const setStatus = useCallback((status) => {
    dispatch({ type: 'SET_STATUS', payload: status });
  }, []);

  const setSessionId = useCallback((sessionId) => {
    dispatch({ type: 'SET_SESSION_ID', payload: sessionId });
  }, []);

  const setPartialText = useCallback((text) => {
    dispatch({ type: 'SET_PARTIAL_TEXT', payload: text });
  }, []);

  const setFinalText = useCallback((text) => {
    dispatch({ type: 'SET_FINAL_TEXT', payload: text });
  }, []);

  const setAgentText = useCallback((text) => {
    dispatch({ type: 'SET_AGENT_TEXT', payload: text });
  }, []);

  const setCurrentVoice = useCallback((voice) => {
    dispatch({ type: 'SET_CURRENT_VOICE', payload: voice });
  }, []);

  const setError = useCallback((error) => {
    dispatch({ type: 'SET_ERROR', payload: error });
  }, []);

  const addToChatHistory = useCallback((role, text) => {
    dispatch({
      type: 'ADD_CHAT_HISTORY',
      payload: { role, text, timestamp: Date.now() },
    });
  }, []);

  const clearText = useCallback(() => {
    dispatch({ type: 'CLEAR_TEXT' });
  }, []);

  const reset = useCallback(() => {
    dispatch({ type: 'RESET' });
  }, []);

  return {
    state,
    setStatus,
    setSessionId,
    setPartialText,
    setFinalText,
    setAgentText,
    setCurrentVoice,
    setError,
    addToChatHistory,
    clearText,
    reset,
  };
}
