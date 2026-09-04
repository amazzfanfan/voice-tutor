"""WebSocket message protocol definitions for voice tutor."""

from enum import Enum
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel

from voice.config import DEFAULT_VOICE_ID


# --- Session States ---

class SessionState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"


# --- Frontend -> Backend Messages ---

class StartSessionMsg(BaseModel):
    type: Literal["start_session"] = "start_session"
    user_id: str
    session_id: str
    voice_id: str = DEFAULT_VOICE_ID
    config: Dict[str, Any] = {}


class AudioDataMsg(BaseModel):
    type: Literal["audio_data"] = "audio_data"
    audio: str  # Base64 encoded audio
    format: str = "pcm"  # "pcm" or "wav"


class StopAudioMsg(BaseModel):
    type: Literal["stop_audio"] = "stop_audio"


class InterruptMsg(BaseModel):
    type: Literal["interrupt"] = "interrupt"


class PlaybackFinishedMsg(BaseModel):
    type: Literal["playback_finished"] = "playback_finished"


class EndSessionMsg(BaseModel):
    type: Literal["end_session"] = "end_session"


class SwitchVoiceMsg(BaseModel):
    type: Literal["switch_voice"] = "switch_voice"
    voice_id: str


class UpdateConfigMsg(BaseModel):
    type: Literal["update_config"] = "update_config"
    config: Dict[str, Any] = {}


# --- Backend -> Frontend Messages ---

class SessionStartedMsg(BaseModel):
    type: str = "session_started"
    session_id: str


class STTPartialMsg(BaseModel):
    type: str = "stt_partial"
    text: str
    is_final: bool = False


class STTFinalMsg(BaseModel):
    type: str = "stt_final"
    text: str


class AgentThinkingMsg(BaseModel):
    type: str = "agent_thinking"


class AgentTextMsg(BaseModel):
    type: str = "agent_text"
    text: str
    is_final: bool = False


class AudioChunkMsg(BaseModel):
    type: str = "audio_chunk"
    audio: str  # Base64 encoded audio
    is_last: bool = False


class AudioStreamEndMsg(BaseModel):
    """Sent when all TTS audio chunks have been delivered."""
    type: str = "audio_stream_end"


class SessionEndedMsg(BaseModel):
    type: str = "session_ended"
    reason: str = "normal"


class ErrorMsg(BaseModel):
    type: str = "error"
    code: str
    message: str


# --- Helper ---

def parse_frontend_msg(data: dict) -> BaseModel:
    """Parse incoming WebSocket message into the appropriate model."""
    msg_type = data.get("type")
    parsers = {
        "start_session": StartSessionMsg,
        "audio_data": AudioDataMsg,
        "stop_audio": StopAudioMsg,
        "interrupt": InterruptMsg,
        "playback_finished": PlaybackFinishedMsg,
        "end_session": EndSessionMsg,
        "switch_voice": SwitchVoiceMsg,
        "update_config": UpdateConfigMsg,
    }
    parser = parsers.get(msg_type)
    if parser is None:
        raise ValueError(f"Unknown message type: {msg_type}")
    return parser(**data)
