from fastapi import FastAPI
from typing import AsyncGenerator, Dict, Any
from algo.base_ai.prompt_templates import feature_prompt
import json
import re


MID_STATUS_LLM_START = "<问题回答>"
MID_STATUS_LLM_END = "</问题回答>"
async def ai_answer(app: FastAPI, requset_data: Dict[str, Any], intention: str, request)-> AsyncGenerator[str, None]:
    queries = requset_data.get("queries", [])
    selected_texts = requset_data.get("selectedTexts", [])
    history = queries[-7:-1]
    query_content = queries[-1].content
    prompt = f"""
你是一个文本处理助手，你的任务是结合对话记录、选择文本，然后根据用户输入完成对应的任务，完成任务是严格按照如下要求：

1. 无需给出分析过程或者理由，直接输出结果
2. 如果是翻译类的任务，直接输出译文

[对话记录]
{history}

[选择文本]
{selected_texts}

[用户输入]
{query_content}

"""
    # prompt = feature_prompt[intention](query_content, history, selected_texts)
    
    async for generate_progress in app.state.llm_model.generate_answer(prompt, request):
                if generate_progress:
                    llm_answer_accum = generate_progress["answers"][0]["content"]
                    # 拼接中间结果（大模型回答标签包裹）
                    llm_answer_accum = re.sub('</?问题回答>', '', llm_answer_accum)
                    current_content = "%s%s%s" % (MID_STATUS_LLM_START, llm_answer_accum, MID_STATUS_LLM_END)
                answer = {"answers": [{"type": "text", "content": current_content}]}
                yield json.dumps(answer, ensure_ascii=False)


async def normal_chat_answer(app: FastAPI, requset_data: Dict[str, Any], request)-> AsyncGenerator[str, None]:
    """
    通用闲聊回复
    """
    history = requset_data.get("queries", [])[-7:-1]
    query_content = requset_data.get("queries", [])[-1].content
    selected_texts = requset_data.get("selectedTexts", [])
    normal_chat_prompt = f"""
你是一位中文对话专家。
下面依次提供：
1. 最近 3 轮对话
2. 用户最新输入
3. 用户选中的多段文本（可能为空或与上下文无关）
【任务流程】
Step-1 相关性自检
快速扫一遍3，若其内容与1+2的话题、实体、逻辑链无任何明显关联，则视为“无关文本”，全程忽略。
Step-2 内容生成
语言：纯中文，口语化、简洁、有温度。
记忆：充分沿用1+2的信息，不重复追问已答内容。
知识：仅当3被判为“相关”时，才把它作为补充背景知识引用；无关则完全不提及。
安全：拒绝违法、暴力、色情、政治敏感内容。
长度：默认 120 字以内，用户要求详细可放宽。
【输入格式】
最近 3 轮对话：
{history}
用户最新输入：
{query_content}
用户选中文本：
{selected_texts}
请直接输出最终回复，禁止输出思考过程或“我忽略了选中文本”之类解释。
"""
    async for generate_progress in app.state.llm_model.generate_answer(normal_chat_prompt, request):
        if generate_progress:
            llm_answer_accum = re.sub('</?问题回答>', '', llm_answer_accum)
            current_content = "%s%s%s" % (MID_STATUS_LLM_START, llm_answer_accum, MID_STATUS_LLM_END)
        answer = {"answers": [{"type": "text", "content": current_content}]}
        yield json.dumps(answer, ensure_ascii=False)