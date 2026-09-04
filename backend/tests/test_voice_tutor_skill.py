"""Contract tests for the project-local voice tutor Skills runtime."""

import json

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice.tutor_skill_runtime import TutorSkillRuntime, TutorSkillRuntimeError


def test_guided_practice_skill_loads_with_agno_tools():
    runtime = TutorSkillRuntime("voice-tutor-guided-practice")

    assert runtime.supports_quiz is True
    assert runtime.requires_profile is False
    assert runtime.interaction_mode == "guided_practice"
    assert runtime.skills.get_skill_names() == ["voice-tutor-guided-practice"]
    assert {tool.name for tool in runtime.skills.get_tools()} == {
        "get_skill_instructions",
        "get_skill_reference",
        "get_skill_script",
    }
    assert "get_skill_instructions" in runtime.agent_instructions
    assert "voice-tutor-guided-practice" in runtime.agent_instructions


def test_skill_reference_rendering_and_generation_input():
    runtime = TutorSkillRuntime("voice-tutor-guided-practice")

    rendered = runtime.render_reference(
        "turn_classifier",
        history_context="讲师: 你现在是什么岗位？",
        query="我是维修人员，用于现场检修。",
    )
    assert "讲师: 你现在是什么岗位？" in rendered
    assert "我是维修人员" in rendered
    assert "{{history_context}}" not in rendered
    assert "{{query}}" not in rendered

    generation_input = runtime.build_generation_input(
        query="输送带有什么要求？",
        history_context="对话历史",
        rag_context="平硐内应采用阻燃型输送带。",
    )
    assert "## 对话历史" in generation_input
    assert "## 知识库检索结果" in generation_input
    assert "## 用户当前问题" in generation_input
    assert "voice-tutor-guided-practice" in generation_input


def test_skill_postprocessor_cleans_and_preserves_option_lines():
    runtime = TutorSkillRuntime("voice-tutor-guided-practice")
    result = runtime.postprocess_response(
        "<answer>问题？\nA. 选项一\nB. 选项二\n你觉得是哪个？ [R1]</answer>"
    )

    assert result["valid"] is True
    assert result["violations"] == []
    assert "forbidden_structured_markup" in result["fixed_violations"]
    assert result["text"] == "问题？\nA. 选项一\nB. 选项二\n你觉得是哪个？"


def test_agno_can_execute_the_skill_postprocessor():
    runtime = TutorSkillRuntime("voice-tutor-guided-practice")
    raw_result = runtime.skills._get_skill_script(
        "voice-tutor-guided-practice",
        "postprocess_response.py",
        execute=True,
        args=["--text", "<answer>讲解 [R1]</answer>"],
    )
    execution = json.loads(raw_result)
    output = json.loads(execution["stdout"])

    assert execution["returncode"] == 0
    assert output["valid"] is True
    assert output["text"] == "讲解"


def test_skill_postprocessor_can_enforce_future_explain_only_mode():
    runtime = TutorSkillRuntime("voice-tutor-guided-practice")
    runtime.manifest["supports_quiz"] = False

    result = runtime.postprocess_response(
        "问题？\nA. 选项一\nB. 选项二\n你觉得是哪个？"
    )

    assert result["valid"] is False
    assert "quiz_not_allowed" in result["violations"]


def test_explain_only_skill_loads_with_profile_aware_instructions():
    runtime = TutorSkillRuntime("voice-tutor-explain-only")

    assert runtime.supports_quiz is False
    assert runtime.requires_profile is True
    assert runtime.interaction_mode == "explain_only"
    assert runtime.skills.get_skill_names() == ["voice-tutor-explain-only"]
    assert "role" in runtime.instructions
    assert "usage scenario" in runtime.instructions
    assert "Never generate multiple-choice questions" in runtime.instructions
    assert "安全员现场讲解版" in runtime.instructions
    assert "display the original permille notation only" in runtime.instructions
    assert "3‰（千分之三，也就是0.3%）" not in runtime.instructions

    generation_input = runtime.build_generation_input(
        query="我是检修人员，准备现场排查故障。",
        history_context="用户：请讲讲带式输送机的保护装置。",
        cached_material_context="保护装置应按规定检查。",
    )
    assert "voice-tutor-explain-only" in generation_input
    assert "immediately explain the original topic" in generation_input


def test_explain_only_profile_gate_covers_first_technical_turn():
    runtime = TutorSkillRuntime("voice-tutor-explain-only")

    prompt = runtime.build_profile_prompt(
        "铁路运输线路应遵循下列哪些规定？"
    )
    assert "什么岗位" in prompt
    assert "什么场景" in prompt

    assert runtime.build_profile_prompt(
        "我是检修人员，准备用于现场故障排查，请讲讲铁路运输线路规定。"
    ) == ""
    scenario_prompt = runtime.build_profile_prompt(
        "我是检修人员，请讲讲铁路运输线路规定。"
    )
    assert "用在什么场景" in scenario_prompt

    assert runtime.build_profile_prompt("你好") == ""
    assert runtime.build_profile_prompt(
        "直接讲铁路运输线路规定，不用问我的身份。"
    ) == ""

    restored_history = (
        "对话历史：\n"
        "用户: 我现在是安全员，我要用于现场讲解。\n"
        "讲师: 我会按现场安全管控重点进行讲解。"
    )
    assert runtime.build_profile_prompt(
        "采用带式运输机应遵循哪些规定？",
        history_context=restored_history,
    ) == ""


def test_voice_agent_restores_profile_history_after_transport_reconnect():
    with patch("voice.voice_agent.DashScope"), patch("voice.voice_agent.Agent"), patch(
        "voice.voice_agent.VOICE_TUTOR_SKILL_NAME",
        "voice-tutor-explain-only",
    ):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    voice_agent.restore_conversation_history(
        "reconnected-session",
        [
            {"role": "user", "content": "铁路运输线路应遵循哪些规定？"},
            {"role": "assistant", "content": "你目前是什么岗位，用在什么场景？"},
            {"role": "user", "content": "我是安全员，用于现场讲解。"},
            {"role": "system", "content": "不得恢复的内部消息"},
        ],
    )

    history = voice_agent._conversation_history["reconnected-session"]
    assert len(history) == 3
    assert history[-1]["content"] == "我是安全员，用于现场讲解。"
    restored_state = voice_agent._session_knowledge_state["reconnected-session"]
    assert restored_state["pending_query"] == "铁路运输线路应遵循哪些规定？"
    assert "安全员" in restored_state["user_profile"]
    assert voice_agent.tutor_skill_runtime.build_profile_prompt(
        "采用带式运输机应遵循哪些规定？",
        history_context="对话历史：\n" + "\n".join(
            f"{'用户' if item['role'] == 'user' else '讲师'}: {item['content']}"
            for item in history
        ),
    ) == ""


def test_explain_only_postprocessor_removes_quiz_and_keeps_explanation():
    runtime = TutorSkillRuntime("voice-tutor-explain-only")
    result = runtime.postprocess_response(
        "对你做检修来说，重点是先确认设备状态。\n"
        "考考你：\n"
        "检查时首先看什么？\n"
        "A. 外观状态\n"
        "B. 设备颜色\n"
        "你觉得是哪个？"
    )

    assert result["valid"] is True
    assert result["text"] == "对你做检修来说，重点是先确认设备状态。"
    assert "quiz_not_allowed" in result["fixed_violations"]
    assert "quiz_options_not_allowed" in result["fixed_violations"]

    valid_explanation = runtime.postprocess_response(
        "对操作人员来说，正确的做法是先确认资料中明确给出的条件。"
    )
    assert valid_explanation["text"] == (
        "对操作人员来说，正确的做法是先确认资料中明确给出的条件。"
    )

    formatted = runtime.postprocess_response(
        "铁路运输线路应遵循以下规定：\n\n"
        "1. **坡度控制**：线路坡度不大于45‰。\n\n"
        "2. **曲线控制**：曲线段坡度不大于3‰。"
    )
    assert formatted["text"] == (
        "铁路运输线路应遵循以下规定：\n\n"
        "1. **坡度控制**：线路坡度不大于45‰。\n\n"
        "2. **曲线控制**：曲线段坡度不大于3‰。"
    )
    assert "\n\n" in formatted["text"]
    assert "**坡度控制**" in formatted["text"]

    markdown_sections = runtime.postprocess_response(
        "### 先看后果\n\n"
        "超载会让制动距离变长。\n\n"
        "### 现场记住\n\n"
        "- **装车前**：先核对吨位。\n"
        "- **运行中**：发现异常立即停车。"
    )
    assert markdown_sections["valid"] is True
    assert markdown_sections["text"].startswith("### 先看后果\n\n")
    assert "### 现场记住" in markdown_sections["text"]
    assert "- **装车前**" in markdown_sections["text"]

    hidden_profile_label = runtime.postprocess_response(
        "**铁路运输线路的核心规定（安全员现场讲解版）**\n"
        "这里先抓住两个能直接判断的指标。"
    )
    assert hidden_profile_label["text"] == (
        "### 铁路运输线路的核心规定\n\n"
        "这里先抓住两个能直接判断的指标。"
    )
    assert "安全员现场讲解版" not in hidden_profile_label["text"]

    cleaned_real_output = runtime.postprocess_response(
        "**铁路运输线路的硬性规定（安全员现场讲解要点）**\n"
        "作为安全员用于日常检查和现场讲解，重点抓七项硬指标：\n"
        "线路坡度不能超过45‰（千分之四十五，也就是4.5%）；"
        "曲线段不能超过3‰（千分之三，即0.3%）。"
    )
    assert cleaned_real_output["text"] == (
        "### 铁路运输线路的硬性规定\n\n"
        "重点抓七项硬指标：\n"
        "线路坡度不能超过45‰；曲线段不能超过3‰。"
    )
    assert "安全员" not in cleaned_real_output["text"]
    assert "4.5%" not in cleaned_real_output["text"]
    assert "千分之四十五" not in cleaned_real_output["text"]

    malformed_bold = runtime.postprocess_response(
        "**第一，坡度和曲线必须严守数值底线- **"
        "全线最大坡度不能超过 **：四十五千分之一**；\n"
        "曲线段坡度不能超 **三‰**。"
    )
    assert "**" not in malformed_bold["text"].splitlines()[0]
    assert "千分之四十五" in malformed_bold["text"]
    assert "四十五千分之一" not in malformed_bold["text"]
    assert "malformed_markdown_emphasis" in malformed_bold["fixed_violations"]

    repaired_sections = runtime.postprocess_response(
        "**一、线路坡度与曲线控制**\n\n"
        "主线路坡度≤45‰；\n"
        "平面连接曲线长度≥30 m。 **二、轨距要求** "
        "半径＜300 m时加宽10 mm；\n"
        "过渡长度≥30 m。 这些参数需要现场核验。"
    )
    assert repaired_sections["text"] == (
        "### 一、线路坡度与曲线控制\n\n"
        "- 主线路坡度≤45‰；\n"
        "- 平面连接曲线长度≥30 m。\n"
        "### 二、轨距要求\n\n"
        "- 半径＜300 m时加宽10 mm；\n"
        "- 过渡长度≥30 m。\n"
        "这些参数需要现场核验。"
    )

    first_profiled_answer = runtime.postprocess_response(
        "明白，你是安全员，要用于日常安全讲解——我这就为你详细讲清楚坡度控制要求。"
        "根据规程，线路坡度不得超过规定限值。",
        history_context=(
            "对话历史：\n"
            "用户: 铁路运输线路有哪些规定？\n"
            "讲师: 你目前是什么岗位，用在什么场景？\n"
            "用户: 我是安全员，用于安全讲解。"
        ),
    )
    assert first_profiled_answer["text"] == "根据规程，线路坡度不得超过规定限值。"

    later_history = (
        "对话历史：\n"
        "讲师: 你目前是什么岗位，用在什么场景？\n"
        "用户: 我是安全员，用于安全讲解。\n"
        "讲师: 明白，我先讲铁路运输线路的核心规定。\n"
        "用户: 细讲一下操作控制。"
    )
    repeated_intro = runtime.postprocess_response(
        "明白，你是安全员，要用于日常安全讲解——我这就为你详细讲清楚坡度控制要求。"
        "根据规程，线路坡度不得超过规定限值。",
        history_context=later_history,
    )
    assert repeated_intro["text"] == "根据规程，线路坡度不得超过规定限值。"

    profile_clause = runtime.postprocess_response(
        "作为安全员用于安全讲解，铁路运输线路的操作控制包括制动和运行秩序。",
        history_context=later_history,
    )
    assert profile_clause["text"] == (
        "铁路运输线路的操作控制包括制动和运行秩序。"
    )

    aged_history = (
        "对话历史：\n"
        "讲师: 前面已经完成了第一轮正式讲解。\n"
        "用户: 请继续。\n"
        "讲师: 这里继续说明第二个控制点。\n"
        "用户: 再讲一下制动。"
    )
    aged_profile_clause = runtime.postprocess_response(
        "作为安全员用于安全讲解，制动控制需要关注规定限值。",
        history_context=aged_history,
    )
    assert aged_profile_clause["text"] == "制动控制需要关注规定限值。"


def test_voice_agent_limits_conversation_history_to_ten_messages():
    with patch("voice.voice_agent.DashScope"), patch("voice.voice_agent.Agent"):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    for index in range(12):
        voice_agent._save_to_history("history-limit", "user", f"消息{index}")

    history = voice_agent._conversation_history["history-limit"]
    assert len(history) == 10
    assert history[0]["content"] == "消息2"


@pytest.mark.asyncio
async def test_voice_agent_enforces_explain_only_profile_gate_before_retrieval():
    with patch("voice.voice_agent.DashScope"), patch(
        "voice.voice_agent.Agent"
    ), patch(
        "voice.voice_agent.VOICE_TUTOR_SKILL_NAME",
        "voice-tutor-explain-only",
    ):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    voice_agent._get_history_context = AsyncMock(return_value="")
    voice_agent._call_rag = AsyncMock()
    answer = await voice_agent.generate(
        "铁路运输线路应遵循下列哪些规定？",
        "profile-gate-session",
    )

    assert "什么岗位" in answer
    assert "什么场景" in answer
    voice_agent._call_rag.assert_not_awaited()
    assert voice_agent._conversation_history["profile-gate-session"] == [
        {
            "role": "user",
            "content": "铁路运输线路应遵循下列哪些规定？",
        },
        {"role": "assistant", "content": answer},
    ]
    state = voice_agent._session_knowledge_state["profile-gate-session"]
    assert state["pending_query"] == "铁路运输线路应遵循下列哪些规定？"


@pytest.mark.asyncio
async def test_profile_reply_retrieves_pending_question_without_history_or_profile():
    with patch("voice.voice_agent.DashScope"), patch("voice.voice_agent.Agent"), patch(
        "voice.voice_agent.VOICE_TUTOR_SKILL_NAME",
        "voice-tutor-explain-only",
    ):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    session_id = "profile-pending-query-session"
    original_query = "铁路运输线路应遵循哪些规定？"
    first_answer = await voice_agent.generate(original_query, session_id)
    assert "什么岗位" in first_answer

    voice_agent._classify_user_turn = AsyncMock(return_value="profile_reply")
    voice_agent._call_knowledge_source = AsyncMock(return_value="铁路运输安全规定")
    voice_agent._generate_answer = AsyncMock(return_value=("安全规定讲解", "RAG"))

    await voice_agent.generate("我是安全员，用于现场安全讲解。", session_id)

    voice_agent._call_knowledge_source.assert_awaited_once_with(original_query)
    generation_args = voice_agent._generate_answer.await_args.args
    assert generation_args[0] == original_query
    state = voice_agent._session_knowledge_state[session_id]
    assert state["pending_query"] == ""
    assert state["current_topic_query"] == original_query
    assert "安全员" in state["user_profile"]


@pytest.mark.asyncio
async def test_direct_answer_request_uses_pending_question_as_retrieval_query():
    with patch("voice.voice_agent.DashScope"), patch("voice.voice_agent.Agent"), patch(
        "voice.voice_agent.VOICE_TUTOR_SKILL_NAME",
        "voice-tutor-explain-only",
    ):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    session_id = "direct-answer-pending-query-session"
    original_query = "带式输送机应遵循哪些规定？"
    await voice_agent.generate(original_query, session_id)

    voice_agent._classify_user_turn = AsyncMock(
        return_value="direct_answer_request"
    )
    voice_agent._call_knowledge_source = AsyncMock(return_value="输送机安全规定")
    voice_agent._generate_answer = AsyncMock(return_value=("直接讲解规定", "RAG"))

    await voice_agent.generate("不用问了，直接回答。", session_id)

    voice_agent._call_knowledge_source.assert_awaited_once_with(original_query)
    assert voice_agent._generate_answer.await_args.args[0] == original_query


@pytest.mark.asyncio
async def test_explain_only_initial_noise_skips_classifier_and_retrieval():
    with patch("voice.voice_agent.DashScope"), patch("voice.voice_agent.Agent"), patch(
        "voice.voice_agent.VOICE_TUTOR_SKILL_NAME",
        "voice-tutor-explain-only",
    ):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    voice_agent._get_history_context = AsyncMock(return_value="")
    voice_agent._classify_user_turn = AsyncMock()
    voice_agent._call_knowledge_source = AsyncMock()

    answer = await voice_agent.generate("啊", "initial-noise-session")

    assert "重新说一遍" in answer
    voice_agent._classify_user_turn.assert_not_awaited()
    voice_agent._call_knowledge_source.assert_not_awaited()


@pytest.mark.asyncio
async def test_explain_only_turn_classifier_accepts_semantic_followup_label():
    with patch("voice.voice_agent.DashScope"), patch("voice.voice_agent.Agent"), patch(
        "voice.voice_agent.VOICE_TUTOR_SKILL_NAME",
        "voice-tutor-explain-only",
    ):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    response = MagicMock()
    response.content = '{"turn_type":"followup_query","reason":"承接上一轮超载风险"}'
    with patch("voice.voice_agent.Agent") as agent_cls:
        classifier = AsyncMock()
        classifier.arun.return_value = response
        agent_cls.return_value = classifier

        result = await voice_agent._classify_user_turn(
            "为什么制动距离会变长？",
            "对话历史：\n讲师: 超载会让制动距离变长。",
        )

    assert result == "followup_query"
    sent_prompt = classifier.arun.await_args.kwargs["input"]
    assert "followup_query" in sent_prompt
    assert "Use semantic fit with the conversation" in sent_prompt


@pytest.mark.asyncio
async def test_explain_only_followup_reuses_cached_material_without_retrieval():
    with patch("voice.voice_agent.DashScope"), patch("voice.voice_agent.Agent"), patch(
        "voice.voice_agent.VOICE_TUTOR_SKILL_NAME",
        "voice-tutor-explain-only",
    ):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    session_id = "semantic-followup-session"
    history_context = (
        "对话历史：\n"
        "用户: 我是安全员，用于现场讲解。\n"
        "讲师: 超载会让制动距离变长。"
    )
    voice_agent._session_materials[session_id] = {
        "current": {
            "query": "超载有什么危害？",
            "relevance": "full",
            "rag_context": "超载会延长制动距离。",
            "web_context": "",
        },
        "history": [],
    }
    voice_agent._get_history_context = AsyncMock(return_value=history_context)
    voice_agent._classify_user_turn = AsyncMock(return_value="followup_query")
    voice_agent._call_knowledge_source = AsyncMock()
    voice_agent._generate_answer = AsyncMock(
        return_value=("### 原因\n\n制动距离变长，是因为负载增加。", "RAG")
    )

    answer = await voice_agent.generate("为什么会这样？", session_id)

    voice_agent._call_knowledge_source.assert_not_awaited()
    assert "### 原因" in answer
    generation_args = voice_agent._generate_answer.await_args.args
    assert "超载会延长制动距离" in generation_args[1]
    assert generation_args[5] == history_context


@pytest.mark.asyncio
async def test_uncached_followup_retrieves_only_rewritten_standalone_query():
    with patch("voice.voice_agent.DashScope"), patch("voice.voice_agent.Agent"), patch(
        "voice.voice_agent.VOICE_TUTOR_SKILL_NAME",
        "voice-tutor-explain-only",
    ):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    session_id = "uncached-followup-rewrite-session"
    history_context = (
        "对话历史：\n"
        "用户: 我是安全员，用于现场讲解。\n"
        "讲师: **铁路运输线路规定**"
    )
    voice_agent._session_knowledge_state[session_id] = {
        "pending_query": "",
        "current_topic_query": "铁路运输线路应遵循哪些规定？",
        "user_profile": "安全员，用于现场讲解",
    }
    voice_agent._get_history_context = AsyncMock(return_value=history_context)
    voice_agent._classify_user_turn = AsyncMock(return_value="followup_query")
    voice_agent._rewrite_followup_retrieval_query = AsyncMock(
        return_value="铁路运输线路的曲线要求有哪些？"
    )
    voice_agent._call_knowledge_source = AsyncMock(return_value="曲线安全规定")
    voice_agent._generate_answer = AsyncMock(return_value=("曲线要求讲解", "RAG"))

    await voice_agent.generate("详细讲一下曲线要求。", session_id)

    voice_agent._rewrite_followup_retrieval_query.assert_awaited_once_with(
        current_topic_query="铁路运输线路应遵循哪些规定？",
        followup_query="详细讲一下曲线要求。",
        history_context=history_context,
    )
    voice_agent._call_knowledge_source.assert_awaited_once_with(
        "铁路运输线路的曲线要求有哪些？"
    )


@pytest.mark.asyncio
async def test_explain_only_new_topic_retrieval_excludes_old_topic_history():
    with patch("voice.voice_agent.DashScope"), patch("voice.voice_agent.Agent"), patch(
        "voice.voice_agent.VOICE_TUTOR_SKILL_NAME",
        "voice-tutor-explain-only",
    ):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    session_id = "semantic-new-topic-session"
    history_context = (
        "对话历史：\n"
        "用户: 我是安全员，用于现场讲解。\n"
        "讲师: 刚才讲的是电机车超载。"
    )
    voice_agent._get_history_context = AsyncMock(return_value=history_context)
    voice_agent._classify_user_turn = AsyncMock(return_value="knowledge_query")
    voice_agent._call_knowledge_source = AsyncMock(return_value="破碎机润滑资料")
    voice_agent._judge_relevance = AsyncMock(return_value="full")
    voice_agent._generate_answer = AsyncMock(
        return_value=("### 润滑检查\n\n先确认油位。", "RAG")
    )

    await voice_agent.generate("圆锥破碎机怎么检查润滑？", session_id)

    voice_agent._call_knowledge_source.assert_awaited_once_with(
        "圆锥破碎机怎么检查润滑？"
    )


def test_voice_agent_can_select_explain_only_skill_without_code_changes():
    with patch("voice.voice_agent.DashScope"), patch(
        "voice.voice_agent.Agent"
    ) as agent_cls, patch(
        "voice.voice_agent.VOICE_TUTOR_SKILL_NAME",
        "voice-tutor-explain-only",
    ):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    kwargs = agent_cls.call_args.kwargs
    assert voice_agent.tutor_skill_runtime.interaction_mode == "explain_only"
    assert voice_agent.tutor_skill_runtime.supports_quiz is False
    assert kwargs["skills"].get_skill_names() == ["voice-tutor-explain-only"]


def test_skill_postprocessor_repairs_inline_options_and_multiple_questions():
    runtime = TutorSkillRuntime("voice-tutor-guided-practice")
    result = runtime.postprocess_response(
        "第一题？ A. 一 B. 二 你觉得是哪个？\n"
        "第二题？ A. 三 B. 四 你觉得是哪个？"
    )

    assert result["valid"] is True
    assert result["text"].count("你觉得是哪个") == 1
    assert "\nA. 一\nB. 二" in result["text"]
    assert "multiple_questions" in result["fixed_violations"]
    assert "options_not_line_separated" in result["fixed_violations"]


def test_runtime_fails_fast_for_missing_skill():
    with pytest.raises(TutorSkillRuntimeError):
        TutorSkillRuntime.from_settings(skill_name="missing-voice-tutor-skill")


def test_voice_agent_receives_only_the_active_skill():
    with patch("voice.voice_agent.DashScope"), patch(
        "voice.voice_agent.Agent"
    ) as agent_cls, patch(
        "voice.voice_agent.VOICE_TUTOR_SKILL_NAME",
        "voice-tutor-guided-practice",
    ):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    kwargs = agent_cls.call_args.kwargs
    assert voice_agent.tutor_skill_runtime.skill_name == "voice-tutor-guided-practice"
    assert kwargs["skills"].get_skill_names() == ["voice-tutor-guided-practice"]
    assert "get_skill_instructions" in kwargs["instructions"]


def test_skill_contract_owns_quiz_parsing_and_guardrails():
    runtime = TutorSkillRuntime("voice-tutor-guided-practice")
    question = (
        "线路坡度应满足什么要求？\n"
        "A. 不大于35‰\n"
        "B. 不大于45‰\n"
        "C. 不大于55‰\n"
        "你觉得是哪个？"
    )

    assert runtime.contract.extract_choice_question_blocks(question) == [question]
    assert runtime.contract.extract_choice_options(question) == {
        "A": "不大于35‰",
        "B": "不大于45‰",
        "C": "不大于55‰",
    }
    assert runtime.contract.looks_like_choice_answer("我选B", {"B": "不大于45‰"})
    assert runtime.contract.extract_answer_labels("正确答案是Ｂ，所以不对") == ["B"]

    guarded = runtime.contract.remove_forbidden_question_tail(
        f"讲解完成。\n{question}",
        [question],
    )
    assert guarded.count("你觉得是哪个") == 0
    assert "这道题刚才已经练过了" in guarded


@pytest.mark.asyncio
async def test_skill_generation_keeps_skill_tools_available():
    with patch("voice.voice_agent.DashScope"), patch("voice.voice_agent.Agent"):
        from voice.voice_agent import VoiceAgent

        voice_agent = VoiceAgent()

    response = MagicMock()
    response.content = "我先了解一下，你现在是什么岗位？这次准备用在什么场景？"
    voice_agent.agent = AsyncMock()
    voice_agent.agent.arun.return_value = response

    answer, source = await voice_agent._generate_answer(
        "输送带有什么要求？",
        "平硐内应采用阻燃型输送带。",
        "",
        "full",
        "skill-test-session",
    )

    assert source == "RAG"
    assert answer == response.content
    assert voice_agent.agent.tools == []
    assert voice_agent.agent.tool_choice == "auto"
    sent_input = voice_agent.agent.arun.await_args.kwargs["input"]
    assert "## 知识库检索结果" in sent_input
    assert "平硐内应采用阻燃型输送带" in sent_input
