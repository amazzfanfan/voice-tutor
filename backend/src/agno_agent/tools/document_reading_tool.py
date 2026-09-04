import asyncio
import os
import re
import shutil
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional, Dict, Any
from urllib.parse import unquote

import aiofiles
import aiohttp
from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.reader.markdown_reader import MarkdownReader

from agno_agent.document.document_processor import DocumentProcessingAgent
from algo.config import TEMP_DIR, MD_DOWNLOAD_URL, BACKEND_ACCESS_KEY, my_logger


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

@dataclass()
class DocumentInput:
    id: str
    # path: str

@dataclass
class DocumentResponse:
    """
    统一的文档处理返回格式
    """
    status: str  # "success" 或 "error"
    mode: str    # "full_text" (全量) 或 "chunked_analysis" (分片处理)
    filename: str
    content: str  # 全量文本或处理后的摘要/答案
    metadata: Dict[str, Any] = field(default_factory=dict)
    message: Optional[str] = None  # 错误信息

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items() if v is not None}

DOWNLOAD_URL = MD_DOWNLOAD_URL
DOWNLOAD_PATH = TEMP_DIR / "document_summarize"
ACCESS_KEY = BACKEND_ACCESS_KEY

# 决定文档是否分片的字符数阈值
CHAR_THRESHOLD = 100000
CHUNK_SIZE = 5000
OVERLAP = 500

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


async def download_single_file(session: aiohttp.ClientSession, file_data: DocumentInput, download_path: str, user_id: str):
    """下载单个文件，成功时返回文件路径，失败时返回 None"""
    # 提取字段
    file_id_val = file_data.id
    # path_str = file_data.path
    #
    # if not file_id_val or not path_str:
    #     print(f"参数缺失: {file_data}")
    #     return None

    # # 示例 path: /知识库/个人@杨洲@USR-xxxx/test/source.docx
    # parts = path_str.split('/')
    # if len(parts) > 2 and '@' in parts[2]:
    #     user_id = parts[2].split('@')[2]
    # else:
    #     user_id = "default_user"

    # 构造请求参数
    param = DownloadParam(
        accessKey=BACKEND_ACCESS_KEY,
        userId=user_id,
        fileId=file_id_val,
        downloadFormat="md"
    )

    try:
        async with session.post(DOWNLOAD_URL, json=asdict(param)) as resp:
            if resp.status != 200:
                print(f"下载失败 (file_id={file_id_val}): HTTP {resp.status}")
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

            print(f"成功下载: {filepath}")
            return filepath

    except Exception as e:
        print(f"下载异常 (file_id={file_id_val}): {e}")
        return None


async def batch_download_md_file(file_data_list: List[DocumentInput], download_path: str, user_id: str) -> List[str]:
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
            download_single_file(session, file_data, download_path, user_id)
            for file_data in file_data_list
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

        print(f"下载完成: 成功 {success_count} 个, 失败 {fail_count} 个")
        return downloaded_paths


# async def chunk_md_file(file_path) -> List[Chunk]:
#     reader = MarkdownReader()
#     raw_chunks = await reader.async_read(Path(file_path))
#     return [
#         Chunk(
#             raw_chunk.content,
#             str(Path(file_path).name),
#             raw_chunk.meta_data["chunk"],
#             raw_chunk.meta_data["chunk_size"],
#         )
#         for raw_chunk in raw_chunks
#     ]

async def chunk_md_file(file_path) -> List[Chunk]:
    # 定义固定大小切分策略：每块 5000 字符，重叠 500 字符
    # 你可以根据需求调整 chunk_size
    fixed_strategy = FixedSizeChunking(chunk_size=CHUNK_SIZE, overlap=OVERLAP)

    # 初始化 Reader 时传入该策略
    reader = MarkdownReader(chunking_strategy=fixed_strategy)

    raw_chunks = await reader.async_read(Path(file_path))

    return [
        Chunk(
            raw_chunk.content,
            str(Path(file_path).name),
            # 这里的 metadata 取值取决于 Agno 具体版本返回的 key，
            # 如果 key 不存在，可以使用 enumerate 的索引
            raw_chunk.meta_data.get("chunk", i),
            len(raw_chunk.content),
        )
        for i, raw_chunk in enumerate(raw_chunks)
    ]

async def document_list_chunksize_tool(documents: List[DocumentInput], user_id: str):
    """
    批量文档分片工具，处理完成后自动清理临时文件。
    """
    if not documents:
        return []

    # 1. 为本次任务创建独立子目录，避免并发任务时互相删错文件
    import uuid
    task_id = str(uuid.uuid4())[:8]
    task_download_path = DOWNLOAD_PATH / task_id
    os.makedirs(task_download_path, exist_ok=True)

    file_paths = []
    try:
        # 2. 批量下载
        file_paths = await batch_download_md_file(documents, str(task_download_path), user_id)

        if not file_paths:
            return []

        # 3. 批量分片
        chunk_tasks = [chunk_md_file(path) for path in file_paths]
        chunk_results = await asyncio.gather(*chunk_tasks, return_exceptions=True)

        all_chunks = []
        for i, result in enumerate(chunk_results):
            if isinstance(result, list):
                all_chunks.extend(result)
            else:
                # 记录失败但继续处理其他文件
                print(f"文件 {file_paths[i]} 分片失败: {result}")

        return all_chunks

    finally:
        # 4. 核心逻辑：无论成功还是报错，最终都会执行清理
        try:
            if task_download_path.exists():
                # 使用 shutil.rmtree 删除整个任务文件夹及其下的所有文件
                shutil.rmtree(task_download_path)
                print(f"临时文件已清理: {task_download_path}")
        except Exception as e:
            print(f"清理临时文件失败: {e}")

async def document_chunksize_tool(document: DocumentInput, user_id: str):
    """
    单文档处理工具：下载并根据长度判断返回模式。
    返回值: (is_chunked, data_list)
    """
    import uuid
    task_id = str(uuid.uuid4())[:8]
    task_download_path = DOWNLOAD_PATH / task_id
    os.makedirs(task_download_path, exist_ok=True)

    try:
        async with aiohttp.ClientSession() as session:
            file_path = await download_single_file(session, document, str(task_download_path), user_id)

        if not file_path or not os.path.exists(file_path):
            return False, None

        # 读取全量文本进行长度判断
        async with aiofiles.open(file_path, mode='r', encoding='utf-8', errors='ignore') as f:
            full_text = await f.read()
            char_count = len(full_text)

        # 逻辑判断
        if char_count <= CHAR_THRESHOLD:
            # --- 模式 1: 不分片，直接封装全量信息 ---
            my_logger.info(f"[Direct] 字符数 {char_count} 未超限，准备全量返回。")
            return False, {
                "filename": os.path.basename(file_path),
                "content": full_text,
                "size": char_count
            }
        else:
            # --- 模式 2: 执行分片逻辑 ---
            my_logger.info(f"[Chunk] 字符数 {char_count} 超过阈值，执行分片。")
            chunks = await chunk_md_file(file_path)
            return True, chunks

    finally:
        try:
            if task_download_path.exists():
                shutil.rmtree(task_download_path)
        except Exception as e:
            my_logger.warning(f"清理临时文件失败: {e}")


async def document_reader_tool(document: DocumentInput, user_id: str, task_type="summary", task_params=None):
    """
        高级文档分析工具。通过下载远程文档并将其转换为 Markdown 格式进行深度分析。
        适用于需要根据文档内容生成摘要、提取关键点、回答特定问题或验证文档完整性的场景。

        Args:
            document: 待处理的文档对象。
                对象必须包含:
                - id: 文件的唯一标识符
            user_id: 执行操作的用户唯一标识符，用于权限校验及日志审计。
            task_type (str): 指定要执行的处理任务。可选值包括:
                - 'summary': 生成全文摘要（默认）
                - 'key_points': 提取文档核心要点
                - 'qa': 基于文档内容回答问题
                - 'validation': 验证文档是否包含必要项
                - 'custom': 执行自定义分析指令
            task_params (dict, optional): 任务的补充参数。
                - 如果 task_type 为 'qa'，需提供 {"question": "你的问题"}
                - 如果 task_type 为 'validation'，需提供 {"required_items": "项1,项2"}
                - 如果 task_type 为 'custom'，需提供 {"instruction": "你的指令"}

        Returns:
            dict: 包含处理状态、结果文本及相关元数据的字典。
    """
    # 1. 获取数据
    is_chunked, result_data = await document_chunksize_tool(document, user_id)

    # 错误处理
    if result_data is None:
        return DocumentResponse(
            status="error",
            mode="none",
            filename=getattr(document, 'path', 'unknown'),
            content="",
            message="未能从文档中提取到有效内容"
        ).to_dict()

    # --- 情况 A: 小文件，全量返回 ---
    if not is_chunked:
        return DocumentResponse(
            status="success",
            mode="full_text",
            filename=result_data["filename"],
            content=result_data["content"],
            metadata={
                "char_count": result_data["size"],
                "direct_read": True
            }
        ).to_dict()

    # --- 情况 B: 大文件，分片逻辑 ---
    # 构造 process_chunks_logic 所需的输入
    formatted_results = [{
        "success": True,
        "filename": result_data[0].file_name,
        "chunks": [
            {"text": c.content, "metadata": {"sequence": c.sequence, "size": c.size}}
            for c in result_data
        ]
    }]

    # 执行分片处理逻辑
    processor = DocumentProcessingAgent()
    import json
    if isinstance(task_params, str):
        task_params = json.loads(task_params)
    my_logger.info(f"文档分片处理开始，task_type: {task_type}, task_params: {task_params}")
    analysis_result = await processor.process_chunks_logic(formatted_results, task_type, task_params)

    # 将 process_chunks_logic 的结果包装进统一类
    if analysis_result.get("status") == "error":
        return DocumentResponse(
            status="error",
            mode="chunked_analysis",
            filename=result_data[0].file_name,
            content="",
            message=analysis_result.get("message")
        ).to_dict()

    # 提取主要内容
    final_content = analysis_result.get("text", "")

    # 提取元数据（排除冗余字段）
    redundant_keys = ["status", "message", "text", "summary", "answer", "result", "validation_result"]
    metadata = {
        k: v for k, v in analysis_result.items()
        if k not in redundant_keys
    }

    return DocumentResponse(
        status="success",
        mode="chunked_analysis",
        filename=result_data[0].file_name,
        content=final_content,
        metadata=metadata
    ).to_dict()

document_reader_tool.__name__ = "文档阅读"
