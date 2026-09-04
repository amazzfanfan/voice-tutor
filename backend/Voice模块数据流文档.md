# 语音模块数据流

## 完整数据流

```
┌─────────────────────────────────────────────────────────────────┐
│                        浏览器端                                  │
│                                                                 │
│  1. 用户点击"开始对话"                                           │
│     └── new WebSocket('ws://localhost:18000/voice/chat')        │
│     └── 发送 start_session                                      │
│         { user_id, session_id, voice_id: "longanhuan_v3" }     │
│                                                                 │
│  2. 收到 session_started 后启动音频采集                          │
│     └── navigator.mediaDevices.getUserMedia({ audio: 16kHz })   │
│     └── AudioWorklet 采集 Float32 → 转 Int16 PCM → Base64      │
│                                                                 │
│  3. 持续发送音频 (~250ms/次)                                     │
│     └── { type: "audio_data", audio: "<base64>" }              │
│                                                                 │
│  4. 收到 stt_final → 显示用户说的话                              │
│  5. 收到 agent_thinking → 显示"思考中..."                        │
│  6. 收到 agent_text → 显示 AI 回复文本                           │
│  7. 收到 audio_chunk → 播放 TTS 音频                             │
│     └── Base64 → PCM (22050Hz) → Web Audio API 播放            │
│  8. 收到 is_last=true → 回到聆听状态                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ WebSocket (双向 JSON 消息)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        服务端                                    │
│                                                                 │
│  1. start_session → 创建 VoiceSession                           │
│     └── 初始化 STT / VoiceAgent(TTS)                            │
│                                                                 │
│  2. audio_data → STT 语音识别                                   │
│     └── DashScope fun-asr-realtime (PCM 16kHz)                 │
│     └── 返回: "请总结一下高炉炼铁的基本流程"                     │
│                                                                 │
│  3. LLM 生成回复                                                │
│     └── 直接调 RAG 检索知识库 (public_knowledge_db_test)        │
│     └── 将 RAG 结果 + 问题发给 qwen-plus                        │
│     └── LLM 自主决定是否调用 WebSearch 补充                     │
│     └── 返回: "高炉炼铁简单来说..."                              │
│                                                                 │
│  4. TTS 语音合成                                                │
│     └── DashScope cosyvoice-v3-flash (longanhuan_v3)           │
│     └── 按句分割，逐句合成 PCM (22050Hz, 16bit, mono)          │
│     └── 逐块发送 audio_chunk                                    │
│                                                                 │
│  5. 发送 is_last=true → 回到 LISTENING                          │
└─────────────────────────────────────────────────────────────────┘
```

## 状态流转

```
IDLE ──start_session──→ LISTENING ──stt_final──→ PROCESSING ──TTS──→ SPEAKING
  ↑                         ↑                                          │
  └──end_session────────────└──────────────── is_last=true ───────────┘
```

## WebSocket 消息

### 前端 → 后端

```json
{ "type": "start_session", "user_id": "USR-10001", "session_id": "sess-xxx", "voice_id": "longanhuan_v3" }
{ "type": "audio_data", "audio": "<base64 PCM 16kHz>" }
{ "type": "interrupt" }
{ "type": "end_session" }
```

### 后端 → 前端

```json
{ "type": "session_started", "session_id": "sess-xxx" }
{ "type": "stt_partial", "text": "高炉炼铁", "is_final": false }
{ "type": "stt_final", "text": "请总结一下高炉炼铁的基本流程。" }
{ "type": "agent_thinking" }
{ "type": "agent_text", "text": "高炉炼铁简单来说...", "is_final": true }
{ "type": "audio_chunk", "audio": "<base64 PCM 22050Hz>", "is_last": false }
{ "type": "audio_chunk", "audio": "", "is_last": true }
```

## 音频格式

| 方向 | 格式 | 采样率 | 位深 | 声道 |
|------|------|--------|------|------|
| 前端 → 后端 (STT) | PCM | 16000 Hz | 16 bit | mono |
| 后端 → 前端 (TTS) | PCM | 22050 Hz | 16 bit | mono |

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| STT | DashScope fun-asr-realtime | 实时语音识别 |
| LLM | DashScope qwen-plus (agno) | 对话生成，含 RAG + WebSearch |
| TTS | DashScope cosyvoice-v3-flash | 流式语音合成 |
| API | FastAPI WebSocket | 双向实时通信 |
| 前端 | React + Web Audio API | 音频采集/播放 |
