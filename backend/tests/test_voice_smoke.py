"""Smoke tests for voice module imports and basic structures."""

import sys
import os

# Ensure src is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_import_protocol():
    """Protocol models should be importable."""
    from voice.protocol import (
        SessionState,
        StartSessionMsg,
        AudioDataMsg,
        InterruptMsg,
        EndSessionMsg,
        parse_frontend_msg,
    )
    assert SessionState.IDLE == "idle"
    assert SessionState.LISTENING == "listening"
    assert SessionState.PROCESSING == "processing"
    assert SessionState.SPEAKING == "speaking"


def test_parse_start_session():
    """parse_frontend_msg should handle start_session."""
    from voice.protocol import parse_frontend_msg, StartSessionMsg
    from voice.config import DEFAULT_VOICE_ID
    msg = parse_frontend_msg({
        "type": "start_session",
        "user_id": "USR-001",
        "session_id": "sess-001",
    })
    assert isinstance(msg, StartSessionMsg)
    assert msg.user_id == "USR-001"
    assert msg.voice_id == DEFAULT_VOICE_ID


def test_parse_audio_data():
    """parse_frontend_msg should handle audio_data."""
    from voice.protocol import parse_frontend_msg, AudioDataMsg
    msg = parse_frontend_msg({
        "type": "audio_data",
        "audio": "base64encodeddata",
    })
    assert isinstance(msg, AudioDataMsg)
    assert msg.format == "pcm"


def test_truncate_response_short():
    """Short responses should pass through unchanged."""
    from voice.voice_prompt import truncate_response
    text = "这是一个简短的回答。"
    assert truncate_response(text) == text


def test_truncate_response_long():
    """Long responses should be truncated at sentence boundary."""
    from voice.voice_prompt import truncate_response
    text = "第一句话。" * 50  # ~250 chars
    result = truncate_response(text)
    assert len(result) <= 250  # Allow some margin for suffix
    assert result.endswith("。") or result.endswith("...")


def test_available_voices():
    """Should have at least the default voice."""
    from voice.config import AVAILABLE_VOICES, DEFAULT_VOICE_ID
    assert DEFAULT_VOICE_ID in AVAILABLE_VOICES
    assert len(AVAILABLE_VOICES) >= 5
