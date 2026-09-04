import { useRef, useState, useCallback } from 'react';
import { decodePCMAudio } from '../utils/audioUtils';

export function useAudioPlayer() {
  const [isPlaying, setIsPlaying] = useState(false);
  const audioQueueRef = useRef([]);
  const isPlayingRef = useRef(false);
  const audioContextRef = useRef(null);
  const currentSourceRef = useRef(null);

  const getAudioContext = useCallback((sampleRate) => {
    if (!audioContextRef.current || audioContextRef.current.state === 'closed') {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      audioContextRef.current = new AudioContextClass({ sampleRate });
    }

    if (audioContextRef.current.state === 'suspended') {
      audioContextRef.current.resume().catch((error) => {
        console.error('[AudioPlayer] Failed to resume audio context', error);
      });
    }

    return audioContextRef.current;
  }, []);

  // 播放下一个音频块
  const playNext = useCallback(() => {
    if (audioQueueRef.current.length === 0) {
      console.log('[AudioPlayer] Queue empty, setting isPlaying=false');
      isPlayingRef.current = false;
      setIsPlaying(false);
      return;
    }

    console.log(`[AudioPlayer] Playing next chunk, queue remaining=${audioQueueRef.current.length}`);
    isPlayingRef.current = true;
    setIsPlaying(true);

    const audioBuffer = audioQueueRef.current.shift();
    const audioContext = audioContextRef.current;

    if (!audioContext || audioContext.state === 'closed') {
      console.error('[AudioPlayer] Audio context unavailable while playing queued audio');
      audioQueueRef.current = [];
      isPlayingRef.current = false;
      setIsPlaying(false);
      return;
    }

    const source = audioContext.createBufferSource();
    currentSourceRef.current = source;
    source.buffer = audioBuffer;
    source.connect(audioContext.destination);

    source.onended = () => {
      if (currentSourceRef.current === source) {
        currentSourceRef.current = null;
      }
      playNext();
    };

    source.start(0);
  }, []);

  // 播放音频块 (TTS outputs 22050Hz PCM)
  const playAudioChunk = useCallback((base64Audio, sampleRate = 22050) => {
    // 跳过空音频块（后端发送的 is_last 标记），防止 0 长度 buffer
    // 导致 onended 立即触发、isPlaying 被错误设为 false
    if (!base64Audio || base64Audio.length === 0) {
      console.log('[AudioPlayer] ⏭️ Skipping empty audio chunk (end-of-stream marker)');
      return;
    }

    try {
      const audioContext = getAudioContext(sampleRate);
      const { audioBuffer } = decodePCMAudio(base64Audio, sampleRate, audioContext);

      audioQueueRef.current.push(audioBuffer);
      console.log(`[AudioPlayer] Queued chunk, queue length=${audioQueueRef.current.length}, isPlaying=${isPlayingRef.current}`);

      if (!isPlayingRef.current) {
        playNext();
      }
    } catch (error) {
      console.error('[AudioPlayer] Failed to play audio chunk', error);
    }
  }, [getAudioContext, playNext]);

  // 停止播放
  const stopPlaying = useCallback(() => {
    audioQueueRef.current = [];
    isPlayingRef.current = false;
    setIsPlaying(false);

    if (currentSourceRef.current) {
      currentSourceRef.current.onended = null;
      try {
        currentSourceRef.current.stop();
      } catch (error) {
        console.warn('[AudioPlayer] Failed to stop current source', error);
      }
      currentSourceRef.current = null;
    }

    if (audioContextRef.current) {
      audioContextRef.current.close().catch((error) => {
        console.warn('[AudioPlayer] Failed to close audio context', error);
      });
      audioContextRef.current = null;
    }
  }, []);

  return {
    isPlaying,
    playAudioChunk,
    stopPlaying,
  };
}
