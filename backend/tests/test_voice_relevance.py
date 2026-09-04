"""Tests for VoiceAgent relevance judgment logic."""

import sys
import os

# Ensure src is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from voice.voice_agent import VoiceAgent


@pytest.fixture
def voice_agent():
    """Create a VoiceAgent instance for testing."""
    with patch('voice.voice_agent.DashScope'), \
         patch('voice.voice_agent.Agent'):
        agent = VoiceAgent()
        return agent


class TestJudgeRelevance:
    """Tests for _judge_relevance method."""

    @pytest.mark.asyncio
    async def test_judge_relevance_full(self, voice_agent):
        """Test relevance judgment returns 'full'."""
        mock_response = MagicMock()
        mock_response.content = '{"relevance": "full"}'

        with patch('voice.voice_agent.Agent') as MockAgent:
            mock_agent_instance = AsyncMock()
            mock_agent_instance.arun.return_value = mock_response
            MockAgent.return_value = mock_agent_instance

            result = await voice_agent._judge_relevance("什么是炼钢?", "炼钢是在高温下...")

            assert result == "full"

    @pytest.mark.asyncio
    async def test_judge_relevance_partial(self, voice_agent):
        """Test relevance judgment returns 'partial'."""
        mock_response = MagicMock()
        mock_response.content = '{"relevance": "partial"}'

        with patch('voice.voice_agent.Agent') as MockAgent:
            mock_agent_instance = AsyncMock()
            mock_agent_instance.arun.return_value = mock_response
            MockAgent.return_value = mock_agent_instance

            result = await voice_agent._judge_relevance("炼钢温度?", "炼钢需要高温...")

            assert result == "partial"

    @pytest.mark.asyncio
    async def test_judge_relevance_none(self, voice_agent):
        """Test relevance judgment returns 'none'."""
        mock_response = MagicMock()
        mock_response.content = '{"relevance": "none"}'

        with patch('voice.voice_agent.Agent') as MockAgent:
            mock_agent_instance = AsyncMock()
            mock_agent_instance.arun.return_value = mock_response
            MockAgent.return_value = mock_agent_instance

            result = await voice_agent._judge_relevance("今天天气?", "炼钢是在高温下...")

            assert result == "none"

    @pytest.mark.asyncio
    async def test_judge_relevance_parse_error(self, voice_agent):
        """Test relevance judgment defaults to 'full' on parse error."""
        mock_response = MagicMock()
        mock_response.content = "I don't understand"

        with patch('voice.voice_agent.Agent') as MockAgent:
            mock_agent_instance = AsyncMock()
            mock_agent_instance.arun.return_value = mock_response
            MockAgent.return_value = mock_agent_instance

            result = await voice_agent._judge_relevance("测试问题", "测试内容")

            assert result == "full"

    @pytest.mark.asyncio
    async def test_judge_relevance_exception(self, voice_agent):
        """Test relevance judgment defaults to 'full' on exception."""
        with patch('voice.voice_agent.Agent') as MockAgent:
            mock_agent_instance = AsyncMock()
            mock_agent_instance.arun.side_effect = Exception("API error")
            MockAgent.return_value = mock_agent_instance

            result = await voice_agent._judge_relevance("测试问题", "测试内容")

            assert result == "full"


class TestGenerateAnswer:
    """Tests for _generate_answer method."""

    @pytest.mark.asyncio
    async def test_generate_answer_full_rag(self, voice_agent):
        """Test answer generation with full RAG relevance."""
        mock_response = MagicMock()
        mock_response.content = "根据资料，炼钢温度是1600度"

        voice_agent.agent = AsyncMock()
        voice_agent.agent.arun.return_value = mock_response

        answer, source = await voice_agent._generate_answer(
            "什么是炼钢温度?",
            "炼钢温度是1600度",
            "",
            "full",
            "test-session"
        )

        assert source == "RAG"
        assert "1600" in answer

    @pytest.mark.asyncio
    async def test_generate_answer_partial(self, voice_agent):
        """Test answer generation with partial relevance."""
        mock_response = MagicMock()
        mock_response.content = "根据资料和搜索结果..."

        voice_agent.agent = AsyncMock()
        voice_agent.agent.arun.return_value = mock_response

        answer, source = await voice_agent._generate_answer(
            "炼钢技术?",
            "炼钢需要高温",
            "最新技术是...",
            "partial",
            "test-session"
        )

        assert source == "RAG+WebSearch"

    @pytest.mark.asyncio
    async def test_generate_answer_none(self, voice_agent):
        """Test answer generation with no RAG relevance."""
        mock_response = MagicMock()
        mock_response.content = "搜索结果显示..."

        voice_agent.agent = AsyncMock()
        voice_agent.agent.arun.return_value = mock_response

        answer, source = await voice_agent._generate_answer(
            "今天天气?",
            "",
            "今天晴天",
            "none",
            "test-session"
        )

        assert source == "WebSearch"


class TestGeneratePureLLM:
    """Tests for _generate_pure_llm method."""

    @pytest.mark.asyncio
    async def test_generate_pure_llm(self, voice_agent):
        """Test pure LLM conversation."""
        mock_response = MagicMock()
        mock_response.content = "你好！有什么可以帮你的吗？"

        voice_agent.agent = AsyncMock()
        voice_agent.agent.arun.return_value = mock_response

        answer = await voice_agent._generate_pure_llm("你好", "test-session")

        assert "你好" in answer
