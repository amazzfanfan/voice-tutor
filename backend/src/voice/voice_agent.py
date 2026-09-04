"""VoiceAgent - agno Agent with conversational prompt for voice interaction."""

import asyncio
import json
import time
from typing import Any, Dict
from agno.agent import Agent
from agno.models.dashscope import DashScope
from voice.config import (
    DASHSCOPE_API_KEY,
    LLM_WIKI_BASE_URL,
    LLM_WIKI_MAX_CHARS,
    LLM_WIKI_PASSWORD,
    LLM_WIKI_USERNAME,
    LLM_WIKI_WORKSPACE,
    VOICE_FUSION_MAX_CHARS,
    VOICE_KNOWLEDGE_SOURCE,
    VOICE_MODEL_NAME,
    VOICE_RAG_CHUNK_MAX_CHARS,
    VOICE_RAG_CONTEXT_MAX_CHARS,
    VOICE_RAG_FILE_IDS,
    VOICE_RAG_MAX_CHUNKS,
    VOICE_RAG_TIMEOUT_SEC,
    VOICE_RETRIEVAL_TOTAL_TIMEOUT_SEC,
    VOICE_TUTOR_SKILL_NAME,
    VOICE_WEB_FALLBACK_TIMEOUT_SEC,
    VOICE_WIKI_CONTEXT_MAX_CHARS,
    VOICE_WIKI_TIMEOUT_SEC,
)
from voice.tutor_skill_runtime import TutorSkillRuntime
from voice.debug_log import compact_log_text, flow_log
from voice.retrieval_fusion import (
    FusedContext,
    RagMaterial,
    RetrievalBundle,
    SourceStatus,
    WikiMaterial,
    fuse_retrieval_bundle,
    rag_material_from_results,
    wiki_material_from_response,
)
from agno_agent.tools.retrieve_tool import knowledge_retrieve_auto_tool
from agno_agent.tools.web_search_tool import get_web_search_results
from algo.config import EXTERNAL_OPENAI_API_BASE, my_logger

import re

class VoiceAgent:
    """Voice tutor agent - oral, concise responses for voice interaction."""

    def __init__(self):
        self.llm = DashScope(
            id=VOICE_MODEL_NAME,
            api_key=DASHSCOPE_API_KEY,
            base_url=EXTERNAL_OPENAI_API_BASE,
            enable_thinking=False,
        )

        # Only include tools relevant to voice scenario
        self.tools = [knowledge_retrieve_auto_tool, get_web_search_results]

        self.tutor_skill_runtime = TutorSkillRuntime.from_settings(
            skill_name=VOICE_TUTOR_SKILL_NAME,
        )
        self.tutor_contract = self.tutor_skill_runtime.contract

        self.agent = Agent(
            model=self.llm,
            tools=self.tools,
            skills=self.tutor_skill_runtime.skills,
            name="AI语音讲师",
            id="voice-v1.1.0",
            description=self.tutor_skill_runtime.description,
            introduction=self.tutor_skill_runtime.introduction,
            instructions=self.tutor_skill_runtime.agent_instructions,
            add_name_to_context=True,
            add_datetime_to_context=True,
            timezone_identifier="Asia/Shanghai",
            retries=2,
            delay_between_retries=0.5,
            reasoning=False,
            markdown=True,  # Frontend renders Markdown; TTS removes display markers.
            telemetry=False,
            debug_mode=False,
        )

        # 本地存储对话历史，用于上下文理解
        self._conversation_history: Dict[str, list] = {}
        # 缓存每个 session 当前教学资料与最近几次历史资料，供后续教学轮次复用
        self._session_materials: Dict[str, Dict[str, Any]] = {}
        # 检索主题与生成画像分开保存，避免从 Markdown 对话历史中
        # 反推检索词。pending_query 是等待画像补充的原始问题，
        # current_topic_query 是当前资料缓存对应的独立知识问题。
        self._session_knowledge_state: Dict[str, Dict[str, str]] = {}
        # llm-wiki-demo 登录 token 缓存在内存中，避免每轮语音都重复登录。
        self._llm_wiki_token = ""

    async def _run_skill_generation(
        self,
        enriched_input: str,
        session_id: str,
        context_source: str,
    ) -> str:
        """Run the main Agent with only the active Skill access tools enabled."""
        self.agent.tools = []
        self.agent.tool_choice = "auto"

        flow_log(
            "06 生成",
            f"开始 | 来源={context_source} | 输入字符={len(enriched_input)} "
            f"| Skill={self.tutor_skill_runtime.skill_name}",
        )
        response = await self.agent.arun(input=enriched_input, session_id=session_id)
        answer = response.content or ""
        flow_log("06 生成", f"完成 | 草稿字符={len(answer)}")
        return answer

    async def generate(self, query: str, session_id: str) -> str:
        """Generate a voice-friendly response to the user's query.

        流程：Wiki/RAG并行检索 → 轻量融合 → WebSearch(严格按需) → 生成回答

        Args:
            query: The user's question (from STT).
            session_id: Session ID for conversation history.

        Returns:
            A short, oral-style text response.
        """
        flow_log("01 输入", f"问题：{compact_log_text(query)}")
        my_logger.info(f"[VoiceAgent] Generating response for: {query[:50]}...")

        try:
            context_source = ""

            # 先获取对话历史（不包含当前查询）
            history_context = await self._get_history_context(session_id)
            flow_log(
                "01 输入",
                f"历史={'有' if history_context else '无'} | 历史字符={len(history_context)}",
            )

            profile_prompt = self.tutor_skill_runtime.build_profile_prompt(
                query=query,
                history_context=history_context,
            )
            if profile_prompt:
                self._set_pending_query(session_id, query)
                flow_log("02 画像", "身份或使用场景不足，发起一次性询问")
                self._save_to_history(session_id, "user", query)
                final_text = str(
                    self.tutor_skill_runtime.postprocess_response(profile_prompt)["text"]
                )
                self._save_to_history(session_id, "assistant", final_text)
                my_logger.info(
                    "[VoiceAgent] Skill profile gate requested role and scenario"
                )
                flow_log(
                    "08 输出",
                    f"来源=画像询问 | 字符={len(final_text)} | 内容：{compact_log_text(final_text, 240)}",
                )
                return final_text
            flow_log("02 画像", "已满足，或当前 Skill 无需补充")

            # 没有上一轮语境时，极短或无效输入不具备“追问/新主题”关系，
            # 直接使用 Skill 的确定性语音噪声兜底。已有历史时则必须交给
            # 语义分类 Agent，避免把“为什么”之类的短追问误当成噪声。
            if not history_context:
                initial_repair_reply = (
                    self.tutor_skill_runtime.build_pre_retrieval_reply(
                        query=query,
                        history_context="",
                    )
                )
                if initial_repair_reply:
                    flow_log("03 路由", "无历史且输入不完整，跳过语义分类与检索")
                    self._save_to_history(session_id, "user", query)
                    final_text = str(
                        self.tutor_skill_runtime.postprocess_response(
                            initial_repair_reply
                        )["text"]
                    )
                    self._save_to_history(session_id, "assistant", final_text)
                    my_logger.info(
                        "[VoiceAgent] Initial unclear input skipped semantic classification"
                    )
                    flow_log(
                        "08 输出",
                        f"来源=语音澄清 | 字符={len(final_text)} | 内容：{compact_log_text(final_text, 240)}",
                    )
                    return final_text

            choice_reprompt = ""
            if self.tutor_skill_runtime.supports_quiz:
                choice_reprompt = self._build_choice_reprompt_if_needed(query, session_id)
            if choice_reprompt:
                my_logger.info(f"[VoiceAgent] 选择题答案疑似误识别，要求用户重说: {query[:50]}...")
                flow_log("03 路由", "疑似选择题答案误识别，跳过检索与生成")
                final_text = str(
                    self.tutor_skill_runtime.postprocess_response(choice_reprompt)["text"]
                )
                self._save_to_history(session_id, "assistant", final_text)
                flow_log(
                    "08 输出",
                    f"来源=答题重说 | 字符={len(final_text)} | 内容：{compact_log_text(final_text, 240)}",
                )
                return final_text

            # 使用独立的语义分类 Agent 判断本轮与最近对话的关系。纯讲解模式
            # 也必须区分追问和新主题，不能依赖“为什么/怎么”等关键词。
            flow_log("03 路由", "开始由语义分类 Agent 判断本轮意图")
            turn_type = await self._classify_user_turn(query, history_context)
            flow_log("03 路由", f"Agent 判定={turn_type}")

            if turn_type == "unclear_or_noise":
                pre_retrieval_reply = self.tutor_skill_runtime.build_pre_retrieval_reply(
                    query=query,
                    history_context=history_context,
                ) or "我刚才可能没听清，你可以把问题再完整说一遍。"
                self._save_to_history(session_id, "user", query)
                final_text = str(
                    self.tutor_skill_runtime.postprocess_response(pre_retrieval_reply)["text"]
                )
                self._save_to_history(session_id, "assistant", final_text)
                my_logger.info("[VoiceAgent] Semantic classifier skipped retrieval for unclear input")
                flow_log("04 资料", "无效或噪声输入，不使用教学资料")
                flow_log(
                    "08 输出",
                    f"来源=语音澄清 | 字符={len(final_text)} | 内容：{compact_log_text(final_text, 240)}",
                )
                return final_text

            has_cached_material = bool(self._get_session_material_context(session_id))
            flow_log("04 资料", f"会话缓存={'有' if has_cached_material else '无'}")
            if (
                turn_type in {"new_topic", "knowledge_query"}
                and has_cached_material
                and self._looks_like_profile_reply(query)
            ):
                turn_type = "profile_reply"
                flow_log("03 路由", "画像语义兜底：调整为 profile_reply")
            is_quiz_answer = turn_type == "answer"
            is_followup_query = turn_type == "followup_query"
            is_profile_reply = turn_type == "profile_reply"
            is_conversation_control = turn_type == "conversation_control"
            is_direct_answer_request = turn_type == "direct_answer_request"
            if is_profile_reply:
                self._save_user_profile(session_id, query)
            if is_quiz_answer:
                my_logger.info(f"[VoiceAgent] 检测到答题回复: {query[:30]}，跳过检索")
                flow_log("04 资料", "答题回复，跳过知识检索")
            elif is_followup_query:
                my_logger.info(f"[VoiceAgent] 语义分类为同主题追问: {query[:30]}")
                flow_log("04 资料", "同主题追问，优先复用会话缓存")
            elif is_profile_reply:
                my_logger.info(f"[VoiceAgent] 语义分类为身份/场景补充: {query[:30]}")
                flow_log(
                    "04 资料",
                    "身份或场景补充，复用会话缓存"
                    if has_cached_material
                    else "身份或场景补充，结合上一轮问题重新检索",
                )
            elif turn_type in {"new_topic", "knowledge_query"}:
                flow_log("04 资料", "新知识主题，准备重新检索")

            # 再保存用户查询到历史
            self._save_to_history(session_id, "user", query)

            pending_query = self._get_pending_query(session_id)
            should_retrieve_pending_query = bool(
                pending_query and (is_profile_reply or is_direct_answer_request)
            )

            # 答题回复、已有对应资料的画像补充和会话控制不进入知识检索。
            if (
                is_quiz_answer
                or (
                    is_profile_reply
                    and has_cached_material
                    and not should_retrieve_pending_query
                )
                or is_conversation_control
            ):
                context_source = "LLM"
                if is_quiz_answer:
                    answer = await self._generate_followup_answer(
                        query, session_id, history_context
                    )
                elif is_profile_reply:
                    cached_material_context = self._get_session_material_context(session_id)
                    flow_log(
                        "05 检索",
                        f"跳过 | 画像补充复用缓存 | 缓存字符={len(cached_material_context)}",
                    )
                    answer, context_source = await self._generate_answer(
                        query,
                        cached_material_context,
                        "",
                        "full",
                        session_id,
                        history_context,
                        context_source_override=self._infer_context_source_label(
                            cached_material_context
                        ),
                    )
                else:
                    answer = await self._generate_pure_llm(
                        query, session_id, history_context
                    )
            elif is_followup_query and has_cached_material:
                # 同主题追问优先复用当前会话已缓存的证据，避免把“为什么/第二点”
                # 当作新主题重复检索。生成阶段仍会同时看到最近对话历史。
                cached_material_context = self._get_session_material_context(session_id)
                flow_log(
                    "05 检索",
                    f"跳过 | 同主题追问复用缓存 | 缓存字符={len(cached_material_context)}",
                )
                answer, context_source = await self._generate_answer(
                    query,
                    cached_material_context,
                    "",
                    "full",
                    session_id,
                    history_context,
                    context_source_override=self._infer_context_source_label(
                        cached_material_context
                    ),
                )
            else:
                # Wiki、RAG 和联网只接收独立知识问题。画像补充和
                # “直接回答”取之前保存的原始问题；仅在追问缓存异常
                # 缺失时生成一个独立问题，不把对话历史传给检索服务。
                if should_retrieve_pending_query:
                    retrieval_query = pending_query
                    retrieval_reason = "待回答原始问题"
                elif is_followup_query:
                    current_topic_query = self._get_current_topic_query(session_id)
                    retrieval_query = await self._rewrite_followup_retrieval_query(
                        current_topic_query=current_topic_query,
                        followup_query=query,
                        history_context=history_context,
                    )
                    retrieval_reason = "缓存异常缺失的追问重写"
                else:
                    retrieval_query = query
                    retrieval_reason = "新知识问题"

                retrieval_query = self._clean_retrieval_query(retrieval_query)
                if not retrieval_query:
                    retrieval_query = self._clean_retrieval_query(query)

                self._set_current_topic_query(session_id, retrieval_query)
                if should_retrieve_pending_query:
                    self._clear_pending_query(session_id)

                generation_query = (
                    retrieval_query
                    if is_profile_reply or is_direct_answer_request
                    else query
                )
                # Step 1: 并行获取本地知识并做轻量确定性融合。
                flow_log(
                    "05 检索",
                    f"开始 | 模式={VOICE_KNOWLEDGE_SOURCE} | 原因={retrieval_reason} "
                    f"| 独立问题：{compact_log_text(retrieval_query)}",
                )
                retrieval_result = await self._call_knowledge_source(retrieval_query)
                # Keep tests and third-party subclasses that still return a string
                # source-compatible while the built-in implementation uses metadata.
                if isinstance(retrieval_result, FusedContext):
                    fused_context = retrieval_result
                else:
                    legacy_context = str(retrieval_result or "")
                    fused_context = FusedContext(
                        text=legacy_context,
                        source_label=self._infer_context_source_label(legacy_context),
                        mode=VOICE_KNOWLEDGE_SOURCE,
                    )

                knowledge_context = fused_context.text
                flow_log(
                    "05 检索",
                    f"融合结果 | 来源={fused_context.source_label} | 字符={len(knowledge_context)} "
                    f"| RAG原始={fused_context.rag_raw_count} | 保留={fused_context.rag_kept_count} "
                    f"| 去重={fused_context.duplicate_count}",
                )

                # Step 2: Normal local results use the service's own ranking. This
                # avoids an extra LLM relevance call on the voice latency path.
                relevance = "full" if knowledge_context else "none"
                flow_log(
                    "05 检索",
                    f"本地资料={'可用' if knowledge_context else '不可用'} | 不再额外调用相关性模型",
                )

                # Step 3: When local retrieval yields no usable evidence,
                # WebSearch is the final evidence fallback if either source
                # failed/timed out or Wiki explicitly recommends searching.
                web_context = ""
                should_search_web = (
                    not knowledge_context
                    and (
                        fused_context.has_source_failure
                        or fused_context.needs_web_search
                    )
                )
                if should_search_web:
                    web_query = self._clean_retrieval_query(
                        fused_context.search_query or retrieval_query
                    )
                    if fused_context.both_local_sources_timed_out:
                        flow_log(
                            "05 检索",
                            f"Wiki 与 RAG 均超时 | 启动联网兜底 | 超时={VOICE_WEB_FALLBACK_TIMEOUT_SEC:.1f}秒",
                        )
                    elif fused_context.has_source_failure:
                        flow_log(
                            "05 检索",
                            f"本地无可用资料且至少一个知识源异常或超时 | 启动联网兜底 | 超时={VOICE_WEB_FALLBACK_TIMEOUT_SEC:.1f}秒",
                        )
                    else:
                        flow_log(
                            "05 检索",
                            f"本地正常返回空且 Wiki 建议联网 | 超时={VOICE_WEB_FALLBACK_TIMEOUT_SEC:.1f}秒",
                        )
                    try:
                        web_context = await asyncio.wait_for(
                            self._call_web_search(web_query),
                            timeout=VOICE_WEB_FALLBACK_TIMEOUT_SEC,
                        )
                    except asyncio.TimeoutError:
                        flow_log("05 检索", "联网补充超时 | 快速降级")
                    flow_log("05 检索", f"联网资料字符={len(web_context)}")
                else:
                    flow_log("05 检索", "无需联网补充")

                self._save_session_materials(
                    session_id,
                    retrieval_query,
                    knowledge_context,
                    web_context,
                    relevance,
                )

                # Step 4: 生成回答
                if knowledge_context:
                    answer, context_source = await self._generate_answer(
                        generation_query,
                        knowledge_context,
                        web_context,
                        relevance,
                        session_id,
                        history_context,
                        context_source_override=(
                            fused_context.source_label
                            + ("+WebSearch" if web_context else "")
                        ),
                    )
                elif web_context:
                    answer, context_source = await self._generate_answer(
                        generation_query,
                        "",
                        web_context,
                        "none",
                        session_id,
                        history_context,
                    )
                else:
                    context_source = "知识源降级"
                    if fused_context.has_source_failure:
                        answer = (
                            "这个问题我现在还缺少可靠依据，先不凭空给你讲。"
                            "请稍后再试一次。"
                        )
                    else:
                        answer = (
                            "这个问题我现在还缺少可靠依据，先不凭空给你讲。"
                            "你可以把问题范围说得更具体一些，我再帮你查。"
                        )
                    flow_log("06 生成", "跳过 | 无可靠资料，使用确定性安全回复")

            flow_log("07 后处理", f"开始 | 草稿字符={len(answer)}")
            postprocess_result = self.tutor_skill_runtime.postprocess_response(
                answer,
                history_context=history_context,
            )
            final_text = str(postprocess_result.get("text", ""))
            violations = postprocess_result.get("violations") or []
            fixed_violations = postprocess_result.get("fixed_violations") or []
            if fixed_violations:
                flow_log("07 后处理", f"已自动修复={fixed_violations}")
            if violations:
                my_logger.warning(
                    f"[VoiceAgent] Skill postprocess violations: {violations}"
                )
                flow_log("07 后处理", f"仍有提示={violations}")
            if not fixed_violations and not violations:
                flow_log("07 后处理", "完成 | 无需修复")

            my_logger.info(f"[VoiceAgent] Response ({len(final_text)} chars, source={context_source}): {final_text[:80]}...")
            flow_log(
                "08 输出",
                f"来源={context_source} | 字符={len(final_text)} | 内容：{compact_log_text(final_text, 240)}",
            )

            # 保存助手回复到历史
            self._save_to_history(session_id, "assistant", final_text)

            return final_text

        except Exception as e:
            my_logger.error(f"[VoiceAgent] Generation failed: {e}")
            flow_log("99 异常", f"{type(e).__name__}: {compact_log_text(str(e), 240)}")
            fallback = "抱歉，我遇到了一些问题，无法回答你的问题。请稍后再试。"
            flow_log("08 输出", f"来源=异常兜底 | 内容：{fallback}")
            return fallback

    async def _get_history_context(self, session_id: str) -> str:
        """获取对话历史上下文，用于理解追问的上下文"""
        try:
            # 从本地存储获取历史消息
            if session_id in self._conversation_history:
                history = self._conversation_history[session_id]
                # 取最近的对话历史（最多保留最近5轮）
                recent_messages = history[-10:]  # 最近10条消息（5轮对话）
                history_parts = []
                for msg in recent_messages:
                    role = "用户" if msg["role"] == "user" else "讲师"
                    content = msg["content"][:1200]  # 保留最近题目和选项，避免答题轮次丢失题干
                    history_parts.append(f"{role}: {content}")
                if history_parts:
                    return "对话历史：\n" + "\n".join(history_parts)
        except Exception as e:
            my_logger.warning(f"[VoiceAgent] 获取对话历史失败: {e}")
        return ""

    def _save_to_history(self, session_id: str, role: str, content: str):
        """保存消息到对话历史"""
        if session_id not in self._conversation_history:
            self._conversation_history[session_id] = []
        self._conversation_history[session_id].append({
            "role": role,
            "content": content
        })
        # 限制历史长度，最多保留10条消息（约5轮对话）
        if len(self._conversation_history[session_id]) > 10:
            self._conversation_history[session_id] = self._conversation_history[session_id][-10:]

    def restore_conversation_history(self, session_id: str, messages: list) -> None:
        """Restore validated learner-facing history after a transport reconnect."""
        restored = []
        for message in (messages or [])[-10:]:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            content = message.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                continue
            content = content.strip()
            if not content:
                continue
            restored.append({"role": role, "content": content[:2000]})
        if restored:
            self._conversation_history[session_id] = restored
            state = self._get_session_knowledge_state(session_id)
            state["user_profile"] = self._extract_profile_context(session_id)
            state["pending_query"] = self._recover_pending_query_from_history(
                session_id
            )
            state["current_topic_query"] = (
                state["pending_query"]
                or self._recover_current_topic_query(session_id)
            )
            my_logger.info(
                f"[VoiceAgent] Restored {len(restored)} history messages after reconnect"
            )

    def _get_session_knowledge_state(self, session_id: str) -> Dict[str, str]:
        """Return structured topic/profile state for one voice session."""
        return self._session_knowledge_state.setdefault(
            session_id,
            {
                "pending_query": "",
                "current_topic_query": "",
                "user_profile": "",
            },
        )

    def _set_pending_query(self, session_id: str, query: str) -> None:
        cleaned = self._clean_retrieval_query(query)
        state = self._get_session_knowledge_state(session_id)
        state["pending_query"] = cleaned
        flow_log("02 画像", f"已保存待回答问题：{compact_log_text(cleaned)}")

    def _get_pending_query(self, session_id: str) -> str:
        return self._get_session_knowledge_state(session_id).get("pending_query", "")

    def _clear_pending_query(self, session_id: str) -> None:
        self._get_session_knowledge_state(session_id)["pending_query"] = ""

    def _set_current_topic_query(self, session_id: str, query: str) -> None:
        cleaned = self._clean_retrieval_query(query)
        self._get_session_knowledge_state(session_id)["current_topic_query"] = cleaned

    def _get_current_topic_query(self, session_id: str) -> str:
        state = self._get_session_knowledge_state(session_id)
        current = state.get("current_topic_query", "")
        if current:
            return current

        recovered = self._recover_current_topic_query(session_id)
        if recovered:
            state["current_topic_query"] = recovered
        return recovered

    def _save_user_profile(self, session_id: str, profile_reply: str) -> None:
        """Store role/scenario text for generation only; never for retrieval."""
        profile_reply = re.sub(r"\s+", " ", (profile_reply or "").strip())
        if not profile_reply:
            return
        state = self._get_session_knowledge_state(session_id)
        previous = state.get("user_profile", "")
        snippets = [item for item in (previous, profile_reply) if item]
        state["user_profile"] = "\n".join(dict.fromkeys(snippets))[-800:]
        flow_log("02 画像", "已保存身份/场景，仅用于回答生成")

    def _get_user_profile(self, session_id: str) -> str:
        state = self._get_session_knowledge_state(session_id)
        return state.get("user_profile", "") or self._extract_profile_context(
            session_id
        )

    @staticmethod
    def _clean_retrieval_query(query: str) -> str:
        """Normalize one standalone retrieval query and remove display markup."""
        text = (query or "").strip()
        if not text:
            return ""
        text = re.sub(r"!?(?:\[([^\]]*)\])\([^)]*\)", r"\1", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"(?m)^\s{0,3}(?:#{1,6}|[-+*]>?)\s*", "", text)
        text = text.replace("**", "").replace("__", "").replace("`", "")
        text = re.sub(r"\s+", " ", text).strip()
        return text[:500]

    def _recover_pending_query_from_history(self, session_id: str) -> str:
        """Recover a profile-gated question after transport reconnect."""
        history = self._conversation_history.get(session_id, [])
        if len(history) < 2:
            return ""

        profile_prompt_terms = ("什么岗位", "什么场景", "用在什么场景")
        for index in range(len(history) - 1, -1, -1):
            message = history[index]
            if message.get("role") != "assistant":
                continue
            content = message.get("content", "")
            if not any(term in content for term in profile_prompt_terms):
                continue

            later_messages = history[index + 1 :]
            if any(item.get("role") == "assistant" for item in later_messages):
                return ""
            for earlier in reversed(history[:index]):
                if earlier.get("role") == "user":
                    return self._clean_retrieval_query(earlier.get("content", ""))
        return ""

    def _recover_current_topic_query(self, session_id: str) -> str:
        """Best-effort recovery used only when in-memory topic state was lost."""
        materials = self._session_materials.get(session_id) or {}
        material_query = (materials.get("current") or {}).get("query", "")
        if material_query:
            return self._clean_retrieval_query(material_query)

        pending_query = self._get_session_knowledge_state(session_id).get(
            "pending_query", ""
        )
        if pending_query:
            return pending_query

        ignored_controls = ("直接讲", "直接回答", "不用问", "继续", "暂停", "慢一点")
        history = self._conversation_history.get(session_id, [])
        for message in reversed(history):
            if message.get("role") != "user":
                continue
            content = message.get("content", "")
            if self._looks_like_profile_reply(content):
                continue
            if any(term in content for term in ignored_controls):
                continue
            cleaned = self._clean_retrieval_query(content)
            if cleaned:
                return cleaned
        return ""

    async def _rewrite_followup_retrieval_query(
        self,
        current_topic_query: str,
        followup_query: str,
        history_context: str = "",
    ) -> str:
        """Rewrite an uncached follow-up into one standalone knowledge query."""
        current_topic_query = self._clean_retrieval_query(current_topic_query)
        followup_query = self._clean_retrieval_query(followup_query)
        fallback = self._clean_retrieval_query(
            f"{current_topic_query} {followup_query}".strip()
        )

        context_section = current_topic_query
        if not context_section:
            # Reconnect recovery may retain only dialogue history. It is used by the
            # internal rewrite Agent, never sent to Wiki, RAG, or WebSearch.
            context_section = history_context

        rewrite_prompt = f"""
当前知识主题：
{context_section or '（未恢复）'}

用户当前追问：
{followup_query}

将追问改写成一句可独立检索的中文知识问题。
补全被省略的技术对象，但不要加入用户岗位、使用场景、讲师回答或 Markdown。
只输出 JSON：{{"query":"..."}}
""".strip()
        rewrite_agent = Agent(
            model=self.llm,
            instructions="你是知识检索问题改写器。只输出 JSON，不回答问题。",
            markdown=False,
            telemetry=False,
        )
        try:
            response = await rewrite_agent.arun(input=rewrite_prompt)
            content = (response.content or "").strip()
            json_match = re.search(r"\{.*?\}", content, flags=re.DOTALL)
            payload = json.loads(json_match.group(0) if json_match else content)
            rewritten = self._clean_retrieval_query(str(payload.get("query", "")))
            if rewritten:
                flow_log(
                    "05 检索",
                    f"追问已重写为独立问题：{compact_log_text(rewritten)}",
                )
                return rewritten
        except Exception as exc:
            my_logger.warning(f"[VoiceAgent] 追问检索词重写失败: {exc}")
            flow_log("05 检索", "追问重写异常，使用结构化主题兜底")
        return fallback or followup_query

    def _save_session_materials(
        self,
        session_id: str,
        query: str,
        rag_context: str,
        web_context: str,
        relevance: str,
    ) -> None:
        """缓存当前教学主题的参考资料，供后续身份回复/答题轮次继续使用。"""
        if not rag_context and not web_context:
            return

        entry = {
            "query": query,
            "relevance": relevance,
            "rag_context": rag_context[:VOICE_FUSION_MAX_CHARS],
            "web_context": web_context[:4000],
        }
        previous = self._session_materials.get(session_id, {})
        history = previous.get("history", [])
        current = previous.get("current")
        if current:
            history = [current, *history][:3]

        self._session_materials[session_id] = {
            "current": entry,
            "history": history,
        }
        flow_log(
            "04 资料",
            f"缓存已更新 | 相关性={relevance} | 知识上下文字符={len(rag_context)} "
            f"| 联网字符={len(web_context)} | 历史资料={len(history)}",
        )

    def _get_session_material_context(self, session_id: str) -> str:
        """获取 session 缓存的教学资料文本。"""
        materials = self._session_materials.get(session_id)
        if not materials:
            return ""

        parts = []
        current = materials.get("current") or {}
        history = materials.get("history") or []

        if current:
            parts.append(self._format_material_entry(current, "当前主题资料"))

        if history:
            history_sections = [
                self._format_material_entry(entry, f"历史资料{i + 1}")
                for i, entry in enumerate(history[:3])
            ]
            parts.append("\n\n".join(history_sections))

        return "\n\n".join(parts)

    @staticmethod
    def _format_material_entry(entry: Dict[str, str], title: str) -> str:
        """格式化单条教学资料缓存。"""
        lines = [f"## {title}"]
        if entry.get("query"):
            lines.append(f"原始主题问题：{entry['query']}")
        if entry.get("rag_context"):
            lines.append(f"知识库资料：\n{entry['rag_context']}")
        if entry.get("web_context"):
            lines.append(f"联网资料：\n{entry['web_context']}")
        return "\n".join(lines)

    def _get_last_assistant_message(self, session_id: str) -> str:
        """Return the latest tutor message in raw form, without display truncation."""
        history = self._conversation_history.get(session_id, [])
        for msg in reversed(history):
            if msg.get("role") == "assistant":
                return msg.get("content", "")
        return ""

    def _extract_profile_context(self, session_id: str) -> str:
        """Extract likely user role/scenario snippets for tone adaptation only."""
        history = self._conversation_history.get(session_id, [])
        profile_terms = (
            "安全员", "操作", "维修", "检修", "班组", "培训", "考试", "备考",
            "现场", "讲解", "检查", "岗位", "运输工", "管理",
        )
        snippets = [
            msg.get("content", "")
            for msg in history
            if msg.get("role") == "user"
            and any(term in msg.get("content", "") for term in profile_terms)
        ]
        return "\n".join(snippets[-3:])[:800]

    @staticmethod
    def _looks_like_profile_reply(query: str) -> bool:
        """Heuristic fallback for role/scenario supplements after a topic was cached."""
        text = (query or "").strip()
        if not text:
            return False

        role_terms = (
            "安全员", "班组长", "新员工", "一线", "操作工", "维修", "检修",
            "管理人员", "培训师", "老师", "主管", "矿工", "运输工",
        )
        scenario_terms = (
            "用于", "用来", "为了", "准备", "讲解", "培训", "宣讲", "考试",
            "备考", "巡查", "检查", "班前会", "课件", "清单", "现场",
        )
        self_markers = ("我是", "我是一名", "我作为", "我的岗位", "岗位是", "担任")

        has_role = any(term in text for term in role_terms)
        has_scenario = any(term in text for term in scenario_terms)
        has_self_marker = any(marker in text for marker in self_markers)
        asks_new_topic = bool(re.search(r"什么是|介绍|解释|讲一下|说一下|为什么|怎么", text))

        if asks_new_topic and not has_self_marker:
            return False
        return (has_self_marker and (has_role or has_scenario)) or (has_role and has_scenario)

    @staticmethod
    def _infer_context_source_label(knowledge_context: str, web_context: str = "") -> str:
        """Infer a human-facing source label from the merged knowledge context."""
        labels = []
        text = knowledge_context or ""
        if text:
            has_wiki = any(
                marker in text
                for marker in (
                    "来源: LLM-Wiki",
                    "【Wiki结构化知识】",
                    "## Wiki概念上下文",
                )
            )
            has_rag = any(
                marker in text
                for marker in (
                    "【RAG原文检索片段】",
                    "## RAG原文依据",
                )
            ) or not has_wiki
            if has_wiki:
                labels.append("Wiki")
            if has_rag:
                labels.append("RAG")
        if web_context:
            labels.append("WebSearch")
        return "+".join(labels) if labels else "LLM"

    def _build_choice_reprompt_if_needed(self, query: str, session_id: str) -> str:
        """Ask the user to repeat when ASR output is unlikely to be a quiz answer."""
        question_context = self._get_recent_question_context(session_id)
        latest_question = question_context.get("latest") or ""
        options = self.tutor_contract.extract_choice_options(latest_question)
        if not options:
            return ""

        if self.tutor_contract.looks_like_choice_answer(query, options):
            return ""

        if self.tutor_contract.looks_like_teaching_topic(query):
            return ""

        labels = "、".join(options.keys())
        return f"我刚才这句可能没听清。你可以直接说{labels}，或者把选项内容说出来。"
    async def _is_semantic_duplicate_question(
        self,
        candidate_question: str,
        asked_questions: list,
    ) -> bool:
        """Use the model to detect same-knowledge-point quiz repetition."""
        if not candidate_question or not asked_questions:
            return False

        asked_section = "\n\n---\n\n".join(asked_questions[-6:])
        check_prompt = self.tutor_skill_runtime.render_reference(
            "semantic_duplicate_check",
            asked_section=asked_section,
            candidate_question=candidate_question,
        )

        checker = Agent(
            model=self.llm,
            instructions="你是选择题语义去重审查器。只输出JSON。",
            markdown=False,
            telemetry=False,
        )

        try:
            response = await checker.arun(input=check_prompt)
            content = (response.content or "").strip()
            json_match = re.search(r"\{.*?\}", content, flags=re.DOTALL)
            payload = json.loads(json_match.group(0) if json_match else content)
            duplicate = bool(payload.get("duplicate"))
            flow_log(
                "07 后处理",
                f"题目语义去重={duplicate} | 原因={compact_log_text(str(payload.get('reason', '')), 120)}",
            )
            return duplicate
        except Exception as e:
            my_logger.warning(f"[VoiceAgent] 语义重复审查失败: {e}")
            flow_log("07 后处理", f"题目去重异常，保留候选题 | {compact_log_text(str(e))}")
            return False

    async def _repair_semantic_duplicate_next_question(
        self,
        text: str,
        asked_questions: list,
        material_context: str,
        profile_context: str,
        session_id: str,
    ) -> str:
        """Replace a semantically duplicate next question, or summarize."""
        if len(asked_questions) >= 3:
            return text

        spans = self.tutor_contract.extract_choice_question_spans(text)
        if not spans or not asked_questions:
            return text

        candidate_span = spans[-1]
        candidate_question = candidate_span["block"]
        is_duplicate = await self._is_semantic_duplicate_question(
            candidate_question, asked_questions
        )
        if not is_duplicate:
            return text

        asked_section = "\n\n---\n\n".join(asked_questions[-6:])
        materials_section = material_context or "（当前没有可用缓存资料）"
        material_bullets = self.tutor_contract.extract_material_bullets(material_context) or "（未提取到条目，请直接阅读已缓存参考资料）"
        profile_section = profile_context or "（用户身份或场景不明确，使用通用工业教学口吻）"
        repair_prompt = self.tutor_skill_runtime.render_reference(
            "duplicate_question_repair",
            text=text,
            candidate_question=candidate_question,
            asked_section=asked_section,
            material_context=materials_section,
            material_bullets=material_bullets,
            profile_context=profile_section,
        )

        repair_agent = Agent(
            model=self.llm,
            instructions="你是语音教学回复修正器。只修正重复下一题，保留判题讲解。",
            markdown=False,
            telemetry=False,
        )

        try:
            response = await repair_agent.arun(input=repair_prompt)
            repaired = (response.content or "").strip()
            if not repaired:
                raise ValueError("empty repair response")

            repaired_spans = self.tutor_contract.extract_choice_question_spans(repaired)
            if repaired_spans:
                repaired_question = repaired_spans[-1]["block"]
                still_duplicate = await self._is_semantic_duplicate_question(
                    repaired_question, asked_questions
                )
                if still_duplicate:
                    flow_log("07 后处理", "重写题目仍重复，改为直接总结")
                    review = self._build_final_review(asked_questions, session_id, repaired)
                    return self.tutor_contract.replace_question_span(repaired, repaired_spans[-1], review)

            return repaired
        except Exception as e:
            my_logger.warning(f"[VoiceAgent] 重复题重写失败: {e}")
            flow_log("07 后处理", f"重复题重写失败，删除该题 | {compact_log_text(str(e))}")
            review = self._build_final_review(asked_questions, session_id, text)
            return self.tutor_contract.replace_question_span(text, candidate_span, review)

    async def _repair_missing_next_question_if_needed(
        self,
        text: str,
        asked_questions: list,
        material_context: str,
        profile_context: str,
        session_id: str,
    ) -> str:
        """Ask the model to add the next non-duplicate question when it omitted one."""
        if not text or len(asked_questions) >= 3:
            return text

        if self.tutor_contract.extract_choice_question_spans(text):
            return text

        if re.search(r"你还有什么想了解|这轮我们先收住|简要总结|总结一下", text):
            return text

        asked_section = "\n\n---\n\n".join(asked_questions[-6:])
        materials_section = material_context or "（当前没有可用缓存资料）"
        material_bullets = self.tutor_contract.extract_material_bullets(material_context) or "（未提取到条目，请直接阅读已缓存参考资料）"
        profile_section = profile_context or "（用户身份或场景不明确，使用通用工业教学口吻）"
        repair_prompt = self.tutor_skill_runtime.render_reference(
            "missing_question_repair",
            text=text,
            asked_section=asked_section,
            material_context=materials_section,
            material_bullets=material_bullets,
            profile_context=profile_section,
        )

        repair_agent = Agent(
            model=self.llm,
            instructions="你是语音教学回复补全器。只补下一题或总结，保留已有判题讲解。",
            markdown=False,
            telemetry=False,
        )

        try:
            response = await repair_agent.arun(input=repair_prompt)
            repaired = (response.content or "").strip()
            if not repaired:
                return text

            repaired_spans = self.tutor_contract.extract_choice_question_spans(repaired)
            if repaired_spans:
                repaired_question = repaired_spans[-1]["block"]
                still_duplicate = await self._is_semantic_duplicate_question(
                    repaired_question, asked_questions
                )
                if still_duplicate:
                    flow_log("07 后处理", "补全题目仍重复，改为直接总结")
                    review = self._build_final_review(asked_questions, session_id, repaired)
                    return self.tutor_contract.replace_question_span(repaired, repaired_spans[-1], review)

            return repaired
        except Exception as e:
            my_logger.warning(f"[VoiceAgent] 漏出下一题补全失败: {e}")
            flow_log("07 后处理", f"下一题补全失败，保留原回复 | {compact_log_text(str(e))}")
            return text

    def _get_recent_answer_labels(
        self,
        session_id: str,
        current_text: str,
        count: int,
    ) -> list:
        """Get recent correct-answer labels from history plus current reply."""
        history = self._conversation_history.get(session_id, [])
        joined = "\n".join(
            msg.get("content", "")
            for msg in history
            if msg.get("role") == "assistant"
        )
        labels = self.tutor_contract.extract_answer_labels(f"{joined}\n{current_text}")
        return labels[-count:] if count > 0 else []
    def _build_final_review(self, asked_questions: list, session_id: str, current_text: str) -> str:
        """Build a numbered, voice-friendly review when the quiz reaches its limit."""
        labels = self._get_recent_answer_labels(session_id, current_text, len(asked_questions))
        points = []
        for block in asked_questions:
            title = self.tutor_contract.question_title(block)
            options = self.tutor_contract.extract_choice_options(block)
            label = labels[len(points)] if len(points) < len(labels) else ""
            option_text = options.get(label, "")
            point = self.tutor_contract.compact_review_point(title, option_text)
            if point and point not in points:
                points.append(point)

        if points:
            numbered = "\n".join(
                f"{idx}、{point}。"
                for idx, point in enumerate(points[-3:], start=1)
            )
            return f"这轮我们先收住，简要总结一下：\n{numbered}\n你还有什么想了解的吗？"

        return "这轮我们先收住，简要总结一下：刚才练过的都是现场讲解时要抓住的关键数值和边界条件。你还有什么想了解的吗？"

    def _finalize_followup_output(self, text: str, asked_questions: list, session_id: str = "") -> str:
        """Apply deterministic guardrails after answer judging."""
        cleaned = self.tutor_contract.strip_internal_progress_text(text)
        cleaned = self.tutor_contract.remove_forbidden_question_tail(cleaned, asked_questions)
        cleaned = self.tutor_contract.strip_internal_progress_text(cleaned)
        cleaned = re.sub(r"(^|\n)\s*这轮我们先收住[。.]?\s*(?=\n|$)", "\n", cleaned).strip()

        if len(asked_questions) >= 3:
            has_numbered_review = re.search(r"(^|\n)\s*1[\.、]", cleaned)
            if not has_numbered_review:
                review = self._build_final_review(asked_questions, session_id, cleaned)
                cleaned = f"{cleaned}\n{review}".strip() if cleaned else review

        return self.tutor_contract.compact_output_lines(cleaned)

    def _get_recent_question_context(self, session_id: str) -> Dict[str, Any]:
        """Get the latest tutor question and previously asked question blocks."""
        history = self._conversation_history.get(session_id, [])
        asked_blocks = []
        latest_block = ""

        for msg in history:
            if msg.get("role") != "assistant":
                continue
            blocks = self.tutor_contract.extract_choice_question_blocks(msg.get("content", ""))
            if blocks:
                asked_blocks.extend(blocks)
                latest_block = blocks[-1]

        return {
            "latest": latest_block,
            "asked": asked_blocks[-6:],
            "last_assistant": self._get_last_assistant_message(session_id),
        }

    async def _classify_user_turn(self, query: str, history_context: str) -> str:
        """Use the LLM to classify the current voice turn.

        Returns:
            Guided practice: ``answer`` | ``profile_reply`` | ``new_topic``.
            Explain only: ``knowledge_query`` | ``followup_query`` |
            ``profile_reply`` | ``conversation_control`` |
            ``unclear_or_noise`` | ``direct_answer_request``.
        """
        if not history_context:
            return (
                "new_topic"
                if self.tutor_skill_runtime.supports_quiz
                else "knowledge_query"
            )

        classify_prompt = self.tutor_skill_runtime.render_reference(
            "turn_classifier",
            history_context=history_context,
            query=query,
        )

        judge_agent = Agent(
            model=self.llm,
            instructions=(
                "你是语音教学对话分类器。根据技术对象、用户意图和指代关系做语义判断；"
                "不要因为‘那、另外、为什么、怎么’等单个词直接下结论。只输出JSON，不解释。"
            ),
            markdown=False,
            telemetry=False,
        )

        try:
            response = await judge_agent.arun(input=classify_prompt)
            content = (response.content or "").strip()
            json_match = re.search(r'\{.*?\}', content, flags=re.DOTALL)
            payload = json.loads(json_match.group(0) if json_match else content)
            fallback_type = (
                "new_topic"
                if self.tutor_skill_runtime.supports_quiz
                else "knowledge_query"
            )
            turn_type = payload.get("turn_type", fallback_type)
            allowed_types = (
                {"answer", "profile_reply", "new_topic"}
                if self.tutor_skill_runtime.supports_quiz
                else {
                    "knowledge_query",
                    "profile_reply",
                    "followup_query",
                    "conversation_control",
                    "unclear_or_noise",
                    "direct_answer_request",
                }
            )
            if turn_type in allowed_types:
                return turn_type
            flow_log(
                "03 路由",
                f"Agent 返回非法值={turn_type} | 兜底={fallback_type}",
            )
        except Exception as e:
            my_logger.warning(f"[VoiceAgent] 用户轮次分类失败: {e}")
            flow_log(
                "03 路由",
                f"Agent 分类异常，使用安全检索兜底 | {compact_log_text(str(e))}",
            )

        return (
            "new_topic"
            if self.tutor_skill_runtime.supports_quiz
            else "knowledge_query"
        )

    async def _call_knowledge_source(self, query: str) -> FusedContext:
        """Retrieve local sources with one standalone plain-text query."""
        enriched_query = self._clean_retrieval_query(query)
        flow_log("05 检索", f"构造独立查询 | 问题：{compact_log_text(enriched_query)}")

        mode = (VOICE_KNOWLEDGE_SOURCE or "rag_only").lower()
        if mode not in {"rag_only", "wiki_only", "rag_wiki"}:
            my_logger.warning(f"[VoiceAgent] Unknown VOICE_KNOWLEDGE_SOURCE={mode}, fallback to rag_only")
            flow_log("05 检索", f"未知模式={mode} | 降级=rag_only")
            mode = "rag_only"

        flow_log("05 检索", f"执行知识源={mode}")
        started = time.monotonic()
        source_tasks: Dict[str, asyncio.Task] = {}
        if mode in {"wiki_only", "rag_wiki"}:
            source_tasks["wiki"] = asyncio.create_task(
                self._retrieve_wiki_material(enriched_query)
            )
        if mode in {"rag_only", "rag_wiki"}:
            source_tasks["rag"] = asyncio.create_task(
                self._retrieve_rag_material(enriched_query)
            )

        flow_log(
            "05 检索",
            f"并行启动 | 来源={'+'.join(source_tasks)} | 总预算={VOICE_RETRIEVAL_TOTAL_TIMEOUT_SEC:.1f}秒",
        )
        done, pending = await asyncio.wait(
            set(source_tasks.values()),
            timeout=VOICE_RETRIEVAL_TOTAL_TIMEOUT_SEC,
        )
        if pending:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            flow_log(
                "05 检索",
                f"总预算到期 | 取消未完成来源={len(pending)}",
            )

        elapsed_ms = round((time.monotonic() - started) * 1000)
        wiki_material = None
        rag_material = None
        for name, task in source_tasks.items():
            if task in done:
                try:
                    material = task.result()
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    material = (
                        WikiMaterial(SourceStatus.ERROR, elapsed_ms=elapsed_ms, error=error)
                        if name == "wiki"
                        else RagMaterial(SourceStatus.ERROR, elapsed_ms=elapsed_ms, error=error)
                    )
            else:
                material = (
                    WikiMaterial(
                        SourceStatus.TIMEOUT,
                        elapsed_ms=elapsed_ms,
                        error="retrieval total timeout",
                    )
                    if name == "wiki"
                    else RagMaterial(
                        SourceStatus.TIMEOUT,
                        elapsed_ms=elapsed_ms,
                        error="retrieval total timeout",
                    )
                )
            if name == "wiki":
                wiki_material = material
            else:
                rag_material = material

        bundle = RetrievalBundle(
            mode=mode,
            wiki=wiki_material,
            rag=rag_material,
            elapsed_ms=elapsed_ms,
        )
        fused = fuse_retrieval_bundle(bundle, max_chars=VOICE_FUSION_MAX_CHARS)
        flow_log(
            "05 检索",
            f"并行结束 | 总耗时={elapsed_ms}毫秒 | Wiki={self._source_status_text(fused.wiki_status)} "
            f"| RAG={self._source_status_text(fused.rag_status)}",
        )
        return fused

    async def _retrieve_rag_material(self, enriched_query: str) -> RagMaterial:
        """Apply a Voice-owned deadline and normalize existing ranked RAG chunks."""
        started = time.monotonic()
        flow_log("05 检索", f"RAG 启动 | 独立超时={VOICE_RAG_TIMEOUT_SEC:.1f}秒")
        try:
            results = await asyncio.wait_for(
                self._call_original_rag(enriched_query),
                timeout=VOICE_RAG_TIMEOUT_SEC,
            )
            elapsed_ms = round((time.monotonic() - started) * 1000)
            material = rag_material_from_results(
                results,
                elapsed_ms=elapsed_ms,
                max_chunks=VOICE_RAG_MAX_CHUNKS,
                chunk_max_chars=VOICE_RAG_CHUNK_MAX_CHARS,
                total_max_chars=VOICE_RAG_CONTEXT_MAX_CHARS,
            )
        except asyncio.TimeoutError:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            material = RagMaterial(
                SourceStatus.TIMEOUT,
                elapsed_ms=elapsed_ms,
                error="voice rag timeout",
            )
        except Exception as exc:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            error = f"{type(exc).__name__}: {exc}"
            material = RagMaterial(
                SourceStatus.ERROR,
                elapsed_ms=elapsed_ms,
                error=error,
            )
            my_logger.warning(f"[VoiceAgent] RAG call failed: {error}")

        flow_log(
            "05 检索",
            f"RAG 结束 | 状态={self._source_status_text(material.status)} "
            f"| 耗时={material.elapsed_ms}毫秒 "
            f"| 返回={material.raw_count} | 保留={len(material.chunks)} "
            f"| 去重={material.duplicate_count}",
        )
        return material

    async def _call_original_rag(self, enriched_query: str) -> list[Any]:
        """Call the retrieval service within the configured file scope."""
        return await knowledge_retrieve_auto_tool(
            query=enriched_query,
            file_ids=VOICE_RAG_FILE_IDS,
            request_timeout_sec=VOICE_RAG_TIMEOUT_SEC,
        )

    async def _retrieve_wiki_material(self, enriched_query: str) -> WikiMaterial:
        """Apply a Voice-owned deadline and normalize the existing Wiki response."""
        started = time.monotonic()
        flow_log("05 检索", f"Wiki 启动 | 独立超时={VOICE_WIKI_TIMEOUT_SEC:.1f}秒")
        try:
            payload = await asyncio.wait_for(
                self._call_wiki_retrieve(enriched_query),
                timeout=VOICE_WIKI_TIMEOUT_SEC,
            )
            elapsed_ms = round((time.monotonic() - started) * 1000)
            material = wiki_material_from_response(
                payload,
                elapsed_ms=elapsed_ms,
                max_chars=VOICE_WIKI_CONTEXT_MAX_CHARS,
            )
        except asyncio.TimeoutError:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            material = WikiMaterial(
                SourceStatus.TIMEOUT,
                elapsed_ms=elapsed_ms,
                error="voice wiki timeout",
            )
        except Exception as exc:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            error = f"{type(exc).__name__}: {exc}"
            material = WikiMaterial(
                SourceStatus.ERROR,
                elapsed_ms=elapsed_ms,
                error=error,
            )
            my_logger.warning(f"[VoiceAgent] Wiki retrieve failed: {error}")

        flow_log(
            "05 检索",
            f"Wiki 结束 | 状态={self._source_status_text(material.status)} "
            f"| 耗时={material.elapsed_ms}毫秒 "
            f"| 字符={len(material.context)} | 命中概念={len(material.matched_concepts)}",
        )
        return material

    async def _call_wiki_retrieve(self, enriched_query: str) -> Dict[str, Any]:
        """Call the unchanged llm-wiki retrieve API and return its JSON object."""
        if not LLM_WIKI_WORKSPACE:
            my_logger.warning("[VoiceAgent] LLM_WIKI_WORKSPACE is empty, skip wiki retrieve")
            flow_log("05 检索", "Wiki 跳过 | 未配置工作区")
            return {}

        token = await self._get_llm_wiki_token()
        if not token:
            my_logger.warning("[VoiceAgent] llm-wiki login token unavailable, skip wiki retrieve")
            flow_log("05 检索", "Wiki 跳过 | 登录凭证不可用")
            return {}

        url = f"{LLM_WIKI_BASE_URL}/api/wiki/retrieve"
        payload = {
            "query": enriched_query,
            "workspace": LLM_WIKI_WORKSPACE,
            "max_chars": min(LLM_WIKI_MAX_CHARS, VOICE_WIKI_CONTEXT_MAX_CHARS),
        }
        headers = {"Authorization": f"Bearer {token}"}

        import httpx
        from algo.app import project_app

        flow_log("05 检索", f"Wiki 请求 | 工作区={LLM_WIKI_WORKSPACE}")
        client = getattr(project_app.state, "http_client", None)
        if client is None:
            async with httpx.AsyncClient(timeout=VOICE_WIKI_TIMEOUT_SEC) as fallback_client:
                response = await fallback_client.post(url, json=payload, headers=headers)
        else:
            response = await client.post(
                url,
                json=payload,
                headers=headers,
                timeout=VOICE_WIKI_TIMEOUT_SEC,
            )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Wiki response is not a JSON object")
        return data

    @staticmethod
    def _source_status_text(status: SourceStatus | None) -> str:
        labels = {
            SourceStatus.SUCCESS: "成功(success)",
            SourceStatus.EMPTY: "无结果(empty)",
            SourceStatus.TIMEOUT: "超时(timeout)",
            SourceStatus.ERROR: "异常(error)",
        }
        return labels.get(status, "未启用")

    async def _get_llm_wiki_token(self) -> str:
        """Login to llm-wiki-demo and cache the JWT token for retrieve calls."""
        if self._llm_wiki_token:
            return self._llm_wiki_token

        if not LLM_WIKI_USERNAME or not LLM_WIKI_PASSWORD:
            my_logger.warning("[VoiceAgent] LLM_WIKI_USERNAME/PASSWORD missing, cannot login")
            flow_log("05 检索", "Wiki 登录跳过 | 未配置账号")
            return ""

        try:
            import httpx
            from algo.app import project_app

            url = f"{LLM_WIKI_BASE_URL}/api/auth/login"
            payload = {
                "username": LLM_WIKI_USERNAME,
                "password": LLM_WIKI_PASSWORD,
            }
            flow_log("05 检索", f"Wiki 登录 | 用户={LLM_WIKI_USERNAME}")
            client = getattr(project_app.state, "http_client", None)
            if client is None:
                async with httpx.AsyncClient(timeout=VOICE_WIKI_TIMEOUT_SEC) as fallback_client:
                    response = await fallback_client.post(url, json=payload)
            else:
                response = await client.post(
                    url,
                    json=payload,
                    timeout=VOICE_WIKI_TIMEOUT_SEC,
                )
            response.raise_for_status()
            data = response.json()
            token = data.get("token") or ""
            if token:
                self._llm_wiki_token = token
                flow_log("05 检索", "Wiki 登录成功，凭证已在内存复用")
                return token
            flow_log("05 检索", "Wiki 登录失败 | 响应中没有凭证")
            raise ValueError("Wiki login response has no token")
        except Exception as e:
            error_detail = f"{type(e).__name__}: {e!r}"
            my_logger.warning(f"[VoiceAgent] llm-wiki login failed: {error_detail}")
            flow_log("05 检索", f"Wiki 登录异常 | {compact_log_text(error_detail)}")
            raise

    async def _judge_relevance(self, query: str, rag_context: str) -> str:
        """判断 RAG 结果与用户问题的相关性

        返回: "full" | "partial" | "none"
        """
        flow_log("05 检索", f"开始判断资料相关性 | 问题：{compact_log_text(query, 100)}")

        judge_prompt = self.tutor_skill_runtime.render_reference(
            "relevance_judge",
            query=query,
            rag_context=rag_context,
        )

        judge_agent = Agent(
            model=self.llm,
            instructions="你是相关性判断专家，只输出JSON格式的判断结果。",
            markdown=False,
            telemetry=False,
        )

        try:
            response = await judge_agent.arun(input=judge_prompt)

            # 解析结果
            relevance_match = re.search(r'\{"relevance"\s*:\s*"(full|partial|none)"\}', response.content)
            if relevance_match:
                relevance = relevance_match.group(1)
                flow_log("05 检索", f"相关性 Agent 判定={relevance}")
                return relevance

            # 解析失败，默认为 full（兜底）
            my_logger.warning(f"[VoiceAgent] 相关性判断解析失败: {response.content[:100]}")
            flow_log("05 检索", "相关性结果无法解析 | 兜底=full")
            return "full"
        except Exception as e:
            my_logger.error(f"[VoiceAgent] 相关性判断失败: {e}")
            flow_log("05 检索", f"相关性判断异常 | 兜底=full | {compact_log_text(str(e))}")
            return "full"

    async def _generate_answer(
        self,
        query: str,
        rag_context: str,
        web_context: str,
        relevance: str,
        session_id: str,
        history_context: str = "",
        context_source_override: str = "",
    ) -> tuple:
        """Generate a grounded response with the active tutor Skill."""
        if context_source_override:
            context_source = context_source_override
        elif rag_context and web_context:
            context_source = "RAG+WebSearch"
        elif rag_context:
            context_source = "RAG"
        elif web_context:
            context_source = "WebSearch"
        else:
            context_source = "LLM"

        enriched_query = self.tutor_skill_runtime.build_generation_input(
            query=query,
            history_context=history_context,
            profile_context=self._get_user_profile(session_id),
            rag_context=rag_context,
            web_context=web_context,
        )
        answer = await self._run_skill_generation(
            enriched_query,
            session_id,
            context_source,
        )
        return answer, context_source

    async def _generate_followup_answer(
        self, query: str, session_id: str, history_context: str = ""
    ) -> str:
        """Judge the user's answer against only the latest tutor question."""
        material_context = self._get_session_material_context(session_id)
        question_context = self._get_recent_question_context(session_id)
        latest_question = question_context.get("latest") or ""
        asked_questions = question_context.get("asked") or []
        profile_context = self._extract_profile_context(session_id)

        if not latest_question:
            flow_log("04 资料", "未找到最近一道题，无法精确判题")
            return "我刚才那道题没有完整记录到。你可以再说一遍题目，或者直接告诉我你选的是A、B还是C。"

        asked_section = "\n\n---\n\n".join(asked_questions)
        asked_count = len(asked_questions)
        materials_section = material_context or "（当前没有可用缓存资料）"
        profile_section = profile_context or "（用户身份或场景不明确，使用通用工业教学口吻）"

        judge_prompt = self.tutor_skill_runtime.render_reference(
            "followup_judge",
            latest_question=latest_question,
            query=query,
            profile_context=profile_section,
            material_context=materials_section,
            asked_section=asked_section,
            asked_count=asked_count,
        )
        judge_agent = Agent(
            model=self.llm,
            instructions="你是语音教学答题判定器。只根据用户当前回答、最近一道题和参考资料输出，不要回到更早题目。",
            markdown=False,
            telemetry=False,
        )

        response = await judge_agent.arun(input=judge_prompt)
        answer = response.content or ""
        answer = await self._repair_semantic_duplicate_next_question(
            answer,
            asked_questions,
            material_context,
            profile_context,
            session_id,
        )
        answer = await self._repair_missing_next_question_if_needed(
            answer,
            asked_questions,
            material_context,
            profile_context,
            session_id,
        )
        answer = await self._repair_semantic_duplicate_next_question(
            answer,
            asked_questions,
            material_context,
            profile_context,
            session_id,
        )
        return self._finalize_followup_output(answer, asked_questions, session_id)

    async def _generate_pure_llm(
        self,
        query: str,
        session_id: str,
        history_context: str = "",
    ) -> str:
        """Generate a response without newly retrieved RAG or web material."""
        material_context = self._get_session_material_context(session_id)
        enriched_input = self.tutor_skill_runtime.build_generation_input(
            query=query,
            history_context=history_context,
            profile_context=self._get_user_profile(session_id),
            cached_material_context=material_context,
        )
        return await self._run_skill_generation(
            enriched_input,
            session_id,
            "LLM",
        )

    async def _call_web_search(self, query: str) -> str:
        """Call WebSearch with the same standalone query used for retrieval."""
        enriched_query = self._clean_retrieval_query(query)
        flow_log("05 检索", f"联网独立查询 | 问题：{compact_log_text(enriched_query)}")
        try:
            results = await get_web_search_results(enriched_query)
            if results and not results[0].get("is_error"):
                parts = []
                for item in results[:3]:
                    title = item.get("title", "")
                    content = item.get("content", "")
                    if title or content:
                        parts.append(f"{title}: {content}" if title else content)
                context = "\n".join(parts)
                if context:
                    my_logger.info(f"[VoiceAgent] WebSearch returned {len(results)} results, {len(context)} chars")
                    flow_log(
                        "05 检索",
                        f"联网完成 | 结果={len(results)} | 字符={len(context)} "
                        f"| 摘要：{compact_log_text(context, 220)}",
                    )
                    return context
            else:
                flow_log("05 检索", "联网未返回可用资料")
        except Exception as e:
            my_logger.warning(f"[VoiceAgent] WebSearch call failed: {e}")
            flow_log("05 检索", f"联网异常 | {compact_log_text(str(e))}")
        return ""
