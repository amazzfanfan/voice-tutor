# app-rag-agent-me

`app-rag-agent-me` 是一个基于 FastAPI 的智能问答与语音讲师后端。项目既提供通用 RAG 问答接口，也提供面向实时语音交互的 WebSocket 服务。

语音讲师支持实时语音识别、用户身份与使用场景识别、追问语义判断、Wiki 与 RAG 并行检索、知识融合、联网降级检索、口语化回答生成，以及分段语音合成与播放状态管理。

## 核心流程

1. 前端通过 WebSocket 建立语音会话并发送音频。
2. STT 将音频实时转换为文本。
3. 讲师 Agent 识别用户意图、身份、场景，以及当前输入是否属于追问。
4. Wiki 与 RAG 并行检索：
   - Wiki 提供概念、结构和核心知识框架。
   - RAG 提供规章原文、参数、案例和培训资料片段。
5. 后端对两路结果去重、筛选并融合；本地资料不足且检索来源异常或超时时，尝试联网搜索。
6. 大模型结合用户身份和使用场景生成适合朗读的讲解内容。
7. TTS 按完整语句分段合成，逐段发送到前端；单段失败时自动重试。

## 主要接口

| 类型 | 地址 | 用途 |
| --- | --- | --- |
| HTTP POST | `/app-rag-agent-me/rag-chat` | 通用 RAG 对话，使用 SSE 返回结果 |
| WebSocket | `/voice/chat` | 实时语音讲师会话 |
| HTTP GET | `/docs` | Swagger API 文档 |

本地默认服务地址为 `http://127.0.0.1:18000`，因此语音 WebSocket 地址为：

```text
ws://127.0.0.1:18000/voice/chat
```

## 环境要求

- Python 3.9 及以上版本
- 可用的 DashScope/OpenAI 兼容模型服务
- RAG 检索服务（使用 `rag_only` 或 `rag_wiki` 模式时需要）
- Wiki 服务（使用 `wiki_only` 或 `rag_wiki` 模式时需要）
- 支持麦克风和音频播放的 Voice 前端

## 安装依赖

在项目根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

如需运行测试，再安装 `pytest`：

```bash
.venv/bin/python -m pip install pytest
```

## 配置说明

仓库只保留脱敏模板。首次运行时先创建本地配置：

```bash
cp src/conf/config.ini.example src/conf/config.ini
```

主配置文件位于 `src/conf/config.ini`，并已被仓库根目录的 `.gitignore` 排除。请只在本地填写真实凭据，首次部署时重点检查以下配置段。

### 基础服务配置

在 `[paths]` 中配置业务后端和检索服务地址：

```ini
[paths]
backend_server = https://backend.example.com
retrieval_server = http://127.0.0.1:18001
retrieve_chunk_url = /api/retrieve/chunks
web_search_url = /api/search/web
```

### 模型及对象存储配置

根据运行环境配置以下内容：

- `[llm_config]`：模型名称、OpenAI 兼容 API 地址和 API Key。
- `[minio_config]`：MinIO 地址、Access Key、Secret Key、Bucket 和 HTTPS 开关。
- `[embeddings_config]`：嵌入模型名称、服务地址和 API Key。
- `[ocr_config]`：OCR 服务地址。

请勿提交真实密钥；生产环境建议通过部署平台的密钥管理能力注入配置。

### 语音讲师配置

在 `[voice_config]` 中配置 STT、TTS、讲师模型、Skill 和知识源：

```ini
[voice_config]
dashscope_api_key_dev = <DashScope API Key>
stt_model = <STT 模型名称>
sample_rate = 16000
tts_model = <TTS 模型名称>
default_voice_id = <音色 ID>
voice_model_name_dev = <讲师模型名称>
voice_tutor_skill = voice-tutor-explain-only

# rag_only、wiki_only 或 rag_wiki；当前默认仅使用 RAG
voice_knowledge_source = rag_only
voice_rag_file_ids = <RAG 资料文件名>

llm_wiki_base_url = http://127.0.0.1:8888
llm_wiki_username = <Wiki 用户名>
llm_wiki_password = <Wiki 密码>
llm_wiki_workspace = <Wiki 工作空间>
```

语音模块支持使用环境变量覆盖部分运行参数：

| 环境变量 | 说明 |
| --- | --- |
| `VOICE_TUTOR_SKILL` | 当前启用的讲师 Skill |
| `VOICE_KNOWLEDGE_SOURCE` | 知识源模式：`rag_only`、`wiki_only`、`rag_wiki` |
| `LLM_WIKI_BASE_URL` | Wiki 服务地址 |
| `LLM_WIKI_USERNAME` | Wiki 登录用户名 |
| `LLM_WIKI_PASSWORD` | Wiki 登录密码 |
| `LLM_WIKI_WORKSPACE` | Wiki 工作空间 |
| `VOICE_WIKI_TIMEOUT_SEC` | Wiki 单路检索超时时间 |
| `VOICE_RAG_TIMEOUT_SEC` | RAG 单路检索超时时间 |
| `VOICE_RAG_FILE_IDS` | 限定 RAG 检索文件，多个文件名用英文逗号分隔 |
| `VOICE_RETRIEVAL_TOTAL_TIMEOUT_SEC` | 并行检索总等待时间 |
| `VOICE_WEB_FALLBACK_TIMEOUT_SEC` | 联网降级检索超时时间 |

`DASHSCOPE_API_KEY` 可作为语音 API Key 的环境变量后备值；如果 `config.ini` 已配置 `dashscope_api_key_dev`，则优先使用配置文件中的值。

## 启动 Voice 后端

在项目根目录执行：

```bash
.venv/bin/python run_web_api.py
```

服务默认监听：

```text
http://0.0.0.0:18000
```

## 本地完整联调

当知识源模式为 `rag_wiki` 时，建议依次启动以下服务。

### 1. 启动 Wiki 后端

```bash
cd <llm-wiki-demo 项目目录>
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8888 --workers 4
```

### 2. 启动 Wiki 前端

```bash
cd <llm-wiki-demo/web 项目目录>
npm install
npm run dev -- --host 0.0.0.0
```

### 3. 启动 RAG 检索服务

在 `app-retrieval-service-me` 项目中按其项目说明启动服务，并确保监听地址与 `retrieval_server` 配置一致，默认端口为 `18001`。

### 4. 启动 Voice 后端

```bash
cd <app-rag-agent-me 项目目录>
.venv/bin/python run_web_api.py
```

### 5. 启动 Voice 前端

```bash
cd <voice-fronted 项目目录>
npm install
BROWSER=none npm start
```

## 运行测试

```bash
.venv/bin/python -m pytest tests -q
```

## 目录结构

```text
app-rag-agent-me/
├── run_web_api.py                 # 本地启动入口
├── requirements.txt               # Python 依赖
├── src/
│   ├── algo/                      # FastAPI 应用、通用问答及配置加载
│   ├── agno_agent/                # 通用 Agent、文档与检索工具
│   ├── voice/                     # STT、TTS、会话、检索融合及语音 Agent
│   └── conf/config.ini.example    # 脱敏配置模板
├── skills/
│   ├── voice-tutor-explain-only/  # 讲解型讲师 Skill
│   └── voice-tutor-guided-practice/ # 引导练习型讲师 Skill
└── tests/                          # Voice 模块测试
```

## 常见问题

- Wiki 或 RAG 调用失败：检查对应服务是否启动、地址是否正确，以及超时配置是否满足当前网络环境。
- Wiki 登录失败：检查用户名、密码、工作空间名称，以及 Wiki 后端对象存储配置。
- 语音无法识别：确认浏览器已获得麦克风权限，前端采样格式与后端 `sample_rate` 一致。
- 回答有文字但没有声音：检查 DashScope Key、TTS 模型和音色配置，并查看后端日志中的分段合成状态。
- 播放结束后无法继续说话：确认前端在播放完成后发送 `playback_finished` 消息，后端收到后会恢复监听。
