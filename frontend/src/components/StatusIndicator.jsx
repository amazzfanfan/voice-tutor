import React from 'react';
import { VOICE_STATUS, STATUS_TEXT } from '../utils/constants';
import '../styles/StatusIndicator.css';

function StatusIndicator({ status }) {
  const getStatusClass = () => {
    switch (status) {
      case VOICE_STATUS.LISTENING:
        return 'status-listening';
      case VOICE_STATUS.PROCESSING:
        return 'status-processing';
      case VOICE_STATUS.SPEAKING:
        return 'status-speaking';
      default:
        return 'status-idle';
    }
  };

  const getStatusIcon = () => {
    switch (status) {
      case VOICE_STATUS.LISTENING:
        return '🎤';
      case VOICE_STATUS.PROCESSING:
        return '💭';
      case VOICE_STATUS.SPEAKING:
        return '🔊';
      default:
        return '👆';
    }
  };

  return (
    <div className={`status-indicator ${getStatusClass()}`}>
      <span className="status-icon">{getStatusIcon()}</span>
      <span className="status-text">{STATUS_TEXT[status]}</span>
    </div>
  );
}

export default StatusIndicator;
