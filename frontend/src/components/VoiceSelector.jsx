import React from 'react';
import { AVAILABLE_VOICES } from '../utils/constants';
import '../styles/VoiceSelector.css';

function VoiceSelector({ currentVoice, onVoiceChange }) {
  const handleChange = (e) => {
    onVoiceChange(e.target.value);
  };

  return (
    <div className="voice-selector">
      <label className="selector-label">选择声音</label>
      <select
        className="selector-dropdown"
        value={currentVoice}
        onChange={handleChange}
      >
        {AVAILABLE_VOICES.map((voice) => (
          <option key={voice.id} value={voice.id}>
            {voice.name}
          </option>
        ))}
      </select>
    </div>
  );
}

export default VoiceSelector;
