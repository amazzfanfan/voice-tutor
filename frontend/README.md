# voice-fronted

`voice-fronted` 是 AI 语音讲师的 React 前端，通过 WebSocket 与 `app-rag-agent-me` Voice 后端进行实时通信。

项目支持浏览器麦克风采集、实时语音识别字幕、讲师回答展示、Markdown/GFM 渲染、分段语音播放、音色切换、会话历史保留，以及播放完成后自动恢复下一轮语音识别。

## 主要功能

- 浏览器麦克风实时采集
- 16 kHz、单声道 PCM 音频传输
- STT 临时结果和最终结果展示
- AI 讲师回答及 Markdown/GFM 格式渲染
- TTS 音频分段排队播放
- 播放结束状态确认与自动恢复录音
- 多种讲师音色切换
- 会话历史展示及最近十条上下文续接
- WebSocket 会话、错误和连接状态管理

## 技术栈

- React 19
- Create React App / react-scripts 5
- WebSocket
- Web Audio API / AudioWorklet
- react-markdown
- remark-gfm
- Jest / Testing Library

## 环境要求

- Node.js 18 及以上版本，推荐使用 Node.js 20 LTS
- npm
- 可访问的 Voice 后端服务
- 支持 Web Audio API、AudioWorklet 和麦克风权限的现代浏览器

## 安装依赖

在项目根目录执行：

```bash
npm ci
```

如果没有使用锁定依赖安装，也可以执行：

```bash
npm install
```

## 后端连接配置

当前 WebSocket 地址定义在 `src/components/VoiceTutor.jsx`：

```javascript
const WS_URL = 'ws://localhost:18000/voice/chat';
```

本地联调时，Voice 后端应监听 `18000` 端口并提供 `/voice/chat` WebSocket 接口。

如果前端和后端部署在不同主机，请修改 `WS_URL`：

```javascript
const WS_URL = 'ws://<后端地址>:18000/voice/chat';
```

页面通过 HTTPS 访问时，浏览器通常要求使用安全 WebSocket，此时应通过反向代理配置 TLS，并改用：

```javascript
const WS_URL = 'wss://<域名>/voice/chat';
```

## 启动开发服务

确保 Voice 后端已经启动，然后在本项目根目录执行：

```bash
BROWSER=none npm start
```

前端默认访问地址：

```text
http://localhost:3000
```

如果希望启动时自动打开浏览器，可以直接执行：

```bash
npm start
```

首次开始语音会话时，浏览器会请求麦克风权限，请选择允许。

## 完整本地联调

### 1. 启动 Voice 后端

```bash
cd <app-rag-agent-me 项目目录>
.venv/bin/python run_web_api.py
```

后端默认监听：

```text
http://127.0.0.1:18000
```

### 2. 启动 Voice 前端

```bash
cd <voice-fronted 项目目录>
npm ci
BROWSER=none npm start
```

### 3. 开始语音会话

1. 在浏览器打开 `http://localhost:3000`。
2. 允许浏览器使用麦克风。
3. 选择讲师音色。
4. 点击开始对话并说出问题。
5. 等待讲师回答和语音播放；播放完成后系统会自动恢复监听。

## 常用命令

### 运行测试

```bash
npm test -- --watchAll=false
```

### 构建生产版本

```bash
npm run build
```

构建产物位于 `build/` 目录。

## WebSocket 交互流程

```text
点击开始对话
  -> 建立 WebSocket
  -> start_session
  -> 采集并发送 audio_data
  -> stop_audio
  -> 接收 stt_final
  -> 接收 agent_text
  -> 接收并播放 audio_chunk
  -> 接收 audio_stream_end
  -> 播放队列清空后发送 playback_finished
  -> 后端发送 start_capture
  -> 进入下一轮语音识别
```

## 目录结构

```text
voice-fronted/
├── public/
│   ├── audio-processor.js       # AudioWorklet 音频处理器
│   └── index.html               # 页面模板
├── src/
│   ├── components/              # 语音讲师界面组件
│   ├── hooks/                   # 录音、播放、状态及 WebSocket Hooks
│   ├── styles/                  # 组件样式
│   ├── utils/                   # 音频工具、协议和常量
│   ├── __tests__/               # 组件及 Hooks 测试
│   ├── App.jsx                  # 应用入口组件
│   └── index.js                 # React 挂载入口
├── package.json                 # 依赖和 npm 命令
└── package-lock.json            # 锁定依赖版本
```

## 常见问题

- 无法连接后端：确认 `app-rag-agent-me` 已启动，并检查 `WS_URL`、端口和 `/voice/chat` 路径。
- 浏览器无法录音：检查麦克风权限；非本机部署时建议使用 HTTPS。
- 有文字但没有声音：检查浏览器自动播放限制、系统音量，以及后端是否返回 `audio_chunk`。
- 回答播放完后不能继续说话：检查浏览器控制台是否收到 `audio_stream_end`，以及是否发送了 `playback_finished`。
- Markdown 显示异常：确认返回内容是合法 Markdown，并检查 `react-markdown` 和 `remark-gfm` 依赖是否已安装。
