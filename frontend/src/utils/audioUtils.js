/**
 * Float32Array转Int16Array（PCM格式）
 */
export function float32ToInt16(float32Array) {
  const int16Array = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }
  return int16Array;
}

/**
 * Int16Array转Float32Array（用于播放）
 */
export function int16ToFloat32(int16Array) {
  const float32Array = new Float32Array(int16Array.length);
  for (let i = 0; i < int16Array.length; i++) {
    float32Array[i] = int16Array[i] / 32768.0;
  }
  return float32Array;
}

/**
 * ArrayBuffer转Base64
 */
export function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

/**
 * Base64转ArrayBuffer
 */
export function base64ToArrayBuffer(base64) {
  const binaryString = atob(base64);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes.buffer;
}

/**
 * 解码PCM音频为AudioBuffer
 */
export function decodePCMAudio(base64Audio, sampleRate = 16000, existingAudioContext = null) {
  const pcmData = base64ToArrayBuffer(base64Audio);
  const int16Array = new Int16Array(pcmData);
  const float32Array = int16ToFloat32(int16Array);

  // 长回复会拆成很多 PCM 块。复用同一个 AudioContext，避免浏览器因短时间
  // 创建大量上下文而暂停或拒绝后续音频播放。
  const audioContext = existingAudioContext || new (window.AudioContext || window.webkitAudioContext)({
    sampleRate: sampleRate,
  });
  const audioBuffer = audioContext.createBuffer(1, float32Array.length, sampleRate);
  audioBuffer.getChannelData(0).set(float32Array);

  return { audioBuffer, audioContext };
}
