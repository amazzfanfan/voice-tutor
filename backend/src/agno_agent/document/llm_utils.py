import asyncio
import socket
from typing import List

import dashscope
from openai import OpenAI

from algo.config import (
    EBD_APIKEY,
    EBD_MODEL_NAME,
    EBD_MODEL_SERVER,
    EXTERNAL_MODEL_NAME,
    EXTERNAL_OPENAI_API_KEY,
)

# 配置千问 API 密钥
dashscope.api_key = EXTERNAL_OPENAI_API_KEY

# Embedding 客户端单例
_embedding_client = None


def get_embeddings(texts: List[str]) -> List[List[float]]:
    """调用远程 Embedding API 获取文本向量，支持批量输入"""
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = OpenAI(base_url=EBD_MODEL_SERVER, api_key=EBD_APIKEY)

    response = _embedding_client.embeddings.create(input=texts, model=EBD_MODEL_NAME)
    return [item.embedding for item in response.data]


async def call_qwen_max(prompt, temperature=0.1):
    """调用千问多模态模型"""
    try:
        socket.setdefaulttimeout(60)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: dashscope.MultiModalConversation.call(
                model=EXTERNAL_MODEL_NAME,
                messages=[{
                    "role": "user",
                    "content": [{"text": prompt}]
                }],
                temperature=temperature,
                top_p=0.7,
            )
        )

        if response.status_code == 200:
            if hasattr(response.output, 'choices') and len(response.output.choices) > 0:
                text = response.output.choices[0].message.content
            else:
                text = response.output.text

            if text is None:
                return "Error: 模型未生成有效内容"

            if isinstance(text, list):
                text = "".join([str(item) for item in text])

            return str(text).strip()
        else:
            print(f"千问API错误: {response}")
            return "Error: 调用千问模型失败"
    except socket.timeout:
        print("调用千问模型超时: 网络连接超时，请检查网络环境")
        return "Error: 网络连接超时，请稍后重试"
    except Exception as e:
        print(f"调用千问模型异常: {e}")
        error_msg = str(e)
        if "timeout" in error_msg.lower():
            return "Error: 调用超时，请稍后重试"
        elif "connection" in error_msg.lower():
            return "Error: 网络连接失败，请检查网络环境"
        else:
            return f"Error: {error_msg}"
