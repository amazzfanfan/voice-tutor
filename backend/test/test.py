import asyncio
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List
from urllib.parse import unquote
import re

from openai import AsyncOpenAI
import aiofiles
import aiohttp
from agno.knowledge.reader.markdown_reader import MarkdownReader

USER_ID = os.getenv("TEST_USER_ID", "<test-user-id>")
DOWNLOAD_URL = os.getenv("DOWNLOAD_URL", "http://127.0.0.1:8080/api/files/download")
DOWNLOAD_PATH = ".\\downloads"
API_BASE_URL = os.getenv("MODEL_API_BASE", "https://api.example.com/v1")
API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
BACKEND_ACCESS_KEY = os.getenv("BACKEND_ACCESS_KEY", "")
MODEL_NAME = os.getenv("MODEL_NAME", "<model-name>")
JSON_SCHEMA = {
    "name": "extract_metadata",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "2-3句话的摘要，最多500字符，不再包含Markdown格式"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3-5个具体关键词或实体"
            }
        },
        "required": ["summary", "tags"],
        "additionalProperties": False
    }
}

PROMPT = """
你是一个Markdown文本总结助手。请分析以下Markdown文本片段并总结。

文本片段:
```
{chunk_text}
```

指令:
撰写一段摘要（2-3句话，最多500个字符），说明核心内容，但不再包含Markdown格式
    
要求：
    摘要应抓住文本精髓，而非简单重复标题
    内容需简洁精准

"""


@dataclass
class DownloadParam:
    accessKey: str
    userId: str
    fileId: str
    downloadFormat: str


@dataclass
class Chunk:
    content: str
    file_name: str
    sequence: int
    size: int


def extract_filename_from_cd(content_disposition: str) -> str:
    """
    从 Content-Disposition 头中提取 filename。
    """
    if not content_disposition:
        return "downloaded_file.md"

    # 匹配 filename="xxx" 或 filename=xxx
    fname_match = re.search(r'filename=([^;]+)', content_disposition, re.IGNORECASE)
    if not fname_match:
        return "downloaded_file.md"

    filename = fname_match.group(1).strip()
    # 去掉引号
    if filename.startswith('"') and filename.endswith('"'):
        filename = filename[1:-1]
    # 解码 URL 编码（如中文文件名）
    filename = unquote(filename)
    return filename


async def download_single_file(session: aiohttp.ClientSession, file_id: str, download_path: str):
    """下载单个文件，成功时返回文件路径，失败时返回 None"""
    # 构造请求参数
    param = DownloadParam(
        accessKey=BACKEND_ACCESS_KEY,
        userId=USER_ID,
        fileId=file_id,
        downloadFormat="md"
    )

    try:
        async with session.post(DOWNLOAD_URL, json=asdict(param)) as resp:
            if resp.status != 200:
                print(f"❌ 下载失败 (file_id={file_id}): HTTP {resp.status}")
                return None

            # 从响应头获取文件名
            cd_header = resp.headers.get('Content-Disposition')
            filename = extract_filename_from_cd(cd_header)
            # 安全处理：只保留文件名，防止路径遍历
            filename = os.path.basename(filename)
            filepath = os.path.join(download_path, filename)

            # 异步写入文件
            async with aiofiles.open(filepath, 'wb') as f:
                async for chunk in resp.content.iter_chunked(8192):
                    await f.write(chunk)

            print(f"✅ 成功下载: {filepath}")
            return filepath

    except Exception as e:
        print(f"❌ 下载异常 (file_id={file_id}): {e}")
        return None


async def batch_download_md_file(file_ids: List[str], download_path: str) -> List[str]:
    """
    批量并行下载 Markdown 文件

    :param file_ids: 文件ID列表
    :param download_path: 本地保存目录
    :return: 成功下载的文件路径列表
    """
    # 创建 ClientSession 用于复用连接
    async with aiohttp.ClientSession() as session:
        # 创建所有下载任务
        tasks = [
            download_single_file(session, file_id, download_path)
            for file_id in file_ids
        ]

        # 并发执行所有任务
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 过滤出成功的文件路径（排除 None 和异常）
        downloaded_paths = []
        success_count = 0
        fail_count = 0

        for result in results:
            if isinstance(result, str):  # 成功返回文件路径
                downloaded_paths.append(result)
                success_count += 1
            else:  # None 或异常
                fail_count += 1

        print(f"\n📊 下载完成: 成功 {success_count} 个, 失败 {fail_count} 个")
        return downloaded_paths


async def chunk_md_file(file_path) -> List[Chunk]:
    reader = MarkdownReader()
    raw_chunks = await reader.async_read(Path(file_path))
    return [
        Chunk(
            raw_chunk.content,
            str(Path(file_path).name),
            raw_chunk.meta_data["chunk"],
            raw_chunk.meta_data["chunk_size"],
        )
        for raw_chunk in raw_chunks
    ]


async def summarize_chunk(client: AsyncOpenAI, chunk: Chunk) -> Chunk:
    """使用大模型总结单个chunk的内容"""
    prompt = PROMPT.format(chunk_text=chunk.content)

    response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}]
    )

    result = response.choices[0].message.content

    return Chunk(
        content=result,
        file_name=chunk.file_name,
        sequence=chunk.sequence,
        size=len(result)
    )


FINAL_SUMMARY_PROMPT = """
你是一个文档总结助手。以下是多个Markdown文件分块的总结内容，每个分块都标明了来源文件和顺序。

请对这些内容进行整合总结，输出一份完整的文档摘要。

分块内容:
{chunks_summary}

要求:
1. 注意每个分块所属的文件和顺序
2. 整合相关主题的内容
3. 输出一份连贯的总结（3-5句话，最多1000字符）
4. 不包含Markdown格式

输出格式:
<文件名>
<总结内容>
"""


async def test():
    file_ids = ["FILE-51ebe0ba-9f70-4c68-8fdb-92f4f79773d9", "FILE-0d36f939-7628-492a-ae47-19a458451697"]
    file_paths = await batch_download_md_file(file_ids, DOWNLOAD_PATH)
    tasks = [chunk_md_file(file_path) for file_path in file_paths]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    chunks = [chunk for sublist in results for chunk in sublist if isinstance(sublist, list)]

    client = AsyncOpenAI(api_key=API_KEY, base_url=API_BASE_URL)

    summarize_tasks = [summarize_chunk(client, chunk) for chunk in chunks]
    summarized_chunks = await asyncio.gather(*summarize_tasks, return_exceptions=True)

    final_chunks = []
    for original, summarized in zip(chunks, summarized_chunks):
        if isinstance(summarized, Chunk):
            final_chunks.append(summarized)
        else:
            final_chunks.append(original)

    chunks_text = "\n".join([
        f"[{fc.file_name} - 顺序{fc.sequence}]\n{fc.content}"
        for fc in final_chunks
    ])
    final_prompt = FINAL_SUMMARY_PROMPT.format(chunks_summary=chunks_text)

    final_response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": final_prompt}]
    )

    print("\n" + final_response.choices[0].message.content)


if __name__ == '__main__':
    os.makedirs(DOWNLOAD_PATH, exist_ok=True)
    asyncio.run(test())
