import React from 'react';
import { VOICE_STATUS } from '../utils/constants';
import '../styles/VoiceButton.css';

function VoiceButton({ status, onClick }) {
  const isIdle = status === VOICE_STATUS.IDLE;

  const getButtonClass = () => {
    return isIdle ? 'voice-button idle' : 'voice-button active';
  };

  const getButtonText = () => {
    return isIdle ? '开始对话' : '结束对话';
  };

  return (
    <div className="voice-button-container">
      <button
        className={getButtonClass()}
        onClick={onClick}
        aria-label={getButtonText()}
      >
        {!isIdle && <div className="ripple"></div>}
        <svg viewBox="0 0 24 24" className="microphone-icon">
          <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
          <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
        </svg>
      </button>
      <span className="button-hint">{getButtonText()}</span>
    </div>
  );
}

export default VoiceButton;
