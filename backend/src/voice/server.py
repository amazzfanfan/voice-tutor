"""WebSocket endpoint for voice conversation."""

import asyncio
import base64
import json
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from voice.protocol import (
    parse_frontend_msg,
    SessionStartedMsg,
    SessionEndedMsg,
    ErrorMsg,
)
from voice.session import VoiceSessionManager
from voice.config import AVAILABLE_VOICES
from algo.config import my_logger

voice_router = APIRouter()
session_manager = VoiceSessionManager()


@voice_router.websocket("/voice/chat")
async def voice_chat_ws(websocket: WebSocket):
    """WebSocket endpoint for voice conversation.

    Protocol:
    - Frontend sends JSON messages (see protocol.py)
    - Audio data is base64 encoded in the 'audio' field
    - Backend sends JSON messages back
    """
    await websocket.accept()
    session_id: Optional[str] = None
    loop = asyncio.get_event_loop()

    my_logger.info("[VoiceWS] New WebSocket connection")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await _send(websocket, ErrorMsg(
                    code="invalid_json",
                    message="Invalid JSON format"
                ).model_dump())
                continue

            try:
                msg = parse_frontend_msg(data)
            except ValueError as e:
                await _send(websocket, ErrorMsg(
                    code="unknown_message",
                    message=str(e)
                ).model_dump())
                continue

            # --- Route messages ---

            if msg.type == "start_session":
                session_id = msg.session_id
                session = session_manager.create_session(
                    session_id=session_id,
                    user_id=msg.user_id,
                    voice_id=msg.voice_id,
                    send_msg=lambda m: asyncio.ensure_future(_send(websocket, m)),
                    loop=loop,
                    conversation_history=msg.config.get("conversation_history", []),
                )
                session._websocket = websocket  # 用于音频块的阻塞发送
                session.start_listening()
                await _send(websocket, SessionStartedMsg(
                    session_id=session_id
                ).model_dump())

            elif msg.type == "audio_data":
                if not session_id:
                    await _send(websocket, ErrorMsg(
                        code="no_session",
                        message="No active session. Send start_session first."
                    ).model_dump())
                    continue
                session = session_manager.get_session(session_id)
                if session:
                    audio_bytes = base64.b64decode(msg.audio)
                    my_logger.info(f"[VoiceWS] Received audio data: {len(audio_bytes)} bytes")
                    session.feed_audio(audio_bytes)

            elif msg.type == "stop_audio":
                if session_id:
                    session = session_manager.get_session(session_id)
                    if session:
                        await session.stop_audio()

            elif msg.type == "interrupt":
                if session_id:
                    session = session_manager.get_session(session_id)
                    if session:
                        await session.handle_interrupt()

            elif msg.type == "playback_finished":
                if session_id:
                    session = session_manager.get_session(session_id)
                    if session:
                        await session.on_playback_finished()

            elif msg.type == "end_session":
                if session_id:
                    session_manager.remove_session(session_id)
                    await _send(websocket, SessionEndedMsg(
                        reason="user_ended"
                    ).model_dump())
                    session_id = None

            elif msg.type == "switch_voice":
                if session_id:
                    session = session_manager.get_session(session_id)
                    if session:
                        if msg.voice_id in AVAILABLE_VOICES:
                            session.voice_id = msg.voice_id
                        else:
                            await _send(websocket, ErrorMsg(
                                code="invalid_voice",
                                message=f"Unknown voice: {msg.voice_id}"
                            ).model_dump())

            elif msg.type == "update_config":
                # Future: allow model switching, etc.
                await _send(websocket, {"type": "config_updated", "config": msg.config})

    except WebSocketDisconnect:
        my_logger.info(f"[VoiceWS] Client disconnected (session={session_id})")
    except Exception as e:
        my_logger.error(f"[VoiceWS] Unexpected error: {e}")
    finally:
        if session_id:
            session_manager.remove_session(session_id)
        my_logger.info(f"[VoiceWS] Connection closed (session={session_id})")


async def _send(websocket: WebSocket, data: dict):
    """Send JSON message to client, handling disconnection."""
    try:
        await websocket.send_text(json.dumps(data, ensure_ascii=False))
    except Exception:
        pass


async def cleanup_expired_sessions():
    """Background task to clean up expired sessions."""
    while True:
        await asyncio.sleep(60)
        await session_manager.cleanup_expired()
