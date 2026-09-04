import os

from agno.agent import Agent
from agno.media import File
from agno.models.dashscope import DashScope

if __name__ == '__main__':
    agent = Agent(
        name="Attachment Agent",
        model=DashScope(
                base_url=os.getenv("MODEL_API_BASE", "https://api.example.com/v1"),
                api_key=os.getenv("DASHSCOPE_API_KEY", ""),
                id=os.getenv("MODEL_NAME", "<model-name>"),
                enable_thinking=False,
            )
    )
    sample_file = File(content=open("sample.txt", "rb").read())
    agent.print_response(
        input="请提取并总结这份文档的关键信息。",
        files=[sample_file],
    )
