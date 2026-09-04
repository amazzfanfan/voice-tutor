import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import VoiceButton from '../../components/VoiceButton';
import { VOICE_STATUS } from '../../utils/constants';

describe('VoiceButton', () => {
  test('should render idle state button', () => {
    render(<VoiceButton status={VOICE_STATUS.IDLE} onClick={() => {}} />);

    expect(screen.getByText('开始对话')).toBeInTheDocument();
    expect(screen.getByLabelText('开始对话')).toBeInTheDocument();
  });

  test('should render listening state button', () => {
    render(<VoiceButton status={VOICE_STATUS.LISTENING} onClick={() => {}} />);

    expect(screen.getByText('结束对话')).toBeInTheDocument();
    expect(screen.getByLabelText('结束对话')).toBeInTheDocument();
  });

  test('should call onClick when clicked', () => {
    const handleClick = jest.fn();
    render(<VoiceButton status={VOICE_STATUS.IDLE} onClick={handleClick} />);

    fireEvent.click(screen.getByLabelText('开始对话'));

    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  test('should apply correct CSS classes', () => {
    const { rerender } = render(<VoiceButton status={VOICE_STATUS.IDLE} onClick={() => {}} />);

    expect(screen.getByLabelText('开始对话')).toHaveClass('idle');

    rerender(<VoiceButton status={VOICE_STATUS.LISTENING} onClick={() => {}} />);
    expect(screen.getByLabelText('结束对话')).toHaveClass('active');
  });

  test('should show ripple animation in listening state', () => {
    render(<VoiceButton status={VOICE_STATUS.LISTENING} onClick={() => {}} />);

    expect(screen.getByLabelText('结束对话').querySelector('.ripple')).toBeInTheDocument();
  });

  test('should not show ripple animation in idle state', () => {
    render(<VoiceButton status={VOICE_STATUS.IDLE} onClick={() => {}} />);

    expect(screen.getByLabelText('开始对话').querySelector('.ripple')).not.toBeInTheDocument();
  });
});
