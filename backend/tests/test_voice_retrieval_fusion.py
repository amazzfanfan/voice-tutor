"""Tests for the low-latency Voice Wiki/RAG fusion path."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from voice.retrieval_fusion import (
    FusedContext,
    RetrievalBundle,
    SourceStatus,
    fuse_retrieval_bundle,
    rag_material_from_results,
    wiki_material_from_response,
)


def test_rag_normalization_keeps_rank_order_and_removes_duplicates():
    material = rag_material_from_results(
        [
            {"content": "制动距离会随载荷增加而变长。", "filename": "规程A"},
            {"content": " 制动距离会随载荷增加而变长。 ", "filename": "重复"},
            {"content": "检查时还要确认制动装置状态。", "filename": "手册B"},
        ],
        elapsed_ms=12,
        max_chunks=5,
        chunk_max_chars=900,
        total_max_chars=3000,
    )

    assert material.status is SourceStatus.SUCCESS
    assert material.raw_count == 3
    assert [chunk.rank for chunk in material.chunks] == [1, 3]
    assert material.duplicate_count == 1


def test_fusion_uses_source_roles_and_preserves_constraints_under_budget():
    repeated = "额定载荷是设备允许安全运行的明确边界，超过后不得继续运行。"
    wiki = wiki_material_from_response(
        {
            "local_context": f"# 额定载荷\n\n{repeated}\n\n先理解载荷，再理解超载风险。",
            "matched_concepts": ["额定载荷"],
        },
        elapsed_ms=10,
        max_chars=2500,
    )
    rag = rag_material_from_results(
        [{"content": repeated, "filename": "设备安全规程"}],
        elapsed_ms=15,
        max_chunks=5,
        chunk_max_chars=900,
        total_max_chars=3000,
    )

    fused = fuse_retrieval_bundle(
        RetrievalBundle(mode="rag_wiki", wiki=wiki, rag=rag, elapsed_ms=16),
        max_chars=600,
    )

    assert fused.source_label == "Wiki+RAG"
    assert fused.duplicate_count == 1
    assert fused.text.count(repeated) == 1
    assert "## Wiki概念上下文" in fused.text
    assert "## RAG原文依据" in fused.text
    assert "最终回答不得向用户展示" in fused.text
    assert len(fused.text) <= 600


@pytest.mark.asyncio
async def test_rag_wiki_sources_start_concurrently():
    with patch("voice.voice_agent.DashScope"), patch("voice.voice_agent.Agent"):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    started = set()
    both_started = asyncio.Event()

    async def fake_wiki(_query):
        started.add("wiki")
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.1)
        return {"local_context": "概念框架"}

    async def fake_rag(_query):
        started.add("rag")
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.1)
        return [{"content": "原文依据"}]

    voice_agent._call_wiki_retrieve = fake_wiki
    voice_agent._call_original_rag = fake_rag

    with patch("voice.voice_agent.VOICE_KNOWLEDGE_SOURCE", "rag_wiki"):
        fused = await voice_agent._call_knowledge_source("测试问题")

    assert started == {"wiki", "rag"}
    assert fused.source_label == "Wiki+RAG"
    assert fused.wiki_status is SourceStatus.SUCCESS
    assert fused.rag_status is SourceStatus.SUCCESS


@pytest.mark.asyncio
async def test_rag_timeout_keeps_fast_wiki_result():
    with patch("voice.voice_agent.DashScope"), patch("voice.voice_agent.Agent"), patch(
        "voice.voice_agent.VOICE_KNOWLEDGE_SOURCE", "rag_wiki"
    ), patch("voice.voice_agent.VOICE_RAG_TIMEOUT_SEC", 0.01), patch(
        "voice.voice_agent.VOICE_RETRIEVAL_TOTAL_TIMEOUT_SEC", 0.08
    ):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

        voice_agent._call_wiki_retrieve = AsyncMock(
            return_value={"local_context": "Wiki 可以正常提供概念框架。"}
        )

        async def slow_rag(_query):
            await asyncio.sleep(0.2)
            return [{"content": "不应等到的结果"}]

        voice_agent._call_original_rag = slow_rag
        fused = await voice_agent._call_knowledge_source("测试问题")

    assert fused.wiki_status is SourceStatus.SUCCESS
    assert fused.rag_status is SourceStatus.TIMEOUT
    assert fused.source_label == "Wiki"
    assert "Wiki 可以正常提供概念框架" in fused.text
    assert "不应等到的结果" not in fused.text


@pytest.mark.asyncio
async def test_generation_path_does_not_call_relevance_model():
    with patch("voice.voice_agent.DashScope"), patch("voice.voice_agent.Agent"), patch(
        "voice.voice_agent.VOICE_TUTOR_SKILL_NAME", "voice-tutor-explain-only"
    ):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    session_id = "fusion-no-rerank-session"
    voice_agent._get_history_context = AsyncMock(
        return_value="对话历史：\n用户: 我是安全员，用于现场讲解。"
    )
    voice_agent._classify_user_turn = AsyncMock(return_value="knowledge_query")
    voice_agent._call_knowledge_source = AsyncMock(
        return_value=FusedContext(
            text="## RAG原文依据\n- E1：额定载荷不得超过规定值。",
            source_label="RAG",
            mode="rag_wiki",
            rag_status=SourceStatus.SUCCESS,
            rag_raw_count=1,
            rag_kept_count=1,
        )
    )
    voice_agent._judge_relevance = AsyncMock()
    voice_agent._generate_answer = AsyncMock(return_value=("先确认额定载荷。", "RAG"))

    answer = await voice_agent.generate("额定载荷怎么讲？", session_id)

    assert answer == "先确认额定载荷。"
    voice_agent._judge_relevance.assert_not_awaited()


@pytest.mark.asyncio
async def test_both_source_timeouts_fall_back_to_web_search():
    with patch("voice.voice_agent.DashScope"), patch("voice.voice_agent.Agent"), patch(
        "voice.voice_agent.VOICE_TUTOR_SKILL_NAME", "voice-tutor-explain-only"
    ):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    voice_agent._get_history_context = AsyncMock(
        return_value="对话历史：\n用户: 我是安全员，用于现场讲解。"
    )
    voice_agent._classify_user_turn = AsyncMock(return_value="knowledge_query")
    voice_agent._call_knowledge_source = AsyncMock(
        return_value=FusedContext(
            text="",
            source_label="LLM",
            mode="rag_wiki",
            wiki_status=SourceStatus.TIMEOUT,
            rag_status=SourceStatus.TIMEOUT,
        )
    )
    voice_agent._call_web_search = AsyncMock(return_value="联网检索到的可靠资料。")
    voice_agent._generate_answer = AsyncMock(
        return_value=("先根据联网资料说明关键要求。", "WebSearch")
    )
    voice_agent._generate_pure_llm = AsyncMock()

    answer = await voice_agent.generate("额定载荷怎么讲？", "web-fallback-session")

    assert answer == "先根据联网资料说明关键要求。"
    voice_agent._call_web_search.assert_awaited_once_with("额定载荷怎么讲？")
    generation_args = voice_agent._generate_answer.await_args.args
    assert generation_args[1] == ""
    assert generation_args[2] == "联网检索到的可靠资料。"
    voice_agent._generate_pure_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_any_source_failure_without_local_material_falls_back_to_web_search():
    with patch("voice.voice_agent.DashScope"), patch("voice.voice_agent.Agent"), patch(
        "voice.voice_agent.VOICE_TUTOR_SKILL_NAME", "voice-tutor-explain-only"
    ):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    voice_agent._get_history_context = AsyncMock(
        return_value="对话历史：\n用户: 我是安全员，用于现场讲解。"
    )
    voice_agent._classify_user_turn = AsyncMock(return_value="knowledge_query")
    voice_agent._call_knowledge_source = AsyncMock(
        return_value=FusedContext(
            text="",
            source_label="LLM",
            mode="rag_wiki",
            wiki_status=SourceStatus.ERROR,
            rag_status=SourceStatus.TIMEOUT,
        )
    )
    voice_agent._call_web_search = AsyncMock(return_value="联网检索到的可靠资料。")
    voice_agent._generate_answer = AsyncMock(
        return_value=("根据联网资料说明关键要求。", "WebSearch")
    )
    voice_agent._generate_pure_llm = AsyncMock()

    answer = await voice_agent.generate("额定载荷怎么讲？", "partial-failure-session")

    assert answer == "根据联网资料说明关键要求。"
    voice_agent._call_web_search.assert_awaited_once_with("额定载荷怎么讲？")
    generation_args = voice_agent._generate_answer.await_args.args
    assert generation_args[1] == ""
    assert generation_args[2] == "联网检索到的可靠资料。"
    voice_agent._generate_pure_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_web_failure_after_both_timeouts_uses_safe_reply():
    with patch("voice.voice_agent.DashScope"), patch("voice.voice_agent.Agent"), patch(
        "voice.voice_agent.VOICE_TUTOR_SKILL_NAME", "voice-tutor-explain-only"
    ):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    voice_agent._get_history_context = AsyncMock(
        return_value="对话历史：\n用户: 我是安全员，用于现场讲解。"
    )
    voice_agent._classify_user_turn = AsyncMock(return_value="knowledge_query")
    voice_agent._call_knowledge_source = AsyncMock(
        return_value=FusedContext(
            text="",
            source_label="LLM",
            mode="rag_wiki",
            wiki_status=SourceStatus.TIMEOUT,
            rag_status=SourceStatus.TIMEOUT,
        )
    )
    voice_agent._call_web_search = AsyncMock(return_value="")
    voice_agent._generate_answer = AsyncMock()
    voice_agent._generate_pure_llm = AsyncMock()

    answer = await voice_agent.generate("额定载荷怎么讲？", "web-failure-session")

    assert "缺少可靠依据" in answer
    voice_agent._call_web_search.assert_awaited_once_with("额定载荷怎么讲？")
    voice_agent._generate_answer.assert_not_awaited()
    voice_agent._generate_pure_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_passes_file_scope_and_timeout_to_existing_rag_tool():
    with patch("voice.voice_agent.DashScope"), patch("voice.voice_agent.Agent"):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    with patch(
        "voice.voice_agent.knowledge_retrieve_auto_tool",
        new=AsyncMock(return_value=[]),
    ) as retrieve_tool, patch(
        "voice.voice_agent.VOICE_RAG_FILE_IDS", ["sample-document.pdf"]
    ):
        await voice_agent._call_original_rag("测试问题")

    assert retrieve_tool.await_args.kwargs["request_timeout_sec"] > 0
    assert retrieve_tool.await_args.kwargs["file_ids"] == ["sample-document.pdf"]
    assert "public_knowledge_base_dirs" not in retrieve_tool.await_args.kwargs
