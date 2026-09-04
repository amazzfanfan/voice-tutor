"""Voice session manager - handles session lifecycle, state machine, interruption."""

import asyncio
import base64
import json
import time
from typing import Callable, Dict, List, Optional
from voice.config import SESSION_IDLE_TIMEOUT_SEC, MAX_SESSION_DURATION_MIN
from voice.protocol import SessionState, AudioStreamEndMsg
from voice.stt_service import STTService, STTSession
from voice.tts_service import TTSService
from voice.voice_agent import VoiceAgent
from voice.debug_log import flow_log
from algo.config import my_logger
from agno_agent.tool import clear_tool_runtime_context


_PCM_22050_MONO_16BIT_BYTES_PER_SECOND = 22050 * 2
_MIN_PLAYBACK_TIMEOUT_SEC = 60.0
_PLAYBACK_TIMEOUT_GRACE_SEC = 15.0


def _playback_timeout_for_audio(audio_duration_sec: float) -> float:
    """Allow long audio to finish while retaining a missing-event fallback."""
    return max(
        _MIN_PLAYBACK_TIMEOUT_SEC,
        audio_duration_sec + _PLAYBACK_TIMEOUT_GRACE_SEC,
    )


class VoiceSession:
    """Single voice conversation session with state machine."""

    def __init__(
        self,
        session_id: str,
        user_id: str,
        voice_id: str,
        stt_service: STTService,
        send_msg: Callable,
        loop: asyncio.AbstractEventLoop,
        conversation_history: Optional[List[dict]] = None,
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.voice_id = voice_id
        self.state = SessionState.IDLE
        self.created_at = time.time()
        self.last_active = time.time()

        self.agent = VoiceAgent()
        self.agent.restore_conversation_history(
            self.session_id,
            conversation_history or [],
        )
        self.tts = TTSService()
        self.stt_service = stt_service

        self._send_msg = send_msg
        self._loop = loop
        self._websocket = None  # Set by server.py for direct awaitable sends
        self._current_task: Optional[asyncio.Task] = None
        self._stt_session: Optional[STTSession] = None
        self._stt_final_received: bool = False
        self._has_spoken: bool = False
        self._is_closed: bool = False
        self._capture_timer: Optional[asyncio.TimerHandle] = None
        self._playback_timeout: Optional[asyncio.TimerHandle] = None
        self._tts_streaming: bool = False
        self._deferred_activation: bool = False  # playback_finished 到达时 TTS 还在流式传输

    @property
    def is_alive(self) -> bool:
        return (time.time() - self.created_at) < MAX_SESSION_DURATION_MIN * 60

    @property
    def is_idle_timeout(self) -> bool:
        return (time.time() - self.last_active) > SESSION_IDLE_TIMEOUT_SEC

    # Browser echo cancellation already suppresses speaker tail. Keep only a
    # short guard so users speaking immediately after playback are not clipped.
    RESUME_CAPTURE_DELAY_SEC = 0.5

    def start_listening(self, force_stt: bool = False):
        """Transition to LISTENING state.

        First call (before AI has spoken): creates STT immediately.
        After AI spoke: waits for playback_finished + delay before creating STT
        and sending start_capture to frontend.
        """
        self.state = SessionState.LISTENING
        self.last_active = time.time()

        # Cancel pending timers
        if self._capture_timer:
            self._capture_timer.cancel()
            self._capture_timer = None
        if self._playback_timeout:
            self._playback_timeout.cancel()
            self._playback_timeout = None

        if force_stt or not self._has_spoken:
            # First time or interrupt: create STT immediately, mic is already on
            if self._stt_session:
                self._stt_session.close()
            my_logger.info(f"[Session {self.session_id}] LISTENING (STT created, force={force_stt})")
            self._stt_session = self.stt_service.create_session(
                session_id=self.session_id,
                on_partial=self._on_stt_partial,
                on_final=self._on_stt_final,
                on_complete=self._on_stt_complete,
                loop=self._loop,
            )
            self._stt_final_received = False
        else:
            # After AI spoke: mic was stopped, wait for playback_finished
            if self._stt_session:
                self._stt_session.close()
                self._stt_session = None
            my_logger.info(f"[Session {self.session_id}] LISTENING (waiting for playback_finished)")

    def feed_audio(self, audio_data: bytes):
        """Feed audio to STT if in LISTENING state."""
        self.last_active = time.time()
        my_logger.info(f"[Session {self.session_id}] feed_audio: {len(audio_data)} bytes, state={self.state}")
        if self.state == SessionState.LISTENING and self._stt_session:
            self._stt_session.feed_audio(audio_data)
        else:
            my_logger.warning(f"[Session {self.session_id}] feed_audio ignored: state={self.state}, stt_session={self._stt_session is not None}")

    async def stop_audio(self):
        """Frontend detected end of speech; ask STT to flush a final result."""
        self.last_active = time.time()
        my_logger.info(f"[Session {self.session_id}] stop_audio received, state={self.state}")

        if self.state != SessionState.LISTENING or not self._stt_session:
            my_logger.warning(
                f"[Session {self.session_id}] stop_audio ignored: "
                f"state={self.state}, stt_session={self._stt_session is not None}"
            )
            return

        await self._send_msg({"type": "stop_capture"})
        self._stt_session.stop()

    async def handle_interrupt(self):
        """Handle user interruption - stop TTS, cancel agent, go back to LISTENING."""
        my_logger.info(f"[Session {self.session_id}] Interrupt received")

        # Cancel current processing task
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass

        # Stop STT and recreate for fresh recognition
        if self._stt_session:
            self._stt_session.close()
            self._stt_session = None

        # Send stop signal to frontend
        await self._send_msg({"type": "audio_chunk", "audio": "", "is_last": True})

        # Go back to listening — force STT because user is actively interrupting
        self.start_listening(force_stt=True)

    async def on_playback_finished(self):
        """Frontend confirms AI audio playback has finished.

        After a short delay (to let the AI's voice fade), re-enable the mic
        and create the STT session.
        """
        if self.state != SessionState.SPEAKING:
            return

        # Cancel fallback timeout
        if self._playback_timeout:
            self._playback_timeout.cancel()
            self._playback_timeout = None

        my_logger.info(f"[Session {self.session_id}] Playback finished, mic resumes in {self.RESUME_CAPTURE_DELAY_SEC}s")
        self._capture_timer = self._loop.call_later(
            self.RESUME_CAPTURE_DELAY_SEC, self._activate_listening
        )

    def _activate_listening(self):
        """Re-enable mic and create STT after delay (called from sync timer)."""
        self._capture_timer = None
        # If TTS is still streaming for the next response, don't interrupt it.
        # _stream_tts() will re-trigger _activate_listening() when done.
        if self._tts_streaming:
            self._deferred_activation = True
            my_logger.info(f"[Session {self.session_id}] TTS still streaming, deferring mic re-enable")
            return
        # Transition state to LISTENING
        self.state = SessionState.LISTENING
        self.last_active = time.time()
        # Close any existing STT session first
        if self._stt_session:
            self._stt_session.close()
            self._stt_session = None
        # Send start_capture to frontend (schedule async send from sync callback)
        asyncio.ensure_future(self._send_msg({"type": "start_capture"}))
        # Create STT session
        self._stt_session = self.stt_service.create_session(
            session_id=self.session_id,
            on_partial=self._on_stt_partial,
            on_final=self._on_stt_final,
            on_complete=self._on_stt_complete,
            loop=self._loop,
        )
        self._stt_final_received = False
        my_logger.info(f"[Session {self.session_id}] Now LISTENING, mic re-enabled, STT created")

    def _on_playback_timeout(self):
        """Fallback if playback_finished is never received."""
        self._playback_timeout = None
        if self.state == SessionState.SPEAKING:
            my_logger.warning(f"[Session {self.session_id}] Playback timeout, forcing resume")
            self._activate_listening()

    async def process_query(self, text: str):
        """Process recognized text through agent and TTS."""
        self.state = SessionState.PROCESSING
        self.last_active = time.time()
        my_logger.info(f"[Session {self.session_id}] Processing: {text[:50]}...")

        # Notify frontend
        await self._send_msg({"type": "agent_thinking"})

        audio_duration_sec = 0.0
        try:
            # Generate agent response
            response_text = await self.agent.generate(text, self.session_id)

            if not response_text:
                await self._send_error("agent_error", "Agent returned empty response")
                self.start_listening()
                return

            # Send text to frontend for subtitle display
            await self._send_msg({
                "type": "agent_text",
                "text": response_text,
                "is_final": True,
            })
            flow_log("08 输出", f"Markdown 文本已发送到前端 | 字符={len(response_text)}")

            # Transition to SPEAKING: stop mic and stream TTS
            self.state = SessionState.SPEAKING
            self._has_spoken = True
            await self._send_msg({"type": "stop_capture"})
            audio_duration_sec = await self._stream_tts(response_text)

        except asyncio.CancelledError:
            my_logger.info(f"[Session {self.session_id}] Processing cancelled (interrupt)")
            return
        except Exception as e:
            my_logger.error(f"[Session {self.session_id}] Processing error: {e}")
            await self._send_error("agent_error", str(e))

        # After TTS sent all chunks, wait for playback_finished from frontend.
        # Set a timeout fallback in case playback_finished is never received.
        # Base the fallback on actual PCM duration. Continuous TTS can finish
        # generating long answers far earlier than the browser finishes playback.
        if self.state == SessionState.SPEAKING:
            playback_timeout_sec = _playback_timeout_for_audio(audio_duration_sec)
            my_logger.info(
                f"[Session {self.session_id}] Playback fallback in "
                f"{playback_timeout_sec:.1f}s "
                f"(audio={audio_duration_sec:.1f}s)"
            )
            self._playback_timeout = self._loop.call_later(
                playback_timeout_sec, self._on_playback_timeout
            )

    async def _stream_tts(self, text: str) -> float:
        """Stream TTS audio chunks to frontend.

        Audio chunks are sent via direct WebSocket await (not ensure_future)
        to guarantee each chunk is delivered before the next one is sent.
        This prevents audio_stream_end from arriving before all audio chunks.
        """
        self._tts_streaming = True
        chunk_count = 0
        total_audio_bytes = 0
        flow_log("09 TTS", f"开始朗读 | 文本字符={len(text)} | 音色={self.voice_id}")
        try:
            async for audio_bytes in self.tts.synthesize_stream(text, self.voice_id):
                if self.state != SessionState.SPEAKING:
                    # Interrupted
                    break
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
                msg = {
                    "type": "audio_chunk",
                    "audio": audio_b64,
                    "is_last": False,
                }
                # 直接 await WebSocket 发送，确保音频块真正发出后再发下一个
                # 避免 ensure_future 导致 audio_stream_end 在音频块之前到达前端
                if self._websocket:
                    await self._websocket.send_text(json.dumps(msg, ensure_ascii=False))
                else:
                    await self._send_msg(msg)
                chunk_count += 1
                total_audio_bytes += len(audio_bytes)

            # Send audio_stream_end after all audio chunks have been sent
            # 此时所有音频块已通过 await 发送到 WebSocket 发送队列
            if self.state == SessionState.SPEAKING:
                end_msg = AudioStreamEndMsg().model_dump()
                if self._websocket:
                    await self._websocket.send_text(json.dumps(end_msg, ensure_ascii=False))
                else:
                    await self._send_msg(end_msg)
        finally:
            self._tts_streaming = False

        audio_duration_sec = total_audio_bytes / _PCM_22050_MONO_16BIT_BYTES_PER_SECOND
        my_logger.info(f"[Session {self.session_id}] TTS sent {chunk_count} chunks")
        flow_log(
            "09 TTS",
            f"完成 | 音频块={chunk_count} | 预计时长={audio_duration_sec:.1f}秒",
        )

        # If a playback_finished was deferred because TTS was streaming,
        # re-trigger mic activation now that TTS has finished.
        if self._deferred_activation:
            self._deferred_activation = False
            my_logger.info(f"[Session {self.session_id}] TTS done, re-triggering deferred mic activation")
            self._activate_listening()
        elif self._capture_timer:
            # Fallback: if timer still exists (shouldn't normally happen), cancel and re-trigger
            my_logger.info(f"[Session {self.session_id}] TTS done, re-triggering from pending timer")
            self._capture_timer.cancel()
            self._capture_timer = None
            self._activate_listening()

        return audio_duration_sec

    async def _on_stt_partial(self, text: str, is_final: bool = False):
        """Callback for partial STT results."""
        await self._send_msg({
            "type": "stt_partial",
            "text": text,
            "is_final": is_final,
        })

    async def _on_stt_final(self, text: str):
        """Callback for final STT result - triggers agent processing."""
        if self._is_closed:
            return

        # 防重入：如果正在处理中，忽略新的请求
        if self.state == SessionState.PROCESSING:
            my_logger.warning(f"[Session {self.session_id}] Ignoring duplicate STT final: {text[:50]}...")
            return
        self._stt_final_received = True

        await self._send_msg({
            "type": "stt_final",
            "text": text,
        })
        await self._send_msg({"type": "stop_capture"})
        # Close current STT session before processing
        if self._stt_session:
            self._stt_session.close()
            self._stt_session = None
        # Process in background task so we can handle interrupts
        self._current_task = asyncio.create_task(self.process_query(text))

    async def _on_stt_complete(self):
        """Handle ASR completion with no final text."""
        if self._is_closed or self._stt_final_received or self.state != SessionState.LISTENING:
            return

        my_logger.warning(f"[Session {self.session_id}] STT completed without final text")
        self._stt_session = None
        await self._send_msg({
            "type": "agent_text",
            "text": "我刚才没有识别到有效语音，请再说一遍。",
            "is_final": False,
        })
        # Let the frontend finish tearing down its previous AudioContext before
        # asking it to acquire the microphone again.
        await asyncio.sleep(0.2)
        if self._is_closed or self.state != SessionState.LISTENING:
            return
        self.start_listening(force_stt=True)
        await self._send_msg({"type": "start_capture"})

    async def _send_error(self, code: str, message: str):
        await self._send_msg({
            "type": "error",
            "code": code,
            "message": message,
        })

    def cleanup(self):
        """Clean up all resources."""
        self._is_closed = True
        if self._capture_timer:
            self._capture_timer.cancel()
            self._capture_timer = None
        if self._playback_timeout:
            self._playback_timeout.cancel()
            self._playback_timeout = None
        if self._stt_session:
            self._stt_session.close()
            self._stt_session = None
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
        clear_tool_runtime_context()


class VoiceSessionManager:
    """Manages all active voice sessions."""

    def __init__(self):
        self._sessions: Dict[str, VoiceSession] = {}
        self._stt_service = STTService()

    def create_session(
        self,
        session_id: str,
        user_id: str,
        voice_id: str,
        send_msg: Callable,
        loop: asyncio.AbstractEventLoop,
        conversation_history: Optional[List[dict]] = None,
    ) -> VoiceSession:
        """Create a new voice session."""
        if session_id in self._sessions:
            my_logger.warning(f"[SessionManager] Session {session_id} already exists, cleaning up old one")
            self._sessions[session_id].cleanup()

        session = VoiceSession(
            session_id=session_id,
            user_id=user_id,
            voice_id=voice_id,
            stt_service=self._stt_service,
            send_msg=send_msg,
            loop=loop,
            conversation_history=conversation_history,
        )
        self._sessions[session_id] = session
        my_logger.info(f"[SessionManager] Created session {session_id} for user {user_id}")
        return session

    def get_session(self, session_id: str) -> Optional[VoiceSession]:
        return self._sessions.get(session_id)

    def remove_session(self, session_id: str):
        session = self._sessions.pop(session_id, None)
        if session:
            session.cleanup()
            self._stt_service.remove_session(session_id)
            my_logger.info(f"[SessionManager] Removed session {session_id}")

    async def cleanup_expired(self):
        """Remove idle/expired sessions. Call periodically."""
        expired = []
        for sid, session in self._sessions.items():
            if not session.is_alive or session.is_idle_timeout:
                expired.append(sid)
        for sid in expired:
            self.remove_session(sid)
            my_logger.info(f"[SessionManager] Expired session {sid}")

    def shutdown(self):
        """Clean up all sessions."""
        for session in self._sessions.values():
            session.cleanup()
        self._stt_service.close_all()
        self._sessions.clear()
