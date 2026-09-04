# Voice 模块开发指南

> 本文档为 Claude 在 `app-rag-agent-me` 仓库中继续开发语音功能提供上下文。
> 当你在新会话中工作时，先阅读本文档了解已有实现。

---

## 1. 模块概述

`src/voice/` 是一个独立的语音对话模块，实现 AI 语音导师功能：
- 用户通过 WebSocket 发送音频流
- 后端进行 STT → Agent 生成 → TTS，返回音频流
- 支持实时打断、多音色切换

---

## 2. 文件结构与职责

```
src/voice/
├── __init__.py           # 包初始化（空文件）
├── config.py             # 配置管理：从 src/conf/config.ini [voice_config] 读取
├── protocol.py           # WebSocket 消息协议：Pydantic v2 模型定义
├── stt_service.py        # STT 服务：封装 DashScope fun-asr-realtime
├── tts_service.py        # TTS 服务：封装 DashScope cosyvoice-v3-flash
├── voice_prompt.py       # 已弃用的兼容模块；VoiceAgent 不再依赖
├── tutor_skill_runtime.py # 当前讲师 Skill 的加载、模板渲染与契约校验
├── voice_agent.py        # Voice Agent：会话编排、检索与模型调用
├── session.py            # 会话管理：状态机 + 打断处理 + TTS 流式
└── server.py             # WebSocket 端点：消息路由 + 连接管理
```

---

## 3. 核心架构

### 3.1 数据流

```
用户说话 → WebSocket 音频流 → STT 识别文字 → VoiceAgent 生成回复文本 → TTS 合成音频 → WebSocket 返回音频流
```

### 3.2 会话状态机

```
Idle → (start_session) → Listening → (audio_data) → Processing → (TTS返回) → Speaking
  ↑                        ↑              ↑                ↑              |
  └── (end_session) ───────┴──────────────┴────────────────┴──────────────┘
  打断: Speaking → (interrupt) → Listening（保留上下文）
```

### 3.3 依赖关系

```
voice_agent.py
  ├── agno.agent.Agent（agno 2.5.10）
  ├── agno.models.dashscope.DashScope
  ├── agno_agent.tools.retrieve_tool.knowledge_retrieve_auto_tool（复用 RAG）
  ├── agno_agent.tools.web_search_tool.get_web_search_results（复用搜索）
  └── voice.tutor_skill_runtime（激活并执行项目内 Skill）

session.py
  ├── voice.stt_service.STTService
  ├── voice.tts_service.TTSService
  ├── voice.voice_agent.VoiceAgent
  └── voice.protocol.SessionState

server.py
  ├── voice.protocol（消息解析）
  └── voice.session.VoiceSessionManager
```

---

## 4. 关键设计决策

### 4.1 为什么新建 VoiceAgent 而不复用 QAAgent

| 维度 | QAAgent | VoiceAgent |
|------|---------|------------|
| Prompt | 结构化，包含 `<answer>`/`<references>` 标签 | 口语化，无结构化标签 |
| 回复长度 | 不限制（可能很长） | 150 字以内，最多 4 句话 |
| 工具 | 5 个（含 OCR、文档阅读、附件处理） | 2 个（仅 RAG 和搜索） |
| 输出格式 | Markdown | 纯文本 |

### 4.2 为什么不修改现有源码

- 语音模块是独立功能，不应影响现有文本聊天
- 避免引入回归风险
- 便于独立测试和部署

### 4.3 Pydantic v2 兼容

协议文件使用 `Literal` 类型替代已废弃的 `const=True`：

```python
# 正确（Pydantic v2）
type: Literal["start_session"] = "start_session"

# 错误（Pydantic v1，已废弃）
type: str = Field(default="start_session", const=True)
```

---

## 5. 配置说明

### 5.1 config.ini `[voice_config]` 段

```ini
[voice_config]
dashscope_api_key_dev = <configure-locally>  # 语音服务 API Key
stt_model = <stt-model-name>         # STT 模型
sample_rate = 16000                   # 采样率
tts_model = <tts-model-name>         # TTS 模型
default_voice_id = <voice-id>        # 默认音色
voice_model_name_dev = <voice-llm-name>  # Voice Agent 使用的 LLM
voice_tutor_skill = voice-tutor-guided-practice
max_session_duration_min = 30        # 最大会话时长（分钟）
session_idle_timeout_sec = 300       # 空闲超时（秒）
max_response_length = 200            # 最大回复字符数
```

### 5.2 config.py 读取逻辑

```python
# src/voice/config.py
DASHSCOPE_API_KEY = config.get("voice_config", f"dashscope_api_key_{env}", fallback="")
VOICE_MODEL_NAME = config.get("voice_config", f"voice_model_name_{env}", fallback="<voice-llm-name>")
VOICE_TUTOR_SKILL_NAME = os.getenv("VOICE_TUTOR_SKILL") or config.get(
    "voice_config", "voice_tutor_skill", fallback="voice-tutor-guided-practice"
)
# ... 其他配置项
```

环境变量优先于 `config.ini`。后续加入新的讲师 Skill 后，可以设置
`VOICE_TUTOR_SKILL=<skill-name>` 切换，不需要修改 `voice_agent.py`。Skill 是讲师
行为的唯一来源；如果 Skill 缺失、清单错误或脚本契约不完整，服务会明确启动失败，
不会静默回退到另一套 prompt。

---

## 6. WebSocket 协议速查

### 前端 → 后端

| type | 说明 | 关键字段 |
|------|------|----------|
| `start_session` | 开始会话 | `user_id`, `session_id`, `voice_id` |
| `audio_data` | 音频数据 | `audio`(Base64), `format` |
| `interrupt` | 打断 | — |
| `end_session` | 结束会话 | — |
| `switch_voice` | 切换音色 | `voice_id` |

### 后端 → 前端

| type | 说明 | 关键字段 |
|------|------|----------|
| `session_started` | 会话已建立 | `session_id` |
| `stt_partial` | 中间识别结果 | `text`, `is_final` |
| `stt_final` | 最终识别结果 | `text` |
| `agent_thinking` | Agent 处理中 | — |
| `agent_text` | Agent 回复文本 | `text`, `is_final` |
| `audio_chunk` | TTS 音频块 | `audio`(Base64), `is_last` |
| `error` | 错误信息 | `code`, `message` |

---

## 7. 可用音色列表

```
longanhuan_zh_v3      # 默认
longxiaoxia_v3        # 龙筱夏
longlaopan_v3         # 龙老潘
longyunque_v3         # 龙云雀
longyouben_v3         # 龙优本
longmiao_v3           # 龙喵
longshuangkuai_v3     # 龙爽快
longjingying_v3       # 龙精英
longjiaorou_v3        # 龙娇柔
longchunqing_v3       # 龙纯情
longmeirenyin_v3      # 龙美人音
longmeinv_v3          # 龙美女
longmeinan_v3         # 龙美男
longtianmei_v3        # 龙甜美
longshaonv_v3         # 龙少女
longjieer_v3          # 龙姐儿
longqinmie_v3         # 龙亲切
longmeiniang_v3       # 龙美娘
longyuantiandian_v3   # 龙元气甜
longmeiyu_v3          # 龙御姐
```

---

## 8. 后续开发注意事项

### 8.1 不要修改的文件

- `src/algo/agent.py` — 现有 QAAgent，与语音模块无关
- `src/algo/prompt_center.py` — 现有 prompt 管理
- `src/agno_agent/` — 现有 agent 工具和框架

### 8.2 可以扩展的方向

1. **新增音色** — 在 `config.py` 的 `AVAILABLE_VOICES` 字典中添加
2. **新增工具** — 在 `voice_agent.py` 的 `self.tools` 列表中添加
3. **修改当前讲师行为** — 修改 `skills/voice-tutor-guided-practice/SKILL.md` 与对应 `references/`
4. **调整 Skill 回复长度** — 修改该 Skill 的 `references/runtime.json`
5. **新增 WebSocket 消息类型** — 在 `protocol.py` 中添加模型，在 `server.py` 中添加路由
6. **新增讲师模式** — 新建独立 Skill，提供 `SKILL.md`、`references/runtime.json` 和 `scripts/postprocess_response.py`，再通过配置切换

讲师 Skill 负责教学 prompt、修复 prompt，以及题目解析、答案识别、重复题限制、
输出清洗等确定性契约。`voice_agent.py` 只负责编排流程，禁止复制这些规则。

当前提供两种讲师 Skill：

| Skill | 模式 | 行为 |
|------|------|------|
| `voice-tutor-guided-practice` | `guided_practice` | 结合资料出题、判题、讲解，最多三题后总结 |
| `voice-tutor-explain-only` | `explain_only` | 结合用户岗位、经验和使用场景直接讲解，不出题、不判题 |

切换到纯讲解模式后重启后端：

```bash
VOICE_TUTOR_SKILL=voice-tutor-explain-only .venv/bin/python run_web_api.py
```

也可以把 `config.ini` 中的 `voice_tutor_skill` 改为
`voice-tutor-explain-only`。纯讲解 Skill 会在身份和场景缺失时合并询问一次；获得
信息后立即回到用户原来的技术问题，并针对操作、检修、安全、培训、管理、考试等
不同用途调整讲解重点，但不会借此补充资料之外的规定或操作要求。

### 8.3 测试

```bash
# 运行烟雾测试
cd D:\agent\app-rag-agent-me
python -m pytest tests/test_voice_smoke.py -v

# 运行讲师 Skill 契约测试
python -m pytest tests/test_voice_tutor_skill.py -v

# 手动测试 WebSocket（需要前端或 wscat）
wscat -c ws://localhost:8000/voice/chat
```

### 8.4 启动服务

```bash
cd D:\agent\app-rag-agent-me
.venv/Scripts/python.exe run_web_api.py
```

预期日志：
```
[VoiceConfig] STT=fun-asr-realtime, TTS=cosyvoice-v3-flash, Voice=longanhuan_zh_v3
```

---

## 9. 性能目标

| 环节 | 目标延迟 |
|------|----------|
| STT 识别 | < 500ms |
| Agent 生成（首 token） | < 1s |
| TTS 合成（首字节） | < 300ms |
| 总响应（用户说完到听到回复） | < 2s |

---

## 10. 已知限制

1. **STT 采样率**：必须 16kHz PCM，前端需要 AudioWorklet 采集
2. **TTS 流式**：分句合成，按句号/问号/感叹号分割
3. **打断延迟**：取决于 WebSocket 消息往返时间
4. **会话超时**：空闲 5 分钟自动关闭
5. **并发**：每个 WebSocket 连接对应一个独立会话
