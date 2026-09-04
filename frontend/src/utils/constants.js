// WebSocket配置
export const WS_CONFIG = {
  RECONNECT_INTERVAL: 3000,  // 重连间隔（毫秒）
  MAX_RECONNECT_ATTEMPTS: 3, // 最大重连次数
};

// 音频配置
export const AUDIO_CONFIG = {
  SAMPLE_RATE: 16000,
  CHANNELS: 1,
  BIT_DEPTH: 16,
  FORMAT: 'pcm',
};

// 语音状态
export const VOICE_STATUS = {
  IDLE: 'idle',
  LISTENING: 'listening',
  PROCESSING: 'processing',
  SPEAKING: 'speaking',
};

// 状态提示文本
export const STATUS_TEXT = {
  [VOICE_STATUS.IDLE]: '点击开始对话',
  [VOICE_STATUS.LISTENING]: '聆听中...',
  [VOICE_STATUS.PROCESSING]: '思考中...',
  [VOICE_STATUS.SPEAKING]: 'AI导师正在讲解...',
};

// 默认音色
export const DEFAULT_VOICE = 'longyumi_v3';

// 可用音色列表
export const AVAILABLE_VOICES = [
  { id: 'longyumi_v3', name: 'YUMI（默认，正经青年女）' },
  { id: 'longxiaoxia_v3', name: '龙小夏（沉稳权威女）' },
  { id: 'longxiaochun_v3', name: '龙小淳（知性积极女）' },
  { id: 'longanwen_v3', name: '龙安温（优雅知性女）' },
  { id: 'longshuo_v3', name: '龙硕（博才干练男）' },
  { id: 'longshu_v3', name: '龙书（沉稳青年男）' },
  { id: 'longmiao_v3', name: '龙妙（抑扬顿挫女）' },
  { id: 'longsanshu_v3', name: '龙三叔（沉稳质感男）' },
  { id: 'longanhuan_v3', name: '龙安欢（欢脱元气女）' },
];
