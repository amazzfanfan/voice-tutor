"""Tests for Voice STT terminal-state recovery."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.mark.asyncio
async def test_stt_error_notifies_session_once_even_if_complete_follows():
    from voice.stt_service import STTCallback

    on_complete = AsyncMock()
    callback = STTCallback(
        session_id="stt-error-session",
        on_partial=AsyncMock(),
        on_final=AsyncMock(),
        on_complete=on_complete,
        loop=asyncio.get_running_loop(),
    )

    error = type(
        "RecognitionError",
        (),
        {"status_code": 44, "code": "EmptyAudio", "message": "EmptyAudio"},
    )()
    callback.on_error(error)
    callback.on_complete()
    await asyncio.sleep(0.01)

    on_complete.assert_awaited_once()


def test_microphone_resumes_quickly_after_playback():
    from voice.session import VoiceSession

    assert VoiceSession.RESUME_CAPTURE_DELAY_SEC == 0.5
