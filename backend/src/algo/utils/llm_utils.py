# src/algo/utils/llm_utils.py
import json
from typing import AsyncGenerator
from openai import OpenAI

# <--- 改造点 1: 导入你的配置模块
# 这个 config.py 就是你提供的那个强大的配置加载器
from .. import config 

class LLMClient:
    """
    一个封装了OpenAI客户端的类，能够根据项目配置文件动态加载模型。
    """
    def __init__(self):
        """
        在创建实例时，从全局配置中加载并初始化OpenAI客户端。
        """
        # <--- 改造点 2: 从 config 模块获取动态加载的配置
        self.model_name = config.LLM_MODEL
        self.base_url = config.LLM_SERVER
        self.api_key = config.LLM_API_KEY

        if not self.base_url or not self.model_name:
            raise ValueError("LLM 配置不完整，请检查 model.ini 和 config.py 文件。")

        print(f"🚀 Initializing LLMClient for model: '{self.model_name}' at endpoint: '{self.base_url}'")
        
        # <--- 改造点 3: 使用加载的配置来初始化客户端
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key
        )

    async def generate_answer(self, prompt: str) -> AsyncGenerator[str, None]:
        """
        一个简单的流式生成答案的函数。
        """
        full_content = ""  # 用于累加完整文本

        # <--- 改造点 4: 使用 self.client 和 self.model_name
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            stream=True,
            stream_options={"include_usage": True}
        )

        for chunk in response:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            if delta and delta.content:
                text_delta = delta.content
                full_content += text_delta

                # 实时流式输出 (这里我们只 yield 累加后的完整文本)
                # 你可以根据需要调整输出格式
                yield full_content

