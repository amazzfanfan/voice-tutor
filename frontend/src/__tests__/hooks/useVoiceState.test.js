import { renderHook, act } from '@testing-library/react';
import { useVoiceState } from '../../hooks/useVoiceState';
import { VOICE_STATUS } from '../../utils/constants';

describe('useVoiceState', () => {
  test('应该初始化正确的默认状态', () => {
    const { result } = renderHook(() => useVoiceState());

    expect(result.current.state.status).toBe(VOICE_STATUS.IDLE);
    expect(result.current.state.sessionId).toBeNull();
    expect(result.current.state.partialText).toBe('');
    expect(result.current.state.finalText).toBe('');
    expect(result.current.state.agentText).toBe('');
    expect(result.current.state.currentVoice).toBe('longyumi_v3');
    expect(result.current.state.error).toBeNull();
    expect(result.current.state.chatHistory).toEqual([]);
  });

  test('应该能够设置状态', () => {
    const { result } = renderHook(() => useVoiceState());

    act(() => {
      result.current.setStatus(VOICE_STATUS.LISTENING);
    });

    expect(result.current.state.status).toBe(VOICE_STATUS.LISTENING);
  });

  test('应该能够设置会话ID', () => {
    const { result } = renderHook(() => useVoiceState());

    act(() => {
      result.current.setSessionId('test-session-id');
    });

    expect(result.current.state.sessionId).toBe('test-session-id');
  });

  test('应该能够设置部分文本', () => {
    const { result } = renderHook(() => useVoiceState());

    act(() => {
      result.current.setPartialText('测试文本');
    });

    expect(result.current.state.partialText).toBe('测试文本');
  });

  test('应该能够设置最终文本', () => {
    const { result } = renderHook(() => useVoiceState());

    act(() => {
      result.current.setFinalText('最终文本');
    });

    expect(result.current.state.finalText).toBe('最终文本');
  });

  test('应该能够设置AI回复文本', () => {
    const { result } = renderHook(() => useVoiceState());

    act(() => {
      result.current.setAgentText('AI回复');
    });

    expect(result.current.state.agentText).toBe('AI回复');
  });

  test('应该能够设置当前音色', () => {
    const { result } = renderHook(() => useVoiceState());

    act(() => {
      result.current.setCurrentVoice('longxiaoxia_v3');
    });

    expect(result.current.state.currentVoice).toBe('longxiaoxia_v3');
  });

  test('应该能够设置错误信息', () => {
    const { result } = renderHook(() => useVoiceState());

    act(() => {
      result.current.setError('测试错误');
    });

    expect(result.current.state.error).toBe('测试错误');
  });

  test('应该能够添加对话历史', () => {
    const { result } = renderHook(() => useVoiceState());

    act(() => {
      result.current.addToChatHistory('user', '用户问题');
    });

    expect(result.current.state.chatHistory).toHaveLength(1);
    expect(result.current.state.chatHistory[0].role).toBe('user');
    expect(result.current.state.chatHistory[0].text).toBe('用户问题');
  });

  test('应该能够清空文本', () => {
    const { result } = renderHook(() => useVoiceState());

    act(() => {
      result.current.setPartialText('部分文本');
      result.current.setFinalText('最终文本');
      result.current.setAgentText('AI回复');
    });

    act(() => {
      result.current.clearText();
    });

    expect(result.current.state.partialText).toBe('');
    expect(result.current.state.finalText).toBe('');
    expect(result.current.state.agentText).toBe('');
  });

  test('应该能够重置状态', () => {
    const { result } = renderHook(() => useVoiceState());

    act(() => {
      result.current.setStatus(VOICE_STATUS.LISTENING);
      result.current.setSessionId('test-session-id');
      result.current.addToChatHistory('user', '用户问题');
    });

    act(() => {
      result.current.reset();
    });

    expect(result.current.state.status).toBe(VOICE_STATUS.IDLE);
    expect(result.current.state.sessionId).toBeNull();
    expect(result.current.state.chatHistory).toEqual([]);
  });
});
