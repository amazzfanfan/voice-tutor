"""DashScope cosyvoice-v3-flash TTS service wrapper."""

import asyncio
import json
import re
import threading
from typing import AsyncIterator, Dict, List, Tuple
import dashscope
from dashscope.audio.tts_v2 import AudioFormat, ResultCallback, SpeechSynthesizer
from voice.config import DASHSCOPE_API_KEY, TTS_MODEL, DEFAULT_VOICE_ID, AVAILABLE_VOICES
from voice.debug_log import compact_log_text, flow_log
from algo.config import my_logger


_AUDIO_STREAM_CHUNK_BYTES = 64 * 1024
_TTS_SEGMENT_TARGET_CHARS = 80
_TTS_SEGMENT_MAX_CHARS = 120
_TTS_SEGMENT_MAX_ATTEMPTS = 2
_STREAM_END = object()
_CHINESE_DIGITS = "零一二三四五六七八九"

# Keep the answer shown in the UI unchanged and normalize only the text sent to
# TTS.  Longer abbreviations must appear before their prefixes (for example,
# ``mm`` before ``m``) so a millimetre can never be partially matched as a metre.
_SPOKEN_MEASURE_UNITS = {
    "km³": "立方千米",
    "cm³": "立方厘米",
    "mm³": "立方毫米",
    "m³": "立方米",
    "km²": "平方千米",
    "cm²": "平方厘米",
    "mm²": "平方毫米",
    "m²": "平方米",
    "㎡": "平方米",
    "mm": "毫米",
    "cm": "厘米",
    "km": "千米",
    "μm": "微米",
    "nm": "纳米",
    "kg": "千克",
    "mg": "毫克",
    "kPa": "千帕",
    "MPa": "兆帕",
    "kV": "千伏",
    "mA": "毫安",
    "m": "米",
    "g": "克",
    "V": "伏",
    "A": "安",
}
_MEASURE_UNIT_PATTERN = "|".join(
    re.escape(unit)
    for unit in sorted(_SPOKEN_MEASURE_UNITS, key=len, reverse=True)
)
_MEASURE_NUMBER_PATTERN = r"\d(?:[\d, ]*\d)?(?:\.\d+)?"


def _integer_to_spoken_chinese(value: int) -> str:
    """Convert common engineering integers to natural Chinese for TTS."""
    if value == 0:
        return "零"
    if value < 0 or value > 9999:
        return str(value)

    parts = []
    zero_pending = False
    for divisor, unit in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
        digit = value // divisor
        value %= divisor
        if digit:
            if zero_pending and parts:
                parts.append("零")
            if not (divisor == 10 and digit == 1 and not parts):
                parts.append(_CHINESE_DIGITS[digit])
            parts.append(unit)
            zero_pending = False
        elif parts and value:
            zero_pending = True
    return "".join(parts)


def _number_to_spoken_chinese(raw: str) -> str:
    integer_part, dot, decimal_part = raw.partition(".")
    spoken = _integer_to_spoken_chinese(int(integer_part))
    if dot:
        spoken += "点" + "".join(_CHINESE_DIGITS[int(char)] for char in decimal_part)
    return spoken


def _speak_permille_values(text: str) -> str:
    """Read display notation such as 45‰ without changing the displayed reply."""
    spoken = re.sub(
        r"(\d+(?:\.\d+)?)\s*‰",
        lambda match: "千分之" + _number_to_spoken_chinese(match.group(1)),
        text,
    )
    return re.sub(
        r"([零〇一二三四五六七八九十百千万两点]+)\s*‰",
        r"千分之\1",
        spoken,
    )


def _speak_measurement_units(text: str) -> str:
    """Expand engineering unit abbreviations in the TTS-only text."""

    def replace_measure(match: re.Match) -> str:
        # A space inside a number is commonly a thousands separator in source
        # documents (for example, ``3 000 m``).  Removing it also prevents TTS
        # from reading the value as two unrelated numbers.
        number = re.sub(r"[ ,]", "", match.group("number"))
        unit = _SPOKEN_MEASURE_UNITS[match.group("unit")]
        return f"{number}{unit}"

    # A hyphen or tilde between two measured values means "to", not "dash".
    range_pattern = re.compile(
        rf"(?P<start>{_MEASURE_NUMBER_PATTERN})\s*"
        rf"[-~～]\s*(?P<end>{_MEASURE_NUMBER_PATTERN})\s*"
        rf"(?P<unit>{_MEASURE_UNIT_PATTERN})(?![A-Za-z])"
    )

    def replace_range(match: re.Match) -> str:
        start = re.sub(r"[ ,]", "", match.group("start"))
        end = re.sub(r"[ ,]", "", match.group("end"))
        unit = _SPOKEN_MEASURE_UNITS[match.group("unit")]
        return f"{start}至{end}{unit}"

    spoken = range_pattern.sub(replace_range, text)
    measure_pattern = re.compile(
        rf"(?P<number>{_MEASURE_NUMBER_PATTERN})\s*"
        rf"(?P<unit>{_MEASURE_UNIT_PATTERN})(?![A-Za-z])"
    )
    spoken = measure_pattern.sub(replace_measure, spoken)
    spoken = re.sub(r"(\d+(?:\.\d+)?)\s*°", r"\1度", spoken)
    # Markdown emphasis often leaves a visual space before a measured value.
    # It is unnecessary in Chinese speech and can weaken unit association.
    return re.sub(r"(?<=[\u4e00-\u9fff：:；;，,（(])\s+(?=\d)", "", spoken)


def _speak_symbols_naturally(text: str) -> str:
    """Turn visual comparison and dash symbols into unambiguous speech."""
    spoken = text.replace("≤", "不大于").replace("≥", "不小于")
    spoken = spoken.replace("≦", "不大于").replace("≧", "不小于")
    spoken = re.sub(r"(?<=\d)\s*[:：]\s*(?=\d)", "比", spoken)

    # Em dashes are prose separators.  Leaving them in the TTS input can make
    # the model say "dash" or produce an unstable non-speech sound.
    spoken = re.sub(r"\s*[—–－]{1,2}\s*", "，", spoken)

    # Preserve the meaning of negative numbers and identifiers while ensuring
    # that a raw ASCII hyphen never reaches the synthesizer.
    spoken = re.sub(r"(?<![A-Za-z0-9])-(?=\d)", "负", spoken)
    spoken = re.sub(r"(?<=[A-Za-z0-9])-(?=[A-Za-z0-9])", "杠", spoken)
    spoken = spoken.replace("-", "，")
    return spoken


class _StreamingTTSCallback(ResultCallback):
    """Bridge DashScope's callback thread into an asyncio audio queue."""

    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
        self.loop = loop
        self.queue = queue
        self.error = None
        self.completed_texts: List[str] = []
        self._finished = False
        self._lock = threading.Lock()

    def _enqueue(self, item) -> None:
        try:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, item)
        except RuntimeError:
            # The request may have been interrupted after its event loop closed.
            pass

    def on_data(self, data: bytes) -> None:
        if data:
            self._enqueue(bytes(data))

    def on_complete(self) -> None:
        self.finish()

    def on_event(self, message: str) -> None:
        """Keep sentence acknowledgements so a segment can be verified."""
        try:
            payload = json.loads(message)
            output = payload.get("payload", {}).get("output", {})
            if output.get("type") == "sentence-end":
                original_text = str(output.get("original_text") or "").strip()
                if original_text:
                    self.completed_texts.append(original_text)
        except (TypeError, ValueError, AttributeError):
            # Audio and task completion remain the compatibility fallback for
            # SDK/model versions that emit a different event shape.
            return

    def on_error(self, message) -> None:
        self.finish(RuntimeError(f"DashScope TTS streaming error: {message}"))

    def finish(self, error=None) -> None:
        with self._lock:
            if self._finished:
                return
            self._finished = True
            self.error = error
        self._enqueue(_STREAM_END)


class TTSService:
    """DashScope cosyvoice-v3-flash TTS wrapper."""

    def __init__(self):
        dashscope.api_key = DASHSCOPE_API_KEY
        dashscope.base_websocket_api_url = 'wss://dashscope.aliyuncs.com/api-ws/v1/inference'

    def get_available_voices(self) -> Dict[str, str]:
        """Return available voice_id -> display name mapping."""
        return dict(AVAILABLE_VOICES)

    @staticmethod
    def _prepare_spoken_text(text: str) -> str:
        """Build natural plain text for TTS without changing the UI answer."""
        spoken = re.sub(r"(?m)^\s*#{1,6}\s*", "", text or "")
        spoken = re.sub(r"```[\s\S]*?```", "", spoken)
        spoken = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", spoken)
        spoken = re.sub(r"`([^`]+)`", r"\1", spoken)
        spoken = re.sub(r"\*\*([^*]+)\*\*", r"\1", spoken)
        spoken = re.sub(r"__([^_]+)__", r"\1", spoken)
        spoken = re.sub(r"~~([^~]+)~~", r"\1", spoken)
        spoken = re.sub(r"(?m)^\s*>\s*", "", spoken)
        spoken = re.sub(r"(?m)^\s*[-*+]\s+", "", spoken)
        spoken = re.sub(r"(?m)^\s*(\d+)[\.)]\s+", r"\1、", spoken)
        spoken = re.sub(r"(?m)^\s*[-*_]{3,}\s*$", "", spoken)
        spoken = _speak_permille_values(spoken)
        spoken = _speak_measurement_units(spoken)
        spoken = _speak_symbols_naturally(spoken)
        spoken = re.sub(r"\n\s*\n+", "\n", spoken)
        return spoken.strip()

    @staticmethod
    def _split_spoken_text(text: str) -> List[str]:
        """Group complete sentences into short, independently retryable segments."""
        normalized = re.sub(r"\n+", "。", text.strip())
        normalized = re.sub(r"[，、,:：；;]+。", "。", normalized)
        normalized = re.sub(r"。{2,}", "。", normalized)
        sentence_units = [
            unit.strip()
            for unit in re.findall(r".+?[。！？!?；;]+|.+$", normalized)
            if unit.strip()
        ]

        bounded_units: List[str] = []
        for unit in sentence_units:
            if len(unit) <= _TTS_SEGMENT_MAX_CHARS:
                bounded_units.append(unit)
                continue

            clauses = [
                clause.strip()
                for clause in re.findall(r".+?[，、,:：]+|.+$", unit)
                if clause.strip()
            ]
            current_clause = ""
            for clause in clauses:
                if current_clause and len(current_clause) + len(clause) > _TTS_SEGMENT_MAX_CHARS:
                    bounded_units.append(current_clause)
                    current_clause = ""
                while len(clause) > _TTS_SEGMENT_MAX_CHARS:
                    if current_clause:
                        bounded_units.append(current_clause)
                        current_clause = ""
                    bounded_units.append(clause[:_TTS_SEGMENT_MAX_CHARS])
                    clause = clause[_TTS_SEGMENT_MAX_CHARS:]
                current_clause += clause
            if current_clause:
                bounded_units.append(current_clause)

        segments: List[str] = []
        current = ""
        for unit in bounded_units:
            if current and (
                len(current) >= _TTS_SEGMENT_TARGET_CHARS
                or len(current) + len(unit) > _TTS_SEGMENT_MAX_CHARS
            ):
                segments.append(current)
                current = ""
            current += unit
        if current:
            segments.append(current)
        return segments

    async def synthesize_stream(
        self, text: str, voice_id: str = None
    ) -> AsyncIterator[bytes]:
        """Synthesize bounded sentence groups with per-segment retry and prefetch."""
        voice = voice_id or DEFAULT_VOICE_ID
        if voice not in AVAILABLE_VOICES:
            my_logger.warning(f"[TTS] Unknown voice {voice}, falling back to default")
            voice = DEFAULT_VOICE_ID

        spoken_text = self._prepare_spoken_text(text)
        if not spoken_text:
            return

        segments = self._split_spoken_text(spoken_text)
        my_logger.info(
            f"[TTS] Segmented synthesis ({len(spoken_text)} chars, "
            f"{len(segments)} segments) with voice={voice}"
        )
        flow_log(
            "09 TTS",
            f"分段计划 | 段数={len(segments)} | 每段最多={_TTS_SEGMENT_MAX_CHARS}字",
        )

        # Each segment is a separate task, so a provider-side early completion
        # cannot silently discard the rest of the answer. Start the next task
        # before yielding the current audio to overlap synthesis and playback.
        segment_task = asyncio.create_task(
            self._synthesize_segment_with_retry(segments[0], voice, 1, len(segments))
        )
        try:
            for index, segment in enumerate(segments, start=1):
                audio = await segment_task
                if index < len(segments):
                    segment_task = asyncio.create_task(
                        self._synthesize_segment_with_retry(
                            segments[index], voice, index + 1, len(segments)
                        )
                    )

                for offset in range(0, len(audio), _AUDIO_STREAM_CHUNK_BYTES):
                    yield audio[offset : offset + _AUDIO_STREAM_CHUNK_BYTES]
        finally:
            if not segment_task.done():
                segment_task.cancel()

    async def _synthesize_segment_with_retry(
        self,
        text: str,
        voice: str,
        index: int,
        total: int,
    ) -> bytes:
        """Synthesize one bounded segment and retry it once on failure."""
        last_error: Exception | None = None
        for attempt in range(1, _TTS_SEGMENT_MAX_ATTEMPTS + 1):
            flow_log(
                "09 TTS",
                f"分段 {index}/{total} | 尝试={attempt} | 字符={len(text)} "
                f"| 内容：{compact_log_text(text, 100)}",
            )
            try:
                audio, request_id = await self._collect_streaming_segment(text, voice)
                flow_log(
                    "09 TTS",
                    f"分段 {index}/{total} 完成 | 音频字节={len(audio)} "
                    f"| request_id={request_id or '-'}",
                )
                return audio
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                my_logger.warning(
                    f"[TTS] Segment {index}/{total} attempt {attempt} failed: {exc}"
                )
                flow_log(
                    "09 TTS",
                    f"分段 {index}/{total} 失败 | 尝试={attempt} "
                    f"| {compact_log_text(str(exc), 120)}",
                )

        raise RuntimeError(
            f"TTS segment {index}/{total} failed after "
            f"{_TTS_SEGMENT_MAX_ATTEMPTS} attempts: {last_error}"
        )

    async def _collect_streaming_segment(
        self, text: str, voice: str
    ) -> Tuple[bytes, str]:
        """Collect and verify one independent streaming synthesis task."""
        loop = asyncio.get_running_loop()
        audio_queue = asyncio.Queue()
        callback = _StreamingTTSCallback(loop, audio_queue)
        synthesizer = SpeechSynthesizer(
            model=TTS_MODEL,
            voice=voice,
            format=AudioFormat.PCM_22050HZ_MONO_16BIT,
            language_hints=["zh"],
            callback=callback,
        )
        synthesis_task = asyncio.create_task(
            asyncio.to_thread(
                self._run_continuous_synthesis,
                synthesizer,
                text,
                callback,
            )
        )
        audio = bytearray()
        try:
            while True:
                item = await audio_queue.get()
                if item is _STREAM_END:
                    break
                audio.extend(item)
            await synthesis_task
        finally:
            if not synthesis_task.done():
                try:
                    synthesizer.streaming_cancel()
                except Exception:
                    pass
                synthesis_task.cancel()

        if callback.error:
            raise callback.error
        if not audio:
            raise RuntimeError("DashScope TTS returned empty audio")

        if callback.completed_texts:
            expected = re.sub(r"\s+", "", text)
            confirmed = re.sub(r"\s+", "", "".join(callback.completed_texts))
            if expected != confirmed:
                raise RuntimeError(
                    f"DashScope TTS sentence confirmation mismatch: "
                    f"expected={len(expected)}, confirmed={len(confirmed)}"
                )

        request_id_getter = getattr(synthesizer, "get_last_request_id", None)
        request_id = str(request_id_getter() or "") if request_id_getter else ""
        return bytes(audio), request_id

    @staticmethod
    def _run_continuous_synthesis(
        synthesizer: SpeechSynthesizer,
        text: str,
        callback: _StreamingTTSCallback,
    ) -> None:
        """Run one DashScope duplex TTS session in a worker thread."""
        try:
            synthesizer.streaming_call(text)
            synthesizer.streaming_complete()
        except Exception as exc:
            callback.finish(exc)
        else:
            # SDK normally invokes on_complete; this also guards SDK edge cases.
            callback.finish()

    async def _synthesize_one(self, text: str, voice_id: str) -> bytes:
        """Synthesize a single sentence. Runs in executor to avoid blocking."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_synthesize, text, voice_id)

    def _sync_synthesize(self, text: str, voice_id: str) -> bytes:
        """Synchronous TTS call (runs in thread pool)."""
        try:
            my_logger.info(f"[TTS] Synthesizing: {text[:30]}...")
            synthesizer = SpeechSynthesizer(
                model=TTS_MODEL,
                voice=voice_id,
                format=AudioFormat.PCM_22050HZ_MONO_16BIT,
                language_hints=["zh"],
            )
            audio = synthesizer.call(text)
            if audio:
                my_logger.info(f"[TTS] Got {len(audio)} bytes for: {text[:30]}...")
                return audio
            my_logger.warning(f"[TTS] Empty audio for: {text[:30]}...")
            return b""
        except Exception as e:
            my_logger.error(f"[TTS] Synthesis failed: {e}")
            return b""

    async def synthesize_full(self, text: str, voice_id: str = None) -> bytes:
        """Synthesize full text into a single audio blob (non-streaming fallback)."""
        voice = voice_id or DEFAULT_VOICE_ID
        return await self._synthesize_one(text, voice)
