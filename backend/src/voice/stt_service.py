"""DashScope fun-asr-realtime STT service wrapper."""

import asyncio
import json
import threading
from typing import Any, Callable, Dict, Optional
import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback
from voice.config import DASHSCOPE_API_KEY, STT_MODEL, SAMPLE_RATE
from algo.config import my_logger


class STTCallback(RecognitionCallback):
    """Callback handler for speech recognition results."""

    def __init__(
        self,
        session_id: str,
        on_partial: Callable,
        on_final: Callable,
        on_complete: Optional[Callable],
        loop: asyncio.AbstractEventLoop,
    ):
        self.session_id = session_id
        self.on_partial = on_partial
        self.on_final = on_final
        self._on_complete_cb = on_complete
        self._loop = loop
        self._terminal_notified = False
        self._terminal_lock = threading.Lock()

    def _notify_terminal(self) -> None:
        """Notify the session once after either completion or an ASR error."""
        with self._terminal_lock:
            if self._terminal_notified:
                return
            self._terminal_notified = True
        if self._on_complete_cb:
            asyncio.run_coroutine_threadsafe(
                self._on_complete_cb(), self._loop
            )

    def on_open(self) -> None:
        """Called when the recognition session opens."""
        my_logger.info(f"[STT] Session {self.session_id} opened")

    def on_complete(self) -> None:
        """Called when recognition is complete."""
        my_logger.info(f"[STT] Session {self.session_id} completed")
        self._notify_terminal()

    def on_error(self, error) -> None:
        """Called when an error occurs.

        DashScope SDK passes a RecognitionResult object (not a string).
        """
        if hasattr(error, 'status_code'):
            my_logger.error(f"[STT] Session {self.session_id} error: "
                          f"status={error.status_code}, code={error.code}, "
                          f"message={error.message}")
        else:
            my_logger.error(f"[STT] Session {self.session_id} error: {error}")
        # DashScope may emit EmptyAudio through on_error without a later
        # on_complete callback. Notify the Voice session so it can recreate
        # recognition instead of remaining permanently stuck.
        self._notify_terminal()

    def on_close(self) -> None:
        """Called when the recognition session closes."""
        my_logger.info(f"[STT] Session {self.session_id} closed")

    def on_event(self, result: Any) -> None:
        """Called when a recognition result is received.

        DashScope SDK passes a RecognitionResult object (not a dict).
        It has .output dict with "sentence" key containing text/sentence_end.
        """
        if not result:
            return

        try:
            # RecognitionResult has .output attribute (dict)
            output = result.output if hasattr(result, 'output') else result

            sentence_data = output.get("sentence", {}) if isinstance(output, dict) else {}

            sentence = sentence_data.get("text", "") if isinstance(sentence_data, dict) else ""
            is_end = sentence_data.get("sentence_end", False) if isinstance(sentence_data, dict) else False

            if sentence:
                if is_end:
                    my_logger.info(f"[STT] Final result: {sentence}")
                    asyncio.run_coroutine_threadsafe(
                        self.on_final(sentence), self._loop
                    )
                else:
                    asyncio.run_coroutine_threadsafe(
                        self.on_partial(sentence, False), self._loop
                    )
        except Exception as e:
            my_logger.error(f"[STT] Error parsing result: {e}")


class STTSession:
    """Manages a single STT recognition session."""

    def __init__(
        self,
        session_id: str,
        on_partial: Callable,
        on_final: Callable,
        on_complete: Optional[Callable] = None,
    ):
        self.session_id = session_id
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_complete = on_complete
        self._recognizer: Optional[Recognition] = None
        self._callback: Optional[STTCallback] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self, loop: asyncio.AbstractEventLoop):
        """Start the recognition session."""
        self._loop = loop
        my_logger.info(f"[STT] Starting recognition for session {self.session_id}")

        # Create callback handler
        self._callback = STTCallback(
            session_id=self.session_id,
            on_partial=self.on_partial,
            on_final=self.on_final,
            on_complete=self.on_complete,
            loop=loop,
        )

        # Create recognizer with correct parameters
        self._recognizer = Recognition(
            model=STT_MODEL,
            format='pcm',
            sample_rate=SAMPLE_RATE,
            callback=self._callback,
        )

        # Start recognition
        self._recognizer.start()

    def feed_audio(self, audio_data: bytes):
        """Send audio chunk to the recognizer."""
        if self._recognizer:
            my_logger.info(f"[STT] Session {self.session_id} feed_audio: {len(audio_data)} bytes")
            self._recognizer.send_audio_frame(audio_data)
        else:
            my_logger.warning(f"[STT] Session {self.session_id} feed_audio: recognizer is None")

    def stop(self):
        """Stop recognition and get final result."""
        if self._recognizer:
            my_logger.info(f"[STT] Stopping recognition for session {self.session_id}")
            self._recognizer.stop()

    def close(self):
        """Clean up resources."""
        if self._recognizer:
            try:
                self._recognizer.stop()
            except Exception:
                pass
            self._recognizer = None
            self._callback = None


class STTService:
    """Manages multiple STT sessions."""

    def __init__(self):
        self._sessions: Dict[str, STTSession] = {}
        dashscope.api_key = DASHSCOPE_API_KEY

    def create_session(
        self,
        session_id: str,
        on_partial: Callable,
        on_final: Callable,
        on_complete: Optional[Callable],
        loop: asyncio.AbstractEventLoop,
    ) -> STTSession:
        """Create and start a new STT session."""
        stt_session = STTSession(session_id, on_partial, on_final, on_complete)
        stt_session.start(loop)
        self._sessions[session_id] = stt_session
        return stt_session

    def get_session(self, session_id: str) -> Optional[STTSession]:
        return self._sessions.get(session_id)

    def remove_session(self, session_id: str):
        """Close and remove a session."""
        session = self._sessions.pop(session_id, None)
        if session:
            session.close()

    def close_all(self):
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()
