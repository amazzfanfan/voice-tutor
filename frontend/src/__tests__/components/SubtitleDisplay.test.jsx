import React from 'react';
import { render, screen } from '@testing-library/react';
import SubtitleDisplay from '../../components/SubtitleDisplay';
import { VOICE_STATUS } from '../../utils/constants';

describe('SubtitleDisplay', () => {
  test('should display partial text when listening', () => {
    render(
      <SubtitleDisplay
        status={VOICE_STATUS.LISTENING}
        partialText="测试文本"
        agentText=""
      />
    );

    expect(screen.getByText('测试文本')).toBeInTheDocument();
  });

  test('should display agent text when speaking', () => {
    render(
      <SubtitleDisplay
        status={VOICE_STATUS.SPEAKING}
        partialText=""
        agentText="AI回复内容"
      />
    );

    expect(screen.getByText('AI回复内容')).toBeInTheDocument();
  });

  test('should not display anything when idle', () => {
    const { container } = render(
      <SubtitleDisplay
        status={VOICE_STATUS.IDLE}
        partialText=""
        agentText=""
      />
    );

    expect(container.firstChild).toBeNull();
  });

  test('should not display anything when processing', () => {
    const { container } = render(
      <SubtitleDisplay
        status={VOICE_STATUS.PROCESSING}
        partialText=""
        agentText=""
      />
    );

    expect(container.firstChild).toBeNull();
  });

  test('should prioritize partial text over agent text', () => {
    render(
      <SubtitleDisplay
        status={VOICE_STATUS.LISTENING}
        partialText="部分文本"
        agentText="AI回复"
      />
    );

    expect(screen.getByText('部分文本')).toBeInTheDocument();
    expect(screen.queryByText('AI回复')).not.toBeInTheDocument();
  });
});
