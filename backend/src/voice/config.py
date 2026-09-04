"""Voice module configuration - reads from config.ini and environment."""

import os
from algo.config import my_config_parser, my_logger, EXTERNAL_OPENAI_API_KEY


def _voice_int(name: str, option: str, fallback: int) -> int:
    """Read a positive integer with environment override and a safe fallback."""
    raw = os.getenv(name) or my_config_parser.get(
        "voice_config", option, fallback=str(fallback)
    )
    try:
        value = int(raw)
        return value if value > 0 else fallback
    except (TypeError, ValueError):
        my_logger.warning(f"[VoiceConfig] Invalid {name}={raw!r}, use {fallback}")
        return fallback


def _voice_float(name: str, option: str, fallback: float) -> float:
    """Read a positive float with environment override and a safe fallback."""
    raw = os.getenv(name) or my_config_parser.get(
        "voice_config", option, fallback=str(fallback)
    )
    try:
        value = float(raw)
        return value if value > 0 else fallback
    except (TypeError, ValueError):
        my_logger.warning(f"[VoiceConfig] Invalid {name}={raw!r}, use {fallback}")
        return fallback


def _voice_list(name: str, option: str, fallback: str = "") -> list[str]:
    """Read a comma-separated list with environment override."""
    raw = os.getenv(name)
    if raw is None:
        raw = my_config_parser.get("voice_config", option, fallback=fallback)
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]

# DashScope API key: config.ini takes priority, fallback to env var
DASHSCOPE_API_KEY = my_config_parser.get(
    "voice_config", "dashscope_api_key_dev", fallback=None
) or os.getenv("DASHSCOPE_API_KEY", EXTERNAL_OPENAI_API_KEY)

# STT
STT_MODEL = my_config_parser.get("voice_config", "stt_model", fallback="fun-asr-realtime")
SAMPLE_RATE = my_config_parser.getint("voice_config", "sample_rate", fallback=16000)

# TTS
TTS_MODEL = my_config_parser.get("voice_config", "tts_model", fallback="cosyvoice-v3-flash")
DEFAULT_VOICE_ID = my_config_parser.get("voice_config", "default_voice_id", fallback="longyumi_v3")

# Voice agent LLM
VOICE_MODEL_NAME = my_config_parser.get(
    "voice_config", "voice_model_name_dev", fallback="<voice-llm-name>"
)

# Tutor behavior package. The environment variable overrides config.ini so a
# new Skill can be selected without changing application code.
VOICE_TUTOR_SKILL_NAME = os.getenv("VOICE_TUTOR_SKILL") or my_config_parser.get(
    "voice_config", "voice_tutor_skill", fallback="voice-tutor-guided-practice"
)

# Knowledge source for VoiceAgent:
# - rag_only: use the existing retrieval-service RAG only
# - wiki_only: use llm-wiki-demo /api/wiki/retrieve only
# - rag_wiki: retrieve from both sources and merge the contexts
VOICE_KNOWLEDGE_SOURCE = (
    os.getenv("VOICE_KNOWLEDGE_SOURCE")
    or my_config_parser.get("voice_config", "voice_knowledge_source", fallback="rag_only")
).strip().lower()

# llm-wiki-demo retrieve API configuration. Username/password are used to
# obtain a short-lived login token automatically.
LLM_WIKI_BASE_URL = (
    os.getenv("LLM_WIKI_BASE_URL")
    or my_config_parser.get("voice_config", "llm_wiki_base_url", fallback="http://127.0.0.1:8888")
).rstrip("/")
LLM_WIKI_USERNAME = (
    os.getenv("LLM_WIKI_USERNAME")
    or my_config_parser.get("voice_config", "llm_wiki_username", fallback="")
).strip()
LLM_WIKI_PASSWORD = (
    os.getenv("LLM_WIKI_PASSWORD")
    or my_config_parser.get("voice_config", "llm_wiki_password", fallback="")
).strip()
LLM_WIKI_WORKSPACE = (
    os.getenv("LLM_WIKI_WORKSPACE")
    or my_config_parser.get("voice_config", "llm_wiki_workspace", fallback="")
).strip()
LLM_WIKI_MAX_CHARS = int(
    os.getenv("LLM_WIKI_MAX_CHARS")
    or my_config_parser.get("voice_config", "llm_wiki_max_chars", fallback="20000")
)

# Voice-side latency budget and deterministic fusion limits. These settings do
# not alter either the Wiki API or retrieval-service ranking parameters.
VOICE_WIKI_TIMEOUT_SEC = _voice_float(
    "VOICE_WIKI_TIMEOUT_SEC", "voice_wiki_timeout_sec", 18.0
)
VOICE_RAG_TIMEOUT_SEC = _voice_float(
    "VOICE_RAG_TIMEOUT_SEC", "voice_rag_timeout_sec", 20.0
)
VOICE_RAG_FILE_IDS = _voice_list(
    "VOICE_RAG_FILE_IDS", "voice_rag_file_ids"
)
VOICE_RETRIEVAL_TOTAL_TIMEOUT_SEC = _voice_float(
    "VOICE_RETRIEVAL_TOTAL_TIMEOUT_SEC", "voice_retrieval_total_timeout_sec", 20.5
)
VOICE_WIKI_CONTEXT_MAX_CHARS = _voice_int(
    "VOICE_WIKI_CONTEXT_MAX_CHARS", "voice_wiki_context_max_chars", 2500
)
VOICE_RAG_MAX_CHUNKS = _voice_int(
    "VOICE_RAG_MAX_CHUNKS", "voice_rag_max_chunks", 5
)
VOICE_RAG_CHUNK_MAX_CHARS = _voice_int(
    "VOICE_RAG_CHUNK_MAX_CHARS", "voice_rag_chunk_max_chars", 900
)
VOICE_RAG_CONTEXT_MAX_CHARS = _voice_int(
    "VOICE_RAG_CONTEXT_MAX_CHARS", "voice_rag_context_max_chars", 3000
)
VOICE_FUSION_MAX_CHARS = _voice_int(
    "VOICE_FUSION_MAX_CHARS", "voice_fusion_max_chars", 4500
)
VOICE_WEB_FALLBACK_TIMEOUT_SEC = _voice_float(
    "VOICE_WEB_FALLBACK_TIMEOUT_SEC", "voice_web_fallback_timeout_sec", 3.0
)

# Session limits
MAX_SESSION_DURATION_MIN = my_config_parser.getint("voice_config", "max_session_duration_min", fallback=30)
SESSION_IDLE_TIMEOUT_SEC = my_config_parser.getint("voice_config", "session_idle_timeout_sec", fallback=300)
MAX_RESPONSE_LENGTH = my_config_parser.getint("voice_config", "max_response_length", fallback=200)

# Available voices for cosyvoice-v3-flash
AVAILABLE_VOICES = {
    "longyumi_v3": "YUMI（默认，正经青年女）",
    "longxiaoxia_v3": "龙小夏（沉稳权威女）",
    "longxiaochun_v3": "龙小淳（知性积极女）",
    "longanwen_v3": "龙安温（优雅知性女）",
    "longshuo_v3": "龙硕（博才干练男）",
    "longshu_v3": "龙书（沉稳青年男）",
    "longmiao_v3": "龙妙（抑扬顿挫女）",
    "longsanshu_v3": "龙三叔（沉稳质感男）",
    "longanhuan_v3": "龙安欢（欢脱元气女）",
}

my_logger.info(f"[VoiceConfig] STT={STT_MODEL}, TTS={TTS_MODEL}, Voice={DEFAULT_VOICE_ID}")
