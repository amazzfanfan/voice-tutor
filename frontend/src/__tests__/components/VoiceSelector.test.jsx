import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import VoiceSelector from '../../components/VoiceSelector';
import { AVAILABLE_VOICES, DEFAULT_VOICE } from '../../utils/constants';

describe('VoiceSelector', () => {
  test('应该渲染当前选中的音色', () => {
    render(
      <VoiceSelector currentVoice={DEFAULT_VOICE} onVoiceChange={() => {}} />
    );

    expect(
      screen.getByDisplayValue('YUMI（默认，正经青年女）')
    ).toBeInTheDocument();
  });

  test('应该显示所有可用音色', () => {
    render(
      <VoiceSelector currentVoice={DEFAULT_VOICE} onVoiceChange={() => {}} />
    );

    const select = screen.getByDisplayValue('YUMI（默认，正经青年女）');
    expect(select.options.length).toBe(AVAILABLE_VOICES.length);
  });

  test('应该在选择新音色时调用onVoiceChange', () => {
    const handleVoiceChange = jest.fn();
    render(
      <VoiceSelector currentVoice={DEFAULT_VOICE} onVoiceChange={handleVoiceChange} />
    );

    const select = screen.getByDisplayValue('YUMI（默认，正经青年女）');
    fireEvent.change(select, { target: { value: 'longxiaoxia_v3' } });

    expect(handleVoiceChange).toHaveBeenCalledWith('longxiaoxia_v3');
  });

  test('应该显示选择声音标签', () => {
    render(
      <VoiceSelector currentVoice={DEFAULT_VOICE} onVoiceChange={() => {}} />
    );

    expect(screen.getByText('选择声音')).toBeInTheDocument();
  });
});
