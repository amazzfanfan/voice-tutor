import { createStartSessionMessage } from '../../utils/protocol';

describe('createStartSessionMessage', () => {
  test('重连时携带最近的对话历史并转换角色', () => {
    const chatHistory = [
      { role: 'user', text: '铁路运输线路应遵循哪些规定？' },
      { role: 'ai', text: '你目前是什么岗位，用在什么场景？' },
      { role: 'user', text: '我是安全员，用于现场讲解。' },
    ];

    const message = createStartSessionMessage(
      'USR-10001',
      'longanhuan_v3',
      chatHistory
    );

    expect(message.config.conversation_history).toEqual([
      { role: 'user', content: '铁路运输线路应遵循哪些规定？' },
      { role: 'assistant', content: '你目前是什么岗位，用在什么场景？' },
      { role: 'user', content: '我是安全员，用于现场讲解。' },
    ]);
  });

  test('重连历史最多携带最近十条消息', () => {
    const chatHistory = Array.from({ length: 12 }, (_, index) => ({
      role: index % 2 === 0 ? 'user' : 'ai',
      text: `消息${index}`,
    }));

    const message = createStartSessionMessage('USR-10001', 'longanhuan_v3', chatHistory);

    expect(message.config.conversation_history).toHaveLength(10);
    expect(message.config.conversation_history[0].content).toBe('消息2');
    expect(message.config.conversation_history[9].content).toBe('消息11');
  });
});
