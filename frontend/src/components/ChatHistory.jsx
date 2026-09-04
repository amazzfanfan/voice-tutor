import React, { useEffect, useRef } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import '../styles/ChatHistory.css';

function ChatHistory({ chatHistory }) {
  const chatListRef = useRef(null);

  // 自动滚动到底部
  useEffect(() => {
    if (chatListRef.current) {
      chatListRef.current.scrollTop = chatListRef.current.scrollHeight;
    }
  }, [chatHistory]);

  const getRoleLabel = (role) => {
    return role === 'user' ? '学生' : 'AI导师';
  };

  const getRoleClass = (role) => {
    return role === 'user' ? 'chat-item user' : 'chat-item ai';
  };

  return (
    <div className="chat-history">
      <h2 className="panel-title">对话历史</h2>
      <div className="chat-list" ref={chatListRef}>
        {chatHistory.length === 0 ? (
          <div className="empty-history">
            <p>开始对话，记录将显示在这里</p>
          </div>
        ) : (
          chatHistory.map((item, index) => (
            <div key={index} className={getRoleClass(item.role)}>
              <div className="chat-role">{getRoleLabel(item.role)}</div>
              <div className="chat-text">
                {item.role === 'ai' ? (
                  <Markdown remarkPlugins={[remarkGfm]}>{item.text}</Markdown>
                ) : (
                  item.text
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default ChatHistory;
