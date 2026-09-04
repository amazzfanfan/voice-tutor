"""Tests for reliable segmented voice synthesis."""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_tts_removes_display_markdown_before_synthesis():
    with patch("voice.tts_service.dashscope"):
        from voice.tts_service import TTSService

        service = TTSService()

    assert service._prepare_spoken_text(
        "### 坡度控制\n\n**要求如下**。\n"
        "1. **全线坡度**：不大于45‰。\n"
        "- 参考[操作手册](https://example.com)。"
    ) == (
        "坡度控制\n"
        "要求如下。\n"
        "1、全线坡度：不大于千分之四十五。\n"
        "参考操作手册。"
    )


def test_tts_reads_permille_without_changing_display_text():
    with patch("voice.tts_service.dashscope"):
        from voice.tts_service import TTSService

        service = TTSService()

    display_text = "线路坡度不大于45‰，曲线段不大于3‰，偏差为0.5‰。"

    assert service._prepare_spoken_text(display_text) == (
        "线路坡度不大于千分之四十五，曲线段不大于千分之三，"
        "偏差为千分之零点五。"
    )
    assert display_text == "线路坡度不大于45‰，曲线段不大于3‰，偏差为0.5‰。"


def test_tts_expands_measure_units_and_visual_symbols_for_speech_only():
    with patch("voice.tts_service.dashscope"):
        from voice.tts_service import TTSService

        service = TTSService()

    display_text = (
        "平面曲线长度不小于 **30 m**；半径——准轨不小于 **120 m**，"
        "窄轨（600 mm）不小于 **30 m**；轨距加宽 **10 mm**；"
        "坡度≤3‰；道床边坡为1:1.75；检查GB 16423-2020。"
    )

    assert service._prepare_spoken_text(display_text) == (
        "平面曲线长度不小于30米；半径，准轨不小于120米，"
        "窄轨（600毫米）不小于30米；轨距加宽10毫米；"
        "坡度不大于千分之三；道床边坡为1比1.75；检查GB 16423杠2020。"
    )
    assert "**30 m**" in display_text


def test_tts_reads_measure_ranges_and_cleans_line_break_punctuation():
    with patch("voice.tts_service.dashscope"):
        from voice.tts_service import TTSService

        service = TTSService()

    spoken = service._prepare_spoken_text(
        "- 作业距离为10-15 m；\n- 电压不低于3 kV；\n- 温度为-5°。"
    )
    assert spoken == "作业距离为10至15米；\n电压不低于3千伏；\n温度为负5度。"
    assert service._split_spoken_text(spoken) == [
        "作业距离为10至15米。电压不低于3千伏。温度为负5度。"
    ]


def test_playback_timeout_scales_with_generated_audio_duration():
    from voice.session import _playback_timeout_for_audio

    assert _playback_timeout_for_audio(30.0) == 60.0
    assert _playback_timeout_for_audio(89.0) == 104.0


def test_tts_segments_only_at_sentence_or_clause_boundaries():
    with patch("voice.tts_service.dashscope"):
        from voice.tts_service import TTSService

        service = TTSService()

    text = (
        "第一项要检查线路坡度、曲线半径和连接长度，确认全部符合规定。"
        "第二项要检查轨距加宽和过渡段，发现异常立即停止作业。"
        "第三项要检查护轨、防爬设施以及安全距离，不能遗漏。"
        "第四项要把现场发现的问题记录清楚，并跟踪整改结果。"
    )
    segments = service._split_spoken_text(text)

    assert len(segments) >= 2
    assert "".join(segments) == text
    assert all(len(segment) <= 120 for segment in segments)
    assert all(segment[-1] in "。！？!?；;，、,:：" for segment in segments[:-1])


@pytest.mark.asyncio
async def test_tts_uses_independent_segments_and_retries_only_failed_segment():
    instances = []

    class FakeSynthesizer:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]
            self.language_hints = kwargs.get("language_hints")
            self.streaming_calls = []
            self.completed = False
            self.cancelled = False
            instances.append(self)

        def streaming_call(self, text):
            self.streaming_calls.append(text)
            if len(instances) == 1:
                self.callback.on_error("temporary failure")
            else:
                self.callback.on_data(text.encode("utf-8"))

        def streaming_complete(self):
            self.completed = True
            self.callback.on_complete()

        def streaming_cancel(self):
            self.cancelled = True

        def get_last_request_id(self):
            return f"request-{len(instances)}"

    with patch("voice.tts_service.dashscope"), patch(
        "voice.tts_service.SpeechSynthesizer", FakeSynthesizer
    ):
        from voice.tts_service import TTSService

        service = TTSService()

        with patch("voice.tts_service._TTS_SEGMENT_TARGET_CHARS", 8), patch(
            "voice.tts_service._TTS_SEGMENT_MAX_CHARS", 12
        ):
            chunks = [
                chunk
                async for chunk in service.synthesize_stream(
                    "第一句话需要确认。第二句话需要复核。第三句话完成。"
                )
            ]

    assert len(instances) == 4
    assert all(instance.language_hints == ["zh"] for instance in instances)
    assert instances[0].streaming_calls == instances[1].streaming_calls
    assert instances[0].completed is True
    assert instances[1].completed is True
    assert instances[2].streaming_calls != instances[1].streaming_calls
    assert instances[3].streaming_calls != instances[2].streaming_calls
    successful_text = "".join(
        instance.streaming_calls[0] for instance in instances[1:]
    )
    assert b"".join(chunks) == successful_text.encode("utf-8")
