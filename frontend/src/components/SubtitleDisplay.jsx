import React from 'react';
import { VOICE_STATUS } from '../utils/constants';
import '../styles/SubtitleDisplay.css';

const normalizeCaptionText = (text) => text
  .replace(/```[\s\S]*?```/g, ' ')
  .replace(/`([^`]+)`/g, '$1')
  .replace(/\[(.*?)\]\((.*?)\)/g, '$1')
  .replace(/^\s*[-*]\s+/gm, ' ')
  .replace(/[*_~>#]/g, ' ')
  .replace(/\s+/g, ' ')
  .trim();

function SubtitleDisplay({ status, partialText, agentText }) {
  const getDisplayText = () => {
    if (status === VOICE_STATUS.LISTENING && partialText) {
      return partialText;
    }
    if (status === VOICE_STATUS.SPEAKING && agentText) {
      return agentText;
    }
    return '';
  };

  const displayText = getDisplayText();

  if (!displayText) {
    return null;
  }

  const isSpeakingCaption = status === VOICE_STATUS.SPEAKING && agentText;
  const captionText = isSpeakingCaption ? normalizeCaptionText(displayText) : displayText;

  return (
    <div
      className={`subtitle-display${isSpeakingCaption ? ' subtitle-display--ticker' : ''}`}
      aria-live="polite"
    >
      {isSpeakingCaption ? (
        <div className="subtitle-ticker" title={captionText}>
          <span className="subtitle-ticker-track">{captionText}</span>
        </div>
      ) : (
        <div className="subtitle-text">{captionText}</div>
      )}
    </div>
  );
}

export default SubtitleDisplay;
