import React from 'react';
import { render, screen } from '@testing-library/react';
import StatusIndicator from '../../components/StatusIndicator';
import { VOICE_STATUS } from '../../utils/constants';

describe('StatusIndicator', () => {
  test('应该渲染空闲状态', () => {
    render(<StatusIndicator status={VOICE_STATUS.IDLE} />);

    expect(screen.getByText('点击开始对话')).toBeInTheDocument();
    expect(screen.getByText('👆')).toBeInTheDocument();
  });

  test('应该渲染聆听状态', () => {
    render(<StatusIndicator status={VOICE_STATUS.LISTENING} />);

    expect(screen.getByText('聆听中...')).toBeInTheDocument();
    expect(screen.getByText('🎤')).toBeInTheDocument();
  });

  test('应该渲染处理状态', () => {
    render(<StatusIndicator status={VOICE_STATUS.PROCESSING} />);

    expect(screen.getByText('思考中...')).toBeInTheDocument();
    expect(screen.getByText('💭')).toBeInTheDocument();
  });

  test('应该渲染说话状态', () => {
    render(<StatusIndicator status={VOICE_STATUS.SPEAKING} />);

    expect(screen.getByText('AI导师正在讲解...')).toBeInTheDocument();
    expect(screen.getByText('🔊')).toBeInTheDocument();
  });

  test('应该应用正确的CSS类', () => {
    const { rerender } = render(<StatusIndicator status={VOICE_STATUS.IDLE} />);

    expect(screen.getByText('点击开始对话').parentElement).toHaveClass('status-idle');

    rerender(<StatusIndicator status={VOICE_STATUS.LISTENING} />);
    expect(screen.getByText('聆听中...').parentElement).toHaveClass('status-listening');

    rerender(<StatusIndicator status={VOICE_STATUS.PROCESSING} />);
    expect(screen.getByText('思考中...').parentElement).toHaveClass('status-processing');

    rerender(<StatusIndicator status={VOICE_STATUS.SPEAKING} />);
    expect(screen.getByText('AI导师正在讲解...').parentElement).toHaveClass('status-speaking');
  });
});
