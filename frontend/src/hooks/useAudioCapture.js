import { useRef, useState, useCallback, useEffect } from 'react';
import { AUDIO_CONFIG } from '../utils/constants';
import { float32ToInt16, arrayBufferToBase64 } from '../utils/audioUtils';

const SPEECH_RMS_THRESHOLD = 0.004;
const MIN_SPEECH_DURATION_MS = 220;
const SILENCE_AFTER_SPEECH_MS = 1000;
const MAX_CAPTURE_DURATION_MS = 12000;
const RMS_LOG_INTERVAL_MS = 1000;

function calculateRms(samples) {
  if (!samples || samples.length === 0) return 0;

  let sumSquares = 0;
  for (let i = 0; i < samples.length; i += 1) {
    sumSquares += samples[i] * samples[i];
  }
  return Math.sqrt(sumSquares / samples.length);
}

export function useAudioCapture(options = {}) {
  const { onAudioData, onSpeechEnd } = options;

  const [isCapturing, setIsCapturing] = useState(false);
  const isCapturingRef = useRef(false);
  const streamRef = useRef(null);
  const audioContextRef = useRef(null);
  const workletNodeRef = useRef(null);
  const sourceNodeRef = useRef(null);
  const silentGainRef = useRef(null);
  const captureStartedAtRef = useRef(0);
  const speechStartedAtRef = useRef(0);
  const lastVoiceAtRef = useRef(0);
  const speechEndSentRef = useRef(false);
  const maxRmsRef = useRef(0);
  const lastRmsLogAtRef = useRef(0);

  const stopCapture = useCallback(async () => {
    // 立即标记为停止，阻止所有后续音频回调（包括 port 队列中的残留消息）
    isCapturingRef.current = false;
    setIsCapturing(false);

    if (workletNodeRef.current) {
      workletNodeRef.current.port.onmessage = null;
      workletNodeRef.current.onprocessorerror = null;
      if (typeof workletNodeRef.current.disconnect === 'function') {
        workletNodeRef.current.disconnect();
      }
      workletNodeRef.current = null;
    }

    if (sourceNodeRef.current) {
      if (typeof sourceNodeRef.current.disconnect === 'function') {
        sourceNodeRef.current.disconnect();
      }
      sourceNodeRef.current = null;
    }

    if (silentGainRef.current) {
      if (typeof silentGainRef.current.disconnect === 'function') {
        silentGainRef.current.disconnect();
      }
      silentGainRef.current = null;
    }

    if (audioContextRef.current) {
      try {
        await audioContextRef.current.close();
      } catch (error) {
        console.error('Failed to close AudioContext', error);
      }
      audioContextRef.current = null;
    }

    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }

    console.log('Audio capture stopped');
  }, []);

  const startCapture = useCallback(async () => {
    // 防重入保护
    if (isCapturingRef.current) {
      return;
    }

    try {
      // 请求麦克风权限
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: AUDIO_CONFIG.SAMPLE_RATE,
          channelCount: AUDIO_CONFIG.CHANNELS,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      streamRef.current = stream;

      // 创建音频上下文
      const audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: AUDIO_CONFIG.SAMPLE_RATE,
      });
      audioContextRef.current = audioContext;

      // 加载AudioWorklet processor
      await audioContext.audioWorklet.addModule('/audio-processor.js');

      // 创建AudioWorklet节点
      const workletNode = new AudioWorkletNode(audioContext, 'audio-processor');
      workletNodeRef.current = workletNode;

      // 监听processor错误
      workletNode.onprocessorerror = (event) => {
        console.error('AudioWorklet processor error:', event);
        stopCapture();
      };

      // 监听音频数据（检查 isCapturingRef 防止 stopCapture 后的残留消息）
      workletNode.port.onmessage = (event) => {
        if (!isCapturingRef.current) return; // 已停止捕获，丢弃残留消息
        if (event.data.type === 'audioData') {
          const inputData = event.data.audioData;
          const now = performance.now();
          const rms = calculateRms(inputData);
          maxRmsRef.current = Math.max(maxRmsRef.current, rms);

          if (rms >= SPEECH_RMS_THRESHOLD) {
            if (!speechStartedAtRef.current) {
              speechStartedAtRef.current = now;
              console.info(`[VoiceTutor] detected speech, rms=${rms.toFixed(5)}`);
            }
            lastVoiceAtRef.current = now;
          }

          if (now - lastRmsLogAtRef.current >= RMS_LOG_INTERVAL_MS) {
            lastRmsLogAtRef.current = now;
            console.info(
              `[VoiceTutor] mic rms=${rms.toFixed(5)}, max=${maxRmsRef.current.toFixed(5)}`
            );
          }

          const pcmData = float32ToInt16(inputData);
          const base64Audio = arrayBufferToBase64(pcmData.buffer);

          if (onAudioData) {
            onAudioData(base64Audio);
          }

          const hasValidSpeech =
            speechStartedAtRef.current > 0 &&
            now - speechStartedAtRef.current >= MIN_SPEECH_DURATION_MS;
          const silenceAfterSpeech =
            hasValidSpeech &&
            lastVoiceAtRef.current > 0 &&
            now - lastVoiceAtRef.current >= SILENCE_AFTER_SPEECH_MS;
          const captureTimedOut =
            captureStartedAtRef.current > 0 &&
            now - captureStartedAtRef.current >= MAX_CAPTURE_DURATION_MS;

          if (!speechEndSentRef.current && (silenceAfterSpeech || captureTimedOut)) {
            speechEndSentRef.current = true;
            console.info(
              `[VoiceTutor] speech end: reason=${silenceAfterSpeech ? 'silence' : 'timeout'}, maxRms=${maxRmsRef.current.toFixed(5)}`
            );
            if (onSpeechEnd) {
              onSpeechEnd();
            }
            stopCapture();
          }
        }
      };

      // 创建音频源并连接（先设置 isCapturingRef，确保 worklet 消息不被丢弃）
      captureStartedAtRef.current = performance.now();
      speechStartedAtRef.current = 0;
      lastVoiceAtRef.current = 0;
      speechEndSentRef.current = false;
      maxRmsRef.current = 0;
      lastRmsLogAtRef.current = 0;
      isCapturingRef.current = true;
      setIsCapturing(true);

      const source = audioContext.createMediaStreamSource(stream);
      sourceNodeRef.current = source;

      source.connect(workletNode);
      if (typeof audioContext.createGain === 'function') {
        const silentGain = audioContext.createGain();
        silentGain.gain.value = 0;
        silentGainRef.current = silentGain;
        workletNode.connect(silentGain);
        silentGain.connect(audioContext.destination);
      } else {
        workletNode.connect(audioContext.destination);
      }

      console.log('Audio capture started with AudioWorklet');
    } catch (error) {
      console.error('Failed to start audio capture', error);
      throw error;
    }
  }, [onAudioData, onSpeechEnd, stopCapture]);

  // 组件卸载时自动清理
  useEffect(() => {
    return () => {
      stopCapture();
    };
  }, [stopCapture]);

  return {
    isCapturing,
    startCapture,
    stopCapture,
  };
}
