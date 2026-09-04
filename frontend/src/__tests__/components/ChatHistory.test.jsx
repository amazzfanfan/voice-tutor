import React from 'react';
import { render, screen } from '@testing-library/react';
import ChatHistory from '../../components/ChatHistory';

describe('ChatHistory', () => {
  test('应该渲染对话历史标题', () => {
    render(<ChatHistory chatHistory={[]} />);

    expect(screen.getByText('对话历史')).toBeInTheDocument();
  });

  test('应该在空历史时显示提示信息', () => {
    render(<ChatHistory chatHistory={[]} />);

    expect(screen.getByText('开始对话，记录将显示在这里')).toBeInTheDocument();
  });

  test('应该渲染用户消息', () => {
    const chatHistory = [
      { role: 'user', text: '用户问题', timestamp: 1234567890 }
    ];

    render(<ChatHistory chatHistory={chatHistory} />);

    expect(screen.getByText('用户问题')).toBeInTheDocument();
    expect(screen.getByText('学生')).toBeInTheDocument();
  });

  test('应该渲染AI回复消息', () => {
    const chatHistory = [
      { role: 'ai', text: 'AI回复', timestamp: 1234567890 }
    ];

    render(<ChatHistory chatHistory={chatHistory} />);

    expect(screen.getByText('AI回复')).toBeInTheDocument();
    expect(screen.getByText('AI导师')).toBeInTheDocument();
  });

  test('应该把AI回复中的完整Markdown交给渲染器', () => {
    const markdown = '### 先看风险\n\n- **制动距离**：超载后会变长。';
    const chatHistory = [{
      role: 'ai',
      text: markdown,
      timestamp: 1234567890
    }];

    render(<ChatHistory chatHistory={chatHistory} />);

    expect(screen.getByTestId('markdown-output')).toHaveAttribute(
      'data-markdown-source',
      markdown
    );
  });

  test('应该渲染多条消息', () => {
    const chatHistory = [
      { role: 'user', text: '问题1', timestamp: 1234567890 },
      { role: 'ai', text: '回复1', timestamp: 1234567891 },
      { role: 'user', text: '问题2', timestamp: 1234567892 },
      { role: 'ai', text: '回复2', timestamp: 1234567893 }
    ];

    render(<ChatHistory chatHistory={chatHistory} />);

    expect(screen.getByText('问题1')).toBeInTheDocument();
    expect(screen.getByText('回复1')).toBeInTheDocument();
    expect(screen.getByText('问题2')).toBeInTheDocument();
    expect(screen.getByText('回复2')).toBeInTheDocument();
  });

  test('应该应用正确的CSS类', () => {
    const chatHistory = [
      { role: 'user', text: '用户问题', timestamp: 1234567890 }
    ];

    render(<ChatHistory chatHistory={chatHistory} />);

    expect(screen.getByText('用户问题').closest('.chat-item')).toHaveClass('user');
  });
});
