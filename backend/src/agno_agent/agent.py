"""
Deep Agent 核心实现
基于 agno Agent 框架的问答智能体
"""

import json
import mimetypes
import os
import re
import traceback
from dataclasses import replace
from typing import List, Dict, Any

from agno.agent import Agent
from agno.media import Image
from agno.models.dashscope import DashScope
from agno.models.openai import OpenAILike
from agno.run.agent import RunContentEvent, ModelRequestCompletedEvent, RunContentCompletedEvent, RunCompletedEvent

from agno_agent.prompt_center import load_agent_prompt
from agno_agent.tool import set_tool_runtime_context, clear_tool_runtime_context, get_tool_runtime_context
from agno_agent.tools.attachment_processing_tool import attachment_processing_func
from agno_agent.tools.document_reading_tool import document_reader_tool
from agno_agent.tools.retrieve_tool import knowledge_retrieve_auto_tool
from agno_agent.tools.web_search_tool import get_web_search_results
from algo.base_ai.ocr import ocr_result, get_image_base64
from algo.config import (INTERNAL_MODEL_NAME, INTERNAL_OPENAI_API_BASE, INTERNAL_OPENAI_API_KEY, EXTERNAL_MODEL_NAME,
                         EXTERNAL_OPENAI_API_BASE, EXTERNAL_OPENAI_API_KEY, my_logger)
from algo.datatype import AgentParam, AttachmentFile, SubagentDataEvent


class QAAgent:
    """问答智能体主类"""
    DEFAULT_PROMPT_TYPE = "GENERAL"

    EXTERNAL_MODEL = DashScope(
        base_url=EXTERNAL_OPENAI_API_BASE,
        api_key=EXTERNAL_OPENAI_API_KEY,
        id=EXTERNAL_MODEL_NAME,
        enable_thinking=False,
    )

    INTERNAL_MODEL = OpenAILike(
        id=INTERNAL_MODEL_NAME,
        base_url=INTERNAL_OPENAI_API_BASE,
        api_key=INTERNAL_OPENAI_API_KEY,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}}
    )

    def __init__(self, model_source):
        if model_source == "INTERNAL":
            self.llm = self.__class__.INTERNAL_MODEL
            my_logger.info(f"✅ 使用内部模型: {INTERNAL_MODEL_NAME}")
        else:
            self.llm = self.__class__.EXTERNAL_MODEL
            my_logger.info(f"✅ 使用外部模型: {EXTERNAL_MODEL_NAME}")

        self.prompt_type = (os.getenv("QA_AGENT_PROMPT_TYPE", self.DEFAULT_PROMPT_TYPE).strip().upper()
                            or self.DEFAULT_PROMPT_TYPE)
        prompt_data = self._load_prompt_data()
        self._prompt_signature = self._build_prompt_signature(prompt_data)

        # 构建 tools
        self.tools = [knowledge_retrieve_auto_tool, get_web_search_results, ocr_result, document_reader_tool, attachment_processing_func]
        self._default_tools = list(self.tools)
        self._tool_by_name = {
            (getattr(tool, "name", None) or getattr(tool, "__name__")): tool
            for tool in self.tools
            if getattr(tool, "name", None) or getattr(tool, "__name__", None)
        }

        # 创建 agno Agent
        self.agent = Agent(
            model=self.llm,
            tools=self.tools,
            name="RAG智能助手",
            id="v1.0.0",
            cache_session=True,  # 内存访问
            read_tool_call_history=True,  # 把工具调用的结果也加入到对话历史
            description=prompt_data["description"],
            introduction=prompt_data["introduction"],
            instructions=prompt_data["instructions"],
            add_name_to_context=True,
            add_datetime_to_context=True,
            add_session_summary_to_context=True,
            timezone_identifier="Asia/Shanghai",
            retries=3,
            delay_between_retries=1,
            # parser_model  主模型不支持格式化输出时
            reasoning=False,
            markdown=True,
            telemetry=False,
            debug_mode=True,
            debug_level=2
        )

    def _build_prompt_signature(self, prompt_data: Dict[str, Any]):
        return (
            prompt_data["description"],
            prompt_data["introduction"],
            prompt_data["instructions"],
        )

    def _load_prompt_data(self) -> Dict[str, Any]:
        return load_agent_prompt(self.prompt_type)

    def _refresh_prompt_if_needed(self):
        prompt_data = self._load_prompt_data()
        current_signature = self._build_prompt_signature(prompt_data)
        if current_signature == self._prompt_signature:
            return

        self.agent.description = prompt_data["description"]
        self.agent.introduction = prompt_data["introduction"]
        self.agent.instructions = prompt_data["instructions"]
        self._prompt_signature = current_signature
        print(f"[PromptRegistry] 已应用最新 Prompt（{self.prompt_type}）")

    def _get_available_tool_names(self) -> List[str]:
        names: List[str] = []
        for tool in self.agent.tools or []:
            tool_name = getattr(tool, "name", None)
            if isinstance(tool_name, str) and tool_name.strip():
                names.append(tool_name.strip())
        return names

    def _select_tools_for_request(self, param: AgentParam) -> List[Any]:
        """按本次请求动态收缩可用工具"""
        use_rag = param.use_rag
        use_web = param.use_web_search
        has_documents = bool(param.documents) and len(param.documents) > 0
        has_attachments = bool(param.attachments) and len(param.attachments) > 0

        selected_tools: List[Any] = []

        # Rag 相关工具
        if use_rag:
            tool = self._tool_by_name.get("知识库检索")
            if tool is not None:
                selected_tools.append(tool)

        # Web 搜索工具
        if use_web:
            tool = self._tool_by_name.get("联网搜索")
            if tool is not None:
                selected_tools.append(tool)

        # 文档阅读工具
        if has_documents:
            tool = self._tool_by_name.get("文档阅读")
            if tool is not None:
                selected_tools.append(tool)

        # 附件处理工具
        if has_attachments:
            tool = self._tool_by_name.get("附件处理")
            if tool is not None:
                selected_tools.append(tool)

        # # 如果没有任何特定需求，则使用默认完整工具列表（防止后续请求变空）
        # if not selected_tools:
        #     return list(self._default_tools)

        return selected_tools

    def _resolve_tool_choice(self, param: AgentParam) -> str:
        """决定 tool_choice"""
        use_rag = param.use_rag
        use_web = param.use_web_search
        has_documents = bool(param.documents) and len(param.documents) > 0
        has_attachments = bool(param.attachments) and len(param.attachments) > 0

        # 只要有任何需要工具的场景，就允许模型自主决定（auto）
        if use_rag or use_web or has_documents or has_attachments:
            return "auto"  # 用 "auto"，让模型根据 prompt 决定是否调用

        return "none"  # 只有纯闲聊时才禁用工具

    @staticmethod
    def _clean_history_answer(answer_text: str) -> str:
        """清理单个 <answer> 内容"""
        if not answer_text:
            return ""

        text = answer_text.strip()

        # 移除可能存在的 <references> 整个块
        text = re.sub(r'<references>.*?</references>', '', text, flags=re.DOTALL | re.IGNORECASE)

        # 提取 <answer> 内部文本
        match = re.search(r'<answer>\s*(.*?)\s*</answer>', text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1)

        # 移除所有引用标记 [W1] [R2.3] 等
        text = re.sub(r'\s*\[(?:W|R)\d+(?:\.\d+)?\]', '', text)

        # 清理格式
        text = re.sub(r'\n{3,}', '\n\n', text.strip())
        text = re.sub(r' +', ' ', text)

        return text.strip()

    @staticmethod
    def _clean_query_with_history(query: str) -> str:
        """
        改进版：同时保留 User input 和干净的 Answer
        """
        if not query or not isinstance(query, str):
            return query

        # 提取整个历史上下文块
        context_match = re.search(r'(<workflow_history_context>.*?</workflow_history_context>)',
                                  query, flags=re.DOTALL | re.IGNORECASE)
        if not context_match:
            return query

        original_context = context_match.group(1)

        # 匹配每一轮完整的 Workflow Run
        runs = re.findall(
            r'(\[Workflow Run-\d+\][\s\S]*?)(?=\[Workflow Run-\d+\]|</workflow_history_context>)',
            original_context,
            flags=re.DOTALL | re.IGNORECASE
        )

        clean_parts = []
        for i, run in enumerate(runs[-5:], 1):  # 最多保留最近 5 轮
            # 提取 User input
            user_match = re.search(r'User input:\s*(.+?)(?=Workflow output:|$)', run, flags=re.DOTALL | re.IGNORECASE)
            user_input = user_match.group(1).strip() if user_match else ""

            # 提取并清理 Answer
            answer_match = re.search(r'Workflow output:\s*<answer>\s*(.*?)\s*</answer>',
                                     run, flags=re.DOTALL | re.IGNORECASE)
            clean_answer = ""
            if answer_match:
                clean_answer = QAAgent._clean_history_answer(answer_match.group(1))

            # 组合成清晰格式
            if user_input or clean_answer:
                part = f"[历史对话 {i}]"
                if user_input:
                    part += f"\n用户: {user_input}"
                if clean_answer:
                    part += f"\n助手: {clean_answer}"
                clean_parts.append(part)

        # 重新组装
        if clean_parts:
            clean_history = "<workflow_history_context>\n" + "\n\n".join(clean_parts) + "\n</workflow_history_context>"
        else:
            clean_history = "<workflow_history_context>\n(无有效历史对话)\n</workflow_history_context>"

        # 替换原历史块
        cleaned_query = query.replace(original_context, clean_history)

        return cleaned_query.strip()

    def _classify_attachments(self, attachments: List[AttachmentFile]) -> tuple[List[AttachmentFile], List[Image]]:
        """
        将附件分为文档列表和 agno Image 对象列表
        返回: (纯文档附件列表, agno Image 对象列表)
        """
        doc_attachments: List[AttachmentFile] = []
        image_objects: List[Image] = []

        for attachment in attachments:
            path = attachment.path
            if not path:
                continue

            mime_type, _ = mimetypes.guess_type(path)

            if mime_type and mime_type.startswith('image/'):
                try:
                    # 获取 Base64 编码
                    base64_str = get_image_base64(path)
                    if not base64_str.startswith("处理失败"):
                        # 直接构建 agno Image 对象
                        img_obj = Image.from_base64(
                            base64_content=base64_str,
                            mime_type=mime_type,
                            detail="auto"
                        )
                        image_objects.append(img_obj)
                        continue  # 是图片且处理成功，不进入 docs 列表
                except Exception as e:
                    my_logger.error(f"图片转换失败 {path}: {e}")

            # 非图片或处理失败的图片（作为回退）进入文档列表
            doc_attachments.append(attachment)

        return doc_attachments, image_objects

    async def stream_run(self, agent_param: AgentParam, request, run_id: str, session_id: str):
        # 先把本次请求上下文挂到工具运行时环境中，便于 retrieve/search 工具直接读取。
        set_tool_runtime_context(agent_param)

        # 预处理附件
        raw_attachments = agent_param.attachments or []
        # 分离出 非图片附件 和 图片附件
        doc_attachments, images = self._classify_attachments(raw_attachments)

        # 更新 agent_param，确保后续工具和 prompt 看到的是排除图片后的附件列表
        agent_param.attachments = doc_attachments

        # 根据传入的参数确定调用web搜索工具还是rag工具
        self.agent.tools = self._select_tools_for_request(agent_param)
        # 只要 use_rag 或 use_web_search 为真，就返回 "auto"，表示"允许模型自主决定是否调用工具、调用哪个工具"，否则返回 "none" 禁止调用工具。
        self.agent.tool_choice = self._resolve_tool_choice(agent_param)
        my_logger.info(
            f"agno tool routing: tool_choice={self.agent.tool_choice}, tools={self._get_available_tool_names()}"
        )

        # 用于记录模型输出的完整文本，以便最后提取用到的 ID
        accumulated_text = ""

        # 暂存用于克隆元数据的参考事件
        reference_event = None
        # 暂存所有标志"结束"的事件
        completion_events = []

        try:
            # stream=True 表示按事件流方式逐段返回模型输出。
            async for event in self.agent.arun(
                    input=agent_param,
                    images=images,
                    session_id=session_id,
                    run_id=run_id,
                    stream=True,
                    stream_events=True
            ):
                if await request.is_disconnected():
                    print("检测到前端断开，正在停止后端生成...")
                    # 退出循环，response 的生成器会自动关闭，向 OpenAI 发送连接关闭信号
                    break

                # 处理 RunError 事件
                if hasattr(event, "event") and getattr(event, "event", None) == "RunError":
                    error_content = getattr(event, "content", str(event))
                    # 打印详细错误到控制台（用于调试）
                    my_logger.error(f"RunError 事件 - 详细错误信息: {error_content}")
                    print(f"【RunError】{error_content}")  # 同时打印到控制台

                    # 返回给前端统一友好提示
                    error_event = RunContentEvent(
                        content="大模型调用失败，请联系开发人员",
                        agent_id="v1.0.0",
                        run_id=run_id,
                        session_id=session_id,
                    )
                    yield error_event.to_json(separators=None, indent=None)
                    return

                # 记录正文内容
                if isinstance(event, RunContentEvent) and event.content:
                    accumulated_text += event.content
                    # 记录最后一个内容事件作为元数据模板
                    reference_event = event

                # 识别所有结束信号并拦截
                if isinstance(event, (ModelRequestCompletedEvent, RunContentCompletedEvent, RunCompletedEvent)):
                    completion_events.append(event)
                    continue

                yield event.to_json(separators=None, indent=None)

            # 在发送结束信号前，处理引用
            if not await request.is_disconnected():
                runtime_ctx = get_tool_runtime_context()
                rag_results = runtime_ctx.get("rag_results", [])
                web_results = runtime_ctx.get("web_results", [])

                # 匹配正文中实际出现的 ID
                used_ids = set(re.findall(r'\[([RW]\d+(?:\.\d+)?)\]', accumulated_text))
                final_references = [item for item in (rag_results + web_results) if item.get("id") in used_ids]

                if final_references:
                    ref_payload = f"\n<references>\n{json.dumps(final_references, ensure_ascii=False)}\n</references>"

                    # 基于 reference_event 克隆一个新的 RunContentEvent
                    ref_event = replace(reference_event, content=ref_payload)
                    yield ref_event.to_json(separators=None, indent=None)

                    # 将引用作为SubagentDataEvent返回，会话服务会单独保存
                    yield SubagentDataEvent(agent_name="rag_agent",
                                            data={"references": ref_payload}).model_dump_json()

                    # 遍历所有拦截到的结束事件，同步更新其 content
                    for i, ev in enumerate(completion_events):
                        # 检查对象是否有 content 属性且不为 None
                        if hasattr(ev, "content") and ev.content is not None:
                            updated_text = ev.content + ref_payload
                            # 使用 dataclass 的 replace 确保生成一个带新内容的新对象
                            completion_events[i] = replace(ev, content=updated_text)

            # 按照原始顺序释放修改后的结束事件
            for ev in completion_events:
                yield ev.to_json(separators=None, indent=None)

            my_logger.info(f"RAG智能助手输出完毕，原问题：{agent_param.query}")

        except Exception:
            my_logger.info(f"大模型调用异常 {traceback.format_exc()}")
            error_event = RunContentEvent(
                content="大模型调用失败，请联系开发人员",
                agent_id="v1.0.0",
                run_id=run_id,
                session_id=session_id,
            )
            yield error_event.to_json(separators=None, indent=None)

        finally:
            # 请求结束后必须清理运行时上下文，避免污染下一次请求。
            clear_tool_runtime_context()


def build_yield_answer(answers) -> str:
    """
    统一构建yield输出格式（JSON序列化，避免格式错乱）
    :param content: 输出内容
    :param data_type: 内容类型（text/error）
    :return: 序列化后的JSON字符串
    """
    answer = {"answers": answers}
    return json.dumps(answer, ensure_ascii=False)
